"""Portable indexing and conservative resolution of database values."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import sqlalchemy as sa
import yaml
from rapidfuzz import fuzz, process

from db.adapter import DatabaseAdapter
from retrieval.local_store import LocalVectorStore
from schema.metadata import SchemaMetadata, is_internal_table_name
from catalog.classifier import (
    ColumnClass,
    classify_column as classify_catalog_column,
    get_column_stats,
    is_candidate_text_column,
    parse_enum_options,
)
from config.data_policy import get_policy_overrides

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
        local_store: LocalVectorStore | None = None,
    ) -> None:
        self.adapter = adapter
        self.metadata = metadata
        self.threshold = cardinality_threshold
        self.values: dict[str, list[str]] = {}
        self.large_columns: set[str] = set()
        self.embeddings: dict[str, np.ndarray] = {}
        self.embedder = embedder
        self.local_store = local_store
        self.build_success = True
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

    def _is_internal_table(self, table: Any) -> bool:
        """Recognize common metadata/index structures by name or by structural columns."""
        if is_internal_table_name(table.name):
            return True
        names = {column.name.casefold() for column in table.columns}
        return (
            {"table_name", "column_name"}.issubset(names)
            or {"embedding", "relationships", "business_relevance"}.issubset(names)
        )

    def _is_value_column(self, column: Any, table_name: str = "") -> bool:
        """Check column eligibility using the unified classifier."""
        policy_overrides = get_policy_overrides()
        col_class, _ = classify_catalog_column(
            table_name=table_name,
            column_name=column.name,
            sql_type=column.type,
            overrides=policy_overrides,
            cardinality_threshold=self.threshold,
        )
        return col_class not in (ColumnClass.BLOCKED, ColumnClass.MASKED, ColumnClass.SKIP)

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
        """Index only VALUE_LOW data, using metadata options for ENUM/SET columns."""
        self.values.clear()
        self.large_columns.clear()
        self.embeddings.clear()
        self.build_success = True
        value_records: list[dict[str, str]] = []
        policy_overrides = get_policy_overrides()

        for table_info in self.metadata.tables.values():
            if self._is_internal_table(table_info):
                continue
            bare_table_name = table_info.name.rsplit(".", 1)[-1]
            reflected = sa.Table(
                bare_table_name,
                sa.MetaData(),
                schema=table_info.schema,
                autoload_with=self.adapter.engine,
            )
            table_key = table_info.name
            for column_info in table_info.columns:
                column = reflected.c.get(column_info.name)
                if column is None:
                    continue
                key = f"{table_key}.{column_info.name}"

                # 1. Preliminary check without DB query
                if not is_candidate_text_column(
                    table_name=table_key,
                    column_name=column_info.name,
                    sql_type=column.type,
                    is_primary_key=column_info.is_primary_key,
                    is_foreign_key=column_info.is_foreign_key,
                    overrides=policy_overrides,
                ):
                    continue

                options = parse_enum_options(column.type)
                if options is not None:
                    cnt = len(options)
                    avg_len = (
                        sum(len(option) for option in options) / cnt if cnt else 0.0
                    )
                else:
                    stats_errors: list[str] = []
                    try:
                        with self.adapter.engine.connect() as connection:
                            cnt, avg_len = get_column_stats(
                                connection,
                                reflected,
                                column_info.name,
                                threshold=self.threshold,
                                on_error=stats_errors.append,
                            )
                    except sa.exc.SQLAlchemyError:
                        cnt, avg_len = None, None
                        stats_errors.append("database_error")
                    if cnt is None:
                        self.build_success = False

                # Final classification is shared with the report and policy boundary.
                final_class, _ = classify_catalog_column(
                    table_name=table_key,
                    column_name=column_info.name,
                    sql_type=column.type,
                    distinct_count=cnt,
                    avg_text_length=avg_len,
                    is_primary_key=column_info.is_primary_key,
                    is_foreign_key=column_info.is_foreign_key,
                    overrides=policy_overrides,
                    cardinality_threshold=self.threshold,
                )

                if final_class == ColumnClass.VALUE_HIGH:
                    self.large_columns.add(key)
                    continue
                elif final_class != ColumnClass.VALUE_LOW:
                    continue

                if options is not None:
                    values = [str(option) for option in options]
                else:
                    try:
                        with self.adapter.engine.connect() as connection:
                            query = (
                                sa.select(column)
                                .where(column.is_not(None))
                                .distinct()
                                .limit(self.threshold + 1)
                            )
                            raw_values = connection.execute(query).scalars().all()
                    except sa.exc.SQLAlchemyError:
                        self.build_success = False
                        continue
                    if len(raw_values) > self.threshold:
                        self.large_columns.add(key)
                        continue
                    values = [str(value) for value in raw_values]

                values = [value for value in values if not self._is_schema_value(value)]
                if not values:
                    continue
                self.values[key] = values
                for value in values:
                    value_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                    value_records.append({
                        "table_name": table_key,
                        "column_name": column_info.name,
                        "classification": ColumnClass.VALUE_LOW.value,
                        "value_hash": value_hash,
                        "value": value,
                    })

        if self.embedder is not None and self.local_store is not None:
            self.build_success = self.local_store.build_values(value_records, self.embedder) and self.build_success
        elif self.embedder is not None:
            for key, values in self.values.items():
                self.embeddings[key] = self.embedder.embed(values)
        return self.values

    def report(self) -> list[dict[str, Any]]:
        """Describe indexed columns by count without returning row values."""
        rows: list[dict[str, Any]] = []
        for column, values in sorted(self.values.items()):
            rows.append({
                "column": column,
                "count": len(values),
            })
        for column in sorted(self.large_columns):
            rows.append({
                "column": column,
                "count": None,
            })
        return rows

    def _score_candidates(self, mention: str, column: str | None, top_k: int) -> list[dict[str, Any]]:
        candidate_values = [
            (key, value)
            for key, values in self.values.items()
            if column is None or key == column
            for value in values
            if not self._is_schema_value(value)
        ]
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
        vector_scores: dict[tuple[str, str], float] = {}
        if query_embedding is not None and self.local_store is not None:
            table_filter, column_filter = (column.rsplit(".", 1) if column else (None, None))
            search_results = self.local_store.search_values(
                query_embedding,
                top_k=len(unique),
                table=table_filter,
                column=column_filter,
            )
            vector_scores = {
                (f"{item['table_name']}.{item['column_name']}", item["value"]): item["similarity"]
                for item in search_results
            }
        candidates = []
        for index, (candidate_column, value) in enumerate(unique):
            lexical_score = lexical_scores.get(index, 0.0)
            vector_score = vector_scores.get((candidate_column, value), 0.0)
            if query_embedding is not None and self.local_store is None and candidate_column in self.embeddings:
                indexed_values = self.values.get(candidate_column, [])
                try:
                    value_vector = self.embeddings[candidate_column][indexed_values.index(value)]
                    denominator = np.linalg.norm(query_embedding) * np.linalg.norm(value_vector)
                    vector_score = max(0.0, float(np.dot(query_embedding, value_vector) / denominator)) if denominator else 0.0
                except (ValueError, IndexError):
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
        for indices in by_column.values():
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