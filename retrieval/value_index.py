"""Portable indexing and conservative resolution of database values."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import sqlalchemy as sa
import yaml
from rapidfuzz import fuzz, process

from db.adapter import DatabaseAdapter, EmbeddingStore
from schema.metadata import SchemaMetadata

LOGGER = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "value_resolution.yaml"
_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d")
_DATE_WORDS = {
    "january", "jan", "february", "feb", "march", "mar", "april", "apr",
    "may", "june", "jun", "july", "jul", "august", "aug", "september",
    "sep", "sept", "october", "oct", "november", "nov", "december", "dec",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def _load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def _normalize(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _mention_value_score(mention: str, value: str, **_: Any) -> float:
    left = mention.casefold().strip()
    right = value.casefold().strip()
    if not left or not right:
        return 0.0
    if left == right:
        return 100.0
    ratio = fuzz.ratio(left, right)
    partial = fuzz.partial_ratio(left, right)
    coverage = min(len(left), len(right)) / max(len(left), len(right))
    return max(float(ratio), float(partial) * (0.5 + 0.5 * coverage))


def _is_token_subset_or_prefix(mention: str, value: str) -> bool:
    mention_tokens = set(_TOKEN_RE.findall(mention.casefold()))
    value_tokens = set(_TOKEN_RE.findall(value.casefold()))
    if not mention_tokens or not value_tokens:
        return False
    if mention_tokens.issubset(value_tokens):
        return True
    if value.casefold().startswith(mention.casefold()):
        return True
    return False


def _word_forms(value: str) -> set[str]:
    token = value.casefold().replace("_", " ")
    forms = {part for part in _TOKEN_RE.findall(token) if part}
    for part in tuple(forms):
        if part.endswith("ies") and len(part) > 4:
            forms.add(part[:-3] + "y")
        elif part.endswith("s") and len(part) > 3:
            forms.add(part[:-1])
        else:
            forms.add(part + "s")
    return forms


class ValueIndex:
    """Index bounded distinct values from semantic text columns only."""

    def __init__(
        self,
        adapter: DatabaseAdapter,
        metadata: SchemaMetadata,
        cardinality_threshold: int = 500,
        embedder: Any = None,
        storage_path: str | Path | None = None,
        embedding_store: EmbeddingStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.metadata = metadata
        self.threshold = cardinality_threshold
        self.values: dict[str, list[str]] = {}
        self.large_columns: set[str] = set()
        self.embeddings: dict[str, np.ndarray] = {}
        self.embedder = embedder
        self.storage_path = (
            Path(storage_path) / adapter.namespace() / "values.json"
            if storage_path is not None else None
        )
        self.config = _load_config()
        self.thresholds = self.config.get("thresholds", {})
        self.accept_score = float(self.thresholds.get("accept_score", 0.88))
        self.ambiguous_gap = float(self.thresholds.get("ambiguous_gap", 0.08))
        self.min_score = float(self.thresholds.get("min_score", 0.65))
        self.max_candidates = int(self.thresholds.get("max_candidates", 5))
        self.excluded_terms = {
            token.casefold()
            for token in self.config.get("excluded_terms", [])
        } | _DATE_WORDS
        self.schema_names = set(metadata.tables)
        self.schema_names.update(
            f"{table.name}.{column.name}"
            for table in metadata.tables.values()
            for column in table.columns
        )
        schema_vocabulary: set[str] = set()
        for table in metadata.tables.values():
            schema_vocabulary.update(_word_forms(table.name))
            for column in table.columns:
                schema_vocabulary.update(_word_forms(column.name))
        self.schema_vocabulary = schema_vocabulary
        self.excluded_terms.update(schema_vocabulary)
        self.metric_terms = {
            term.casefold()
            for term in self.config.get("metric_value_names", [])
        }
        self.excluded_terms.update(self.metric_terms)
        self.metric_term_cues = {
            term.casefold(): {cue.casefold() for cue in cues}
            for term, cues in self.config.get("cued_metric_terms", {}).items()
        }
        self.value_column_allowlist = {
            name.casefold()
            for name in self.config.get("value_column_allowlist", [])
        }
        self.value_column_suffixes = tuple(
            suffix.casefold()
            for suffix in self.config.get("value_column_patterns", {}).get("suffixes", [])
        )
        self.value_column_names = {
            name.casefold()
            for name in self.config.get("value_column_patterns", {}).get("exact_names", [])
        }
        self.excluded_column_names = {
            name.casefold()
            for name in self.config.get("excluded_column_names", [])
        }
        self.status_filter_column_names = {
            name.casefold()
            for name in self.config.get("status_filter_column_names", [])
        }
        self.activity_query_expansion = tuple(
            str(term) for term in self.config.get("activity_query_expansion", [])
        )
        self.embedding_store = embedding_store

    def _is_internal_table(self, table: Any) -> bool:
        """Recognize common metadata/index structures by their structural columns."""
        names = {column.name.casefold() for column in table.columns}
        return (
            {"table_name", "column_name", "values"}.issubset(names)
            or {"embedding", "relationships", "business_relevance"}.issubset(names)
        )

    def _is_value_column(self, column: Any) -> bool:
        """Check text type and configured semantics before indexing a column."""
        column_name = column.name.casefold()
        if column_name in self.excluded_column_names:
            return False
        if self.value_column_allowlist:
            configured = column_name in self.value_column_allowlist
        else:
            configured = (
                column_name in self.value_column_names
                or column_name.endswith(self.value_column_suffixes)
            )
        if not configured:
            return False
        type_name = str(column.type).lower()
        return any(marker in type_name for marker in ("char", "text", "string"))

    def _is_schema_value(self, value: str) -> bool:
        """Reject values that are table/column/metric vocabulary, not row data."""
        normalized = _normalize(value)
        if not normalized:
            return True
        if normalized in {_normalize(name) for name in self.schema_names}:
            return True
        if normalized in self.metric_terms:
            return True
        words = set(normalized.split())
        return bool(words) and words.issubset(self.schema_vocabulary)

    def build(self) -> dict[str, list[str]]:
        """Index distinct values only from eligible reflected data columns."""
        self.values.clear()
        self.large_columns.clear()
        self.embeddings.clear()

        for table_info in self.metadata.tables.values():
            if self._is_internal_table(table_info):
                continue
            table_name = table_info.name.rsplit(".", 1)[-1]
            reflected = sa.Table(
                table_name,
                sa.MetaData(),
                schema=table_info.schema,
                autoload_with=self.adapter.engine,
            )
            for column_info in table_info.columns:
                column = reflected.c.get(column_info.name)
                if column is None or not self._is_value_column(column):
                    continue
                key = f"{table_info.name}.{column_info.name}"
                try:
                    with self.adapter.engine.connect() as connection:
                        query = (
                            sa.select(column)
                            .where(column.is_not(None))
                            .distinct()
                            .limit(self.threshold + 1)
                        )
                        raw_values = connection.execute(query).scalars().all()
                    if len(raw_values) > self.threshold:
                        self.large_columns.add(key)
                        continue
                    values = [str(value) for value in raw_values]
                    values = [value for value in values if not self._is_schema_value(value)]
                    if not values:
                        continue
                    self.values[key] = values

                    # Upsert embeddings to PostgreSQL via EmbeddingStore
                    if self.embedder is not None and self.embedding_store is not None:
                        namespace = self.embedding_store.namespace
                        embeddings_list = self.embedder.embed(values)
                        for i, value in enumerate(values):
                            content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                            embedding = embeddings_list[i].tolist()
                            self.embedding_store.upsert_value(
                                table_name=table_name,
                                column_name=column_info.name,
                                value=value,
                                content_hash=content_hash,
                                embedding=embedding,
                            )
                        # Load embeddings into memory for scoring
                        value_embeddings = self.embedding_store.get_value_embeddings(
                            table_name, column_info.name
                        )
                        self.embeddings[key] = np.array([value_embeddings[v] for v in values if v in value_embeddings])
                    elif self.embedder is not None:
                        self.embeddings[key] = self.embedder.embed(values)
                except (sa.exc.SQLAlchemyError, KeyError):
                    LOGGER.debug("Value index skipped a column", extra={"column": key})
        if self.storage_path is not None:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(
                json.dumps({
                    "values": self.values,
                    "embeddings": {
                        key: vectors.tolist() for key, vectors in self.embeddings.items()
                    },
                }),
                encoding="utf-8",
            )
        return self.values

    def report(self, sample_size: int = 5) -> list[dict[str, Any]]:
        """Describe the index: value count and a small sample per configured column."""
        rows: list[dict[str, Any]] = []
        for column, values in sorted(self.values.items()):
            rows.append({
                "column": column,
                "count": len(values),
                "samples": list(values[:sample_size]),
            })
        for column in sorted(self.large_columns):
            rows.append({
                "column": column,
                "count": None,
                "samples": [],
            })
        return rows

    def forbidden_values(self) -> list[tuple[str, str]]:
        """Return indexed values that are table, column, or metric vocabulary."""
        forbidden: list[tuple[str, str]] = []
        for column, values in self.values.items():
            for value in values:
                if self._is_schema_value(value):
                    forbidden.append((column, value))
        return forbidden

    def _score_candidates(self, mention: str, column: str | None, top_k: int) -> list[dict[str, Any]]:
        candidate_values = [
            (key, value)
            for key, values in self.values.items()
            if column is None or key == column
            for value in values
            if not self._is_schema_value(value)
        ]
        if column and column in self.large_columns:
            table_name, column_name = column.rsplit(".", 1)
            if self.embedding_store is not None:
                # Use EmbeddingStore.search_values for high-cardinality columns (0b fix).
                # Embed the mention once and search via the store.
                if self.embedder is not None:
                    span_embedding = self.embedder.embed([mention])[0].tolist()
                    store_results = self.embedding_store.search_values(
                        query_embedding=span_embedding,
                        top_k=top_k,
                    )
                    candidate_values.extend(
                        (column, result["value"])
                        for result in store_results
                        if result.get("table_name") == table_name
                        and result.get("column_name") == column_name
                        and not self._is_schema_value(result["value"])
                    )
                else:
                    LOGGER.debug(
                        "High-cardinality lookup skipped: no embedder",
                        extra={"column": column},
                    )
            else:
                LOGGER.debug(
                    "High-cardinality lookup skipped: no embedding_store",
                    extra={"column": column},
                )
        unique = list(dict.fromkeys(candidate_values))
        if not unique:
            return []
        lexical_matches = process.extract(
            mention,
            [value for _, value in unique],
            scorer=_mention_value_score,
            limit=len(unique),
        )
        lexical_scores = {index: score / 100 for _, score, index in lexical_matches}
        query_embedding = self.embedder.embed([mention])[0] if self.embedder is not None else None
        candidates = []
        for index, (candidate_column, value) in enumerate(unique):
            lexical_score = lexical_scores.get(index, 0.0)
            vector_score = 0.0
            indexed_values = self.values.get(candidate_column, [])
            if query_embedding is not None and candidate_column in self.values:
                try:
                    value_index = indexed_values.index(value)
                    # Try to get vector score from EmbeddingStore first
                    if self.embedding_store is not None:
                        namespace = self.embedding_store.namespace
                        search_results = self.embedding_store.search_values(
                            query_embedding=query_embedding.tolist(),
                            top_k=1,
                            namespace=namespace,
                        )
                        if search_results:
                            for result in search_results:
                                if result.get("value") == value:
                                    vector_score = result.get("similarity", 0.0)
                                    break
                    else:
                        # Fall back to numpy computation if no EmbeddingStore
                        value_vector = self.embeddings[candidate_column][value_index]
                        denominator = np.linalg.norm(query_embedding) * np.linalg.norm(value_vector)
                        vector_score = max(0.0, float(np.dot(query_embedding, value_vector) / denominator)) if denominator else 0.0
                except (ValueError, IndexError, KeyError):
                    vector_score = 0.0
            confidence = max(
                lexical_score,
                0.8 * lexical_score + 0.2 * vector_score if query_embedding is not None else lexical_score,
            )
            if mention.casefold() == value.casefold():
                confidence = 1.0
            candidates.append({
                "column": candidate_column,
                "value": value,
                "confidence": confidence,
            })

        # Boost unique token-subset/prefix matches per column
        from collections import defaultdict
        by_column: dict[str, list[int]] = defaultdict(list)
        for i, cand in enumerate(candidates):
            by_column[cand["column"]].append(i)
        for col, indices in by_column.items():
            subset_indices = [
                i for i in indices
                if _is_token_subset_or_prefix(mention, candidates[i]["value"])
            ]
            if len(subset_indices) == 1:
                # Unique token-subset/prefix match in this column -> strong signal
                candidates[subset_indices[0]]["confidence"] = max(
                    candidates[subset_indices[0]]["confidence"], 0.95
                )

        candidates.sort(key=lambda candidate: candidate["confidence"], reverse=True)
        return candidates[:top_k]

    def resolve(self, mention: str, column: str | None = None, top_k: int = 5) -> dict[str, Any]:
        """Apply configured accept/ambiguity thresholds for one mention."""
        candidates = [
            candidate for candidate in self._score_candidates(mention, column, top_k)
            if candidate["confidence"] >= self.min_score
        ]
        if not candidates:
            return {"resolved": None, "candidates": []}
        best = candidates[0]
        close = [
            candidate for candidate in candidates
            if best["confidence"] - candidate["confidence"] < self.ambiguous_gap
        ]
        if best["confidence"] >= self.accept_score and len(close) == 1:
            return {"resolved": best, "candidates": candidates}
        if len(close) >= 2:
            return {"resolved": None, "candidates": close}
        return {"resolved": None, "candidates": []}

    def _cue_columns(self, words: set[str]) -> set[str]:
        """Map configured cue terms to reflected columns without table literals in code."""
        result: set[str] = set()
        cues = self.config.get("cue_aliases", {})
        for semantic, cue_words in cues.items():
            if not words.intersection({word.casefold() for word in cue_words}):
                continue
            for column in self.values:
                table_name, column_name = column.rsplit(".", 1)
                vocabulary = _word_forms(table_name) | _word_forms(column_name)
                if semantic in vocabulary or any(alias.casefold() in vocabulary for alias in cue_words):
                    result.add(column)
        return result

    def _eligible_tokens(self, question: str) -> list[tuple[str, int, int]]:
        tokens = [(match.group(), match.start(), match.end()) for match in _TOKEN_RE.finditer(question)]
        return [
            (word, start, end)
            for word, start, end in tokens
            if word.casefold() not in self.excluded_terms and not _NUMBER_RE.search(word)
        ]

    def _candidate_spans(self, question: str) -> list[dict[str, Any]]:
        tokens = self._eligible_tokens(question)
        all_tokens = list(_TOKEN_RE.finditer(question))
        spans: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        for first in range(len(tokens)):
            for last in range(first, min(first + 6, len(tokens))):
                start, end = tokens[first][1], tokens[last][2]
                if (start, end) in seen:
                    continue
                seen.add((start, end))
                mention = question[start:end].strip(" ,.;:?!\"'()[]{}")
                mention_tokens = [match.group() for match in _TOKEN_RE.finditer(mention)]
                while mention_tokens and mention_tokens[0].casefold() in self.excluded_terms:
                    mention_tokens.pop(0)
                while mention_tokens and mention_tokens[-1].casefold() in self.excluded_terms:
                    mention_tokens.pop()
                while mention_tokens and mention_tokens[0].casefold() in self.excluded_terms:
                    mention_tokens.pop(0)
                if not mention_tokens:
                    continue
                mention = " ".join(mention_tokens)
                if not mention or any(_NUMBER_RE.search(word) for word in mention_tokens):
                    continue
                spans.append({"mention": mention, "start": start, "end": end, "tokens": mention_tokens})
        return spans

    def _direct_cue_value(self, question: str, span: dict[str, Any]) -> tuple[str | None, set[str]]:
        """Find a category/product/city/department cue immediately before or after a mention."""
        before = question[:span["start"]]
        before_words = [match.group().casefold() for match in _TOKEN_RE.finditer(before)]
        after = question[span["end"]:]
        after_words = [match.group().casefold() for match in _TOKEN_RE.finditer(after)]
        cue_aliases = self.config.get("cue_aliases", {})
        for semantic, aliases in cue_aliases.items():
            alias_set = {alias.casefold() for alias in aliases}
            if before_words and before_words[-1] in alias_set:
                columns = self._cue_columns({semantic.casefold()})
                return semantic, columns
            if after_words and after_words[0] in alias_set:
                columns = self._cue_columns({semantic.casefold()})
                return semantic, columns
        return None, set()

    def _is_cued_metric_mention(self, question: str, mention: str, cue: str | None) -> bool:
        """Allow a metric-like word only when cued or when nothing else gives it meaning."""
        words = {word.casefold() for word in _TOKEN_RE.findall(mention)}
        cued_words = words & set(self.metric_term_cues)
        if not cued_words:
            return True
        for word in cued_words:
            if cue in self.metric_term_cues[word]:
                return True
        if cue is not None:
            return False
        question_words = {match.group().casefold() for match in _TOKEN_RE.finditer(question)}
        other_metrics = (question_words & self.metric_terms) - set(self.metric_term_cues)
        return not other_metrics

    def resolve_question(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Resolve only value-like phrases, apply cue/not-found rules, then prune overlaps."""
        spans = self._candidate_spans(question)
        output: list[dict[str, Any]] = []
        for span in spans:
            mention = span["mention"]
            cue, cue_columns = self._direct_cue_value(question, span)

            # Metric-like words ("sales") only count when a cue names their type.
            if not self._is_cued_metric_mention(question, mention, cue):
                continue

            matches = self._score_candidates(mention, None, max(top_k, self.max_candidates))
            if cue_columns:
                matches = [candidate for candidate in matches if candidate["column"] in cue_columns]
            matches = [candidate for candidate in matches if candidate["confidence"] >= self.min_score]
            if matches:
                best = matches[0]
                close = [
                    candidate for candidate in matches
                    if best["confidence"] - candidate["confidence"] < self.ambiguous_gap
                ]
                if best["confidence"] >= self.accept_score and len(close) == 1:
                    output.append({
                        "mention": mention,
                        "column": best["column"],
                        "value": best["value"],
                        "confidence": best["confidence"],
                        "start": span["start"],
                        "end": span["end"],
                        "exact_match": mention.casefold() == best["value"].casefold(),
                    })
                elif len(close) >= 2 and all(candidate["confidence"] >= self.min_score for candidate in close):
                    output.append({
                        "mention": mention,
                        "ambiguous": True,
                        "candidates": close[:self.max_candidates],
                        "confidence": best["confidence"],
                        "start": span["start"],
                        "end": span["end"],
                        "exact_match": False,
                    })
                continue

            capitalized_unknown = any(
                word[:1].isupper() and word.casefold() not in self.schema_vocabulary
                for word in _TOKEN_RE.findall(mention)
            )
            if (cue and cue_columns) or capitalized_unknown:
                output.append({
                    "mention": mention,
                    "not_found": True,
                    "column": next(iter(cue_columns), None),
                    "candidates": [],
                    "confidence": 0.0,
                    "start": span["start"],
                    "end": span["end"],
                    "exact_match": False,
                })

        def overlap_sort_key(item: dict[str, Any]) -> tuple:
            """Sort key: exact_match desc, span length desc, confidence desc, start asc."""
            span_len = int(item["end"]) - int(item["start"])
            return (
                -int(item.get("exact_match", False)),
                -span_len,
                -float(item.get("confidence", 0.0)),
                int(item["start"]),
            )

        output.sort(key=overlap_sort_key)
        selected: list[dict[str, Any]] = []
        for item in output:
            overlaps = any(
                int(item["start"]) < int(existing["end"])
                and int(item["end"]) > int(existing["start"])
                for existing in selected
            )
            if not overlaps:
                selected.append(item)
        selected.sort(key=lambda item: int(item["start"]))
        for item in selected:
            item.pop("start", None)
            item.pop("end", None)
            item.pop("exact_match", None)
        return selected