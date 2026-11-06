"""Portable indexing and conservative resolution of database values."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import sqlalchemy as sa
import yaml
from rapidfuzz import fuzz, process

from db.adapter import DatabaseAdapter
from retrieval.qdrant_store import QdrantVectorStore
from schema.metadata import SchemaMetadata, is_internal_table_name
from catalog.classifier import (
    ColumnClass,
    classify_column as classify_catalog_column,
    is_candidate_text_column,
    is_pii_shaped_value,
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
        local_store: QdrantVectorStore | None = None,
        phrase_span_limit: int = 40,
        top_k_per_span: int = 5,
        high_cache_max_values: int = 20000,
        high_cache_total_values: int = 200000,
        high_db_lookup_limit: int = 20,
        index_refresh_ttl_hours: float = 24.0,
        database_overrides: dict[str, Any] | None = None,
        policy_overrides: dict[str, Any] | None = None,
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
        self.database_overrides = database_overrides or {}
        self.policy_overrides = policy_overrides or (
            get_policy_overrides(self.database_overrides)
            if self.database_overrides
            else get_policy_overrides()
        )
        resolution_overrides = self.database_overrides.get("value_resolution", {})
        if isinstance(resolution_overrides, dict):
            for key, value in resolution_overrides.items():
                if isinstance(value, dict) and isinstance(self.config.get(key), dict):
                    self.config[key] = {**self.config[key], **value}
                elif isinstance(value, list) and isinstance(self.config.get(key), list):
                    self.config[key] = list(dict.fromkeys([*self.config[key], *value]))
                else:
                    self.config[key] = value
            synonyms = resolution_overrides.get("synonyms", {})
            if isinstance(synonyms, dict):
                cue_aliases = dict(self.config.get("cue_aliases", {}))
                for semantic, terms in synonyms.items():
                    cue_aliases[semantic] = list(dict.fromkeys([
                        *cue_aliases.get(semantic, []), *terms
                    ]))
                self.config["cue_aliases"] = cue_aliases
        self.thresholds = self.config.get("thresholds", {})
        self.accept_score = float(self.thresholds.get("accept_score", 0.88))
        self.ambiguous_gap = float(self.thresholds.get("ambiguous_gap", 0.08))
        self.min_score = float(self.thresholds.get("min_score", 0.65))
        self.max_candidates = int(self.thresholds.get("max_candidates", 5))
        self.phrase_span_limit = max(1, int(phrase_span_limit))
        self.top_k_per_span = max(1, int(top_k_per_span))
        self.high_cache_max_values = max(1, int(high_cache_max_values))
        self.high_cache_total_values = max(1, int(high_cache_total_values))
        self.high_db_lookup_limit = max(1, int(high_db_lookup_limit))
        self.high_cache_ttl_seconds = max(0.0, float(index_refresh_ttl_hours) * 3600)
        self.high_value_cache: OrderedDict[str, tuple[float, list[str] | None]] = OrderedDict()
        self.high_value_cache_count = 0
        self.high_resolution_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.uncacheable_high_columns: set[str] = set()
        self.call_counts = {
            "embedding_calls": 0,
            "vector_searches": 0,
        }
        self.last_call_counts = {
            "embedding_calls": 0,
            "vector_searches": 0,
            "value_lookup_db_calls": 0,
        }
        self.unmatched_high_count = 0
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
        self.classification_cache: dict[str, Any] = {}
        self.value_records: list[dict[str, str]] = []
        self.incomplete_tables: dict[str, str] = {}
        self.last_value_scan_at: dict[str, float] = {}
        self.scan_count = 0
        self.scanned_tables = 0
        self.scan_seconds = 0.0
        self.classify_seconds = 0.0

    def reset_question_counts(self) -> None:
        self.call_counts = {"embedding_calls": 0, "vector_searches": 0}
        self.unmatched_high_count = 0
        self.high_resolution_cache.clear()

    def _high_column_values(self, column_key: str) -> list[str] | None:
        """Return a cached bounded high-cardinality column, or None when oversized."""
        now = time.monotonic()
        cached = self.high_value_cache.get(column_key)
        if cached is not None:
            expires_at, values = cached
            if expires_at >= now:
                self.high_value_cache.move_to_end(column_key)
                return values
            if values is not None:
                self.high_value_cache_count -= len(values)
            del self.high_value_cache[column_key]

        table_name, column_name = column_key.rsplit(".", 1)
        table_info = self.metadata.tables.get(table_name)
        if table_info is None or column_name not in {col.name for col in table_info.columns}:
            return None
        self.call_counts["value_lookup_db_calls"] = self.call_counts.get(
            "value_lookup_db_calls", 0
        ) + 1
        values = self.adapter.distinct_text_values(
            table_info, column_name, self.high_cache_max_values + 1
        )
        expires_at = now + self.high_cache_ttl_seconds
        if len(values) > self.high_cache_max_values:
            self.high_value_cache[column_key] = (expires_at, None)
            self.uncacheable_high_columns.add(column_key)
            self._evict_high_columns()
            return None

        self.high_value_cache[column_key] = (expires_at, values)
        self.high_value_cache_count += len(values)
        self._evict_high_columns()
        current = self.high_value_cache.get(column_key)
        return current[1] if current is not None else None

    def _evict_high_columns(self) -> None:
        while (
            self.high_value_cache_count > self.high_cache_total_values
            or len(self.high_value_cache) > self.high_cache_total_values
        ) and self.high_value_cache:
            _, (_, values) = self.high_value_cache.popitem(last=False)
            if values is not None:
                self.high_value_cache_count -= len(values)

    def resolve_high_value(self, column_key: str, mention: str) -> dict[str, Any]:
        """Resolve VALUE_HIGH text locally; oversized columns use a bounded SQL lookup."""
        cache_key = (column_key, mention.casefold())
        cached_result = self.high_resolution_cache.get(cache_key)
        if cached_result is not None:
            return dict(cached_result)
        self.call_counts.setdefault("value_lookup_db_calls", 0)
        if column_key not in self.large_columns:
            return {"status": "not_found", "candidates": []}
        values = self._high_column_values(column_key)
        if values is None:
            table_name, column_name = column_key.rsplit(".", 1)
            table_info = self.metadata.tables.get(table_name)
            if table_info is None or column_name not in {col.name for col in table_info.columns}:
                self.unmatched_high_count += 1
                return {"status": "not_found", "candidates": []}
            self.call_counts["value_lookup_db_calls"] = self.call_counts.get(
                "value_lookup_db_calls", 0
            ) + 1
            candidates = self.adapter.lookup_text_candidates(
                table_info, column_name, mention, self.high_db_lookup_limit
            )
        else:
            candidates = values

        exact = [value for value in candidates if value == mention]
        if exact:
            result = {"status": "resolved", "value": exact[0], "candidates": []}
            self.high_resolution_cache[cache_key] = result
            return dict(result)
        casefolded = [value for value in candidates if value.casefold() == mention.casefold()]
        if len(casefolded) == 1:
            result = {"status": "resolved", "value": casefolded[0], "candidates": []}
            self.high_resolution_cache[cache_key] = result
            return dict(result)
        if len(casefolded) > 1:
            result = {"status": "ambiguous", "candidates": casefolded[:self.max_candidates]}
            self.high_resolution_cache[cache_key] = result
            return dict(result)

        matches = process.extract(
            mention,
            candidates,
            scorer=_mention_value_score,
            limit=min(self.max_candidates + 1, len(candidates)),
        )
        scored = [
            {"column": column_key, "value": str(value), "confidence": score / 100}
            for value, score, _ in matches
            if score / 100 >= self.min_score
        ]
        if not scored:
            self.unmatched_high_count += 1
            result = {"status": "not_found", "candidates": []}
            self.high_resolution_cache[cache_key] = result
            return dict(result)
        best = scored[0]
        close = [
            item for item in scored
            if best["confidence"] - item["confidence"] < self.ambiguous_gap
        ]
        if best["confidence"] >= self.accept_score and len(close) == 1:
            result = {"status": "resolved", "value": best["value"], "candidates": []}
            self.high_resolution_cache[cache_key] = result
            return dict(result)
        if len(close) > 1:
            result = {"status": "ambiguous", "candidates": close[:self.max_candidates]}
            self.high_resolution_cache[cache_key] = result
            return dict(result)
        self.unmatched_high_count += 1
        result = {"status": "not_found", "candidates": []}
        self.high_resolution_cache[cache_key] = result
        return dict(result)

    def _is_internal_table(self, table: Any) -> bool:
        """Recognize common metadata/index structures by name or by structural columns."""
        if is_internal_table_name(table.name):
            return True
        names = {column.name.casefold() for column in table.columns}
        return (
            {"table_name", "column_name"}.issubset(names)
            or {"embedding", "relationships", "business_relevance"}.issubset(names)
        )

    def _table_policy_fingerprint(self, table_name: str) -> str:
        bare_name = table_name.rsplit(".", 1)[-1].casefold()
        scoped = {}
        for action in (
            "force_block", "force_mask", "force_allow", "force_value_low", "force_value_high"
        ):
            scoped[action] = sorted(
                target
                for target in self.policy_overrides.get(action, [])
                if str(target).rsplit(".", 1)[0].casefold() in {table_name.casefold(), bare_name}
            )
        payload = json.dumps(scoped, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _is_value_column(self, column: Any, table_name: str = "") -> bool:
        """Check column eligibility using the unified classifier."""
        col_class, _ = classify_catalog_column(
            table_name=table_name,
            column_name=column.name,
            sql_type=column.type,
            overrides=self.policy_overrides,
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

    @staticmethod
    def _error_category(error: Exception) -> str:
        if isinstance(error, sa.exc.OperationalError):
            return "operational_or_connection_error"
        if isinstance(error, sa.exc.ProgrammingError):
            return "query_or_schema_error"
        if isinstance(error, sa.exc.DataError):
            return "data_error"
        if isinstance(error, sa.exc.SQLAlchemyError):
            return "database_error"
        return "unexpected_error"

    def _scan_column(
        self, connection: Any, table: Any, column_name: str
    ) -> tuple[list[Any], int]:
        started = time.perf_counter()
        column = table.c[column_name]
        bounded_values = (
            sa.select(column.label("value"))
            .where(column.is_not(None))
            .distinct()
            .limit(self.threshold + 1)
            .subquery("bounded_values")
        )
        row_count = sa.select(
            sa.literal_column("COUNT(*)").label("non_null_count")
        ).select_from(table).where(column.is_not(None)).subquery("column_counts")
        query = sa.select(
            bounded_values.c.value,
            row_count.c.non_null_count,
        ).select_from(row_count.outerjoin(bounded_values, sa.true()))
        rows = connection.execute(query).all()
        self.scan_seconds += time.perf_counter() - started
        values = [row[0] for row in rows if row[0] is not None]
        non_null_count = int(rows[0][1]) if rows and rows[0][1] is not None else 0
        return values, non_null_count

    @staticmethod
    def column_fingerprint(column_info: Any) -> str:
        payload = {
            "name": column_info.name,
            "type": column_info.data_type,
            "enum_options": column_info.enum_options,
            "nullable": column_info.nullable,
            "primary_key": column_info.is_primary_key,
            "foreign_key": column_info.is_foreign_key,
            "foreign_table": column_info.foreign_table,
            "foreign_column": column_info.foreign_column,
            "comment": column_info.comment,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _process_table(
        self,
        table_info: Any,
        table_fingerprint: str,
        policy_overrides: dict[str, Any],
        connection: Any,
    ) -> tuple[dict[str, Any], dict[str, list[str]], int]:
        bare_table_name = table_info.name.rsplit(".", 1)[-1]
        table = sa.table(
            bare_table_name,
            *(sa.column(column.name, sa.String()) for column in table_info.columns),
            schema=table_info.schema,
        )
        columns: dict[str, Any] = {}
        column_fingerprints: dict[str, str] = {}
        indexed_values: dict[str, list[str]] = {}
        scans = 0
        for column_info in table_info.columns:
            column_fingerprints[column_info.name] = self.column_fingerprint(column_info)
            column_type = column_info.data_type
            options = column_info.enum_options or parse_enum_options(column_type)
            candidate = is_candidate_text_column(
                table_name=table_info.name,
                column_name=column_info.name,
                sql_type=column_type,
                is_primary_key=column_info.is_primary_key,
                is_foreign_key=column_info.is_foreign_key,
                overrides=policy_overrides,
            )
            values: list[Any] = []
            non_null_count: int | None = None
            if candidate and options is not None:
                distinct_count = len(options)
                average_length = (
                    sum(len(option) for option in options) / distinct_count
                    if distinct_count
                    else 0.0
                )
                values = list(options)
                clean_shape = not any(is_pii_shaped_value(option) for option in options)
            elif candidate:
                values, non_null_count = self._scan_column(
                    connection, table, column_info.name
                )
                scans += 1
                distinct_count = len(values)
                average_length = (
                    sum(len(str(value)) for value in values) / distinct_count
                    if distinct_count
                    else 0.0
                )
                clean_shape = not any(is_pii_shaped_value(value) for value in values)
            else:
                distinct_count = None
                average_length = None
                clean_shape = False

            column_class, reason = classify_catalog_column(
                table_name=table_info.name,
                column_name=column_info.name,
                sql_type=column_type,
                distinct_count=distinct_count,
                avg_text_length=average_length,
                nullable=column_info.nullable,
                is_primary_key=column_info.is_primary_key,
                is_foreign_key=column_info.is_foreign_key,
                overrides=policy_overrides,
                cardinality_threshold=self.threshold,
                sensitive_values_clean=clean_shape,
            )
            columns[column_info.name] = {
                "class": column_class.value,
                "reason": reason,
                "distinct_count": distinct_count,
                "non_null_count": non_null_count,
                "avg_text_length": average_length,
            }
            if column_class == ColumnClass.VALUE_LOW:
                key = f"{table_info.name}.{column_info.name}"
                filtered = [str(value) for value in values if not self._is_schema_value(str(value))]
                if filtered:
                    indexed_values[key] = list(dict.fromkeys(filtered))

        return (
            {
                "fingerprint": table_fingerprint,
                "policy_fingerprint": self._table_policy_fingerprint(table_info.name),
                "column_fingerprints": column_fingerprints,
                "columns": columns,
            },
            indexed_values,
            scans,
        )

    def _restore_table_values(self, table_name: str) -> None:
        for record in getattr(self.local_store, "values_meta", []):
            if record.get("table_name") != table_name:
                continue
            column = str(record.get("column_name", ""))
            value = record.get("value")
            if value is not None:
                self.values.setdefault(f"{table_name}.{column}", []).append(str(value))

    def restore_table_from_store(
        self, table_name: str, classification: dict[str, Any]
    ) -> None:
        """Restore resolver state for a table whose new embeddings failed."""
        prefix = f"{table_name}."
        for key in [key for key in self.values if key.startswith(prefix)]:
            self.values.pop(key, None)
        self.large_columns = {
            key for key in self.large_columns if not key.startswith(prefix)
        }
        self.classification_cache[table_name] = classification
        for column_name, entry in classification.get("columns", {}).items():
            if entry.get("class") == ColumnClass.VALUE_HIGH.value:
                self.large_columns.add(f"{table_name}.{column_name}")
        self._restore_table_values(table_name)

    def load_cached(self, classification_cache: dict[str, Any] | None = None) -> None:
        """Restore resolver state exclusively from validated local metadata files."""
        self.values.clear()
        self.large_columns.clear()
        self.classification_cache = classification_cache or {}
        for table_name, table_cache in self.classification_cache.items():
            for column_name, entry in table_cache.get("columns", {}).items():
                if entry.get("class") == ColumnClass.VALUE_HIGH.value:
                    self.large_columns.add(f"{table_name}.{column_name}")
            self._restore_table_values(table_name)

    def build_incremental(
        self,
        classification_cache: dict[str, Any] | None,
        table_fingerprints: dict[str, str],
        changed_tables: set[str],
        stale_tables: set[str],
        value_part_valid: bool,
        reuse_value_metadata: bool = False,
        last_value_scan_at: dict[str, float] | None = None,
        force: bool = False,
        workers: int = 1,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Reuse fresh table classifications and rescan only changed or stale tables."""
        self.values.clear()
        self.large_columns.clear()
        self.embeddings.clear()
        self.build_success = True
        self.incomplete_tables.clear()
        self.scan_count = 0
        self.scanned_tables = 0
        self.scan_seconds = 0.0
        scan_started = time.perf_counter()
        policy_overrides = self.policy_overrides
        previous_cache = classification_cache or {}
        prior_scan_times = dict(last_value_scan_at or {})
        now_value = time.time() if now is None else float(now)
        active_tables = {
            table.name: table
            for table in self.metadata.tables.values()
            if not self._is_internal_table(table)
        }
        tables_to_process = set(changed_tables) | set(stale_tables)
        if (
            force
            or (not value_part_valid and not reuse_value_metadata)
            or classification_cache is None
        ):
            tables_to_process.update(active_tables)
        for table_name in active_tables:
            cached = previous_cache.get(table_name)
            if (
                cached is None
                or cached.get("fingerprint") != table_fingerprints.get(table_name)
                or cached.get("policy_fingerprint")
                != self._table_policy_fingerprint(table_name)
            ):
                tables_to_process.add(table_name)

        def process_table(table_name: str, connection: Any) -> tuple[str, Any, Any, int, str | None]:
            try:
                cache, values, scans = self._process_table(
                    active_tables[table_name],
                    table_fingerprints[table_name],
                    policy_overrides,
                    connection,
                )
                return table_name, cache, values, scans, None
            except (sa.exc.SQLAlchemyError, RuntimeError, ValueError, TypeError, KeyError) as error:
                return table_name, None, None, 0, self._error_category(error)

        processed: dict[str, tuple[Any, Any, int, str | None]] = {}
        queued = sorted(tables_to_process & set(active_tables))
        worker_count = min(8, max(1, int(workers)))
        tables_needing_connection = {
            table_name
            for table_name in queued
            if any(
                is_candidate_text_column(
                    table_name=table_name,
                    column_name=column.name,
                    sql_type=column.data_type,
                    is_primary_key=column.is_primary_key,
                    is_foreign_key=column.is_foreign_key,
                    overrides=policy_overrides,
                )
                and column.enum_options is None
                and parse_enum_options(column.data_type) is None
                for column in active_tables[table_name].columns
            )
        }
        if worker_count == 1:
            if tables_needing_connection:
                connection_context = self.adapter.readonly_connection()
            else:
                connection_context = None
            if connection_context is None:
                for table_name in queued:
                    _, cache, values, scans, error = process_table(table_name, None)
                    processed[table_name] = (cache, values, scans, error)
            else:
                with connection_context as connection:
                    for table_name in queued:
                        _, cache, values, scans, error = process_table(table_name, connection)
                        processed[table_name] = (cache, values, scans, error)
        elif queued:
            def process_with_connection(table_name: str):
                if table_name not in tables_needing_connection:
                    return process_table(table_name, None)
                with self.adapter.readonly_connection() as connection:
                    return process_table(table_name, connection)

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                for table_name, cache, values, scans, error in executor.map(
                    process_with_connection, queued
                ):
                    processed[table_name] = (cache, values, scans, error)

        self.classification_cache = {}
        for table_name in active_tables:
            current_fingerprint = table_fingerprints[table_name]
            cached = previous_cache.get(table_name)
            processed_table = processed.get(table_name)
            if processed_table is not None:
                cache, values, scans, error = processed_table
                if error is not None:
                    self.incomplete_tables[table_name] = error
                    self.build_success = False
                    if cached is not None:
                        self.classification_cache[table_name] = cached
                        self.large_columns.update(
                            f"{table_name}.{column_name}"
                            for column_name, entry in cached.get("columns", {}).items()
                            if entry.get("class") == ColumnClass.VALUE_HIGH.value
                        )
                        self._restore_table_values(table_name)
                    continue
                self.classification_cache[table_name] = cache
                self.large_columns.update(
                    f"{table_name}.{column_name}"
                    for column_name, entry in cache.get("columns", {}).items()
                    if entry.get("class") == ColumnClass.VALUE_HIGH.value
                )
                for key, column_values in values.items():
                    self.values[key] = column_values
                self.scan_count += scans
                if scans:
                    self.scanned_tables += 1
                    prior_scan_times[table_name] = now_value
            elif cached is not None and cached.get("fingerprint") == current_fingerprint:
                self.classification_cache[table_name] = cached
                for column_name, entry in cached.get("columns", {}).items():
                    if entry.get("class") == ColumnClass.VALUE_HIGH.value:
                        self.large_columns.add(f"{table_name}.{column_name}")
                self._restore_table_values(table_name)
            else:
                self.incomplete_tables[table_name] = "classification_cache_missing"
                self.build_success = False

        self.last_value_scan_at = prior_scan_times
        self.classify_seconds = max(
            0.0, time.perf_counter() - scan_started - self.scan_seconds
        )
        self.value_records = []
        for key, values in sorted(self.values.items()):
            table_name, column_name = key.rsplit(".", 1)
            for value in values:
                self.value_records.append({
                    "table_name": table_name,
                    "column_name": column_name,
                    "classification": ColumnClass.VALUE_LOW.value,
                    "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    "value": value,
                })
        return self.values

    def build(self) -> dict[str, list[str]]:
        """Perform a complete value classification and persist VALUE_LOW vectors."""
        fingerprints = {table.name: "full-build" for table in self.metadata.tables.values()}
        self.build_incremental(
            classification_cache=None,
            table_fingerprints=fingerprints,
            changed_tables=set(fingerprints),
            stale_tables=set(),
            value_part_valid=False,
            force=True,
        )
        if self.embedder is not None and self.local_store is not None:
            self.build_success = self.local_store.build_values(
                self.value_records, self.embedder
            ) and self.build_success
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

    def _score_candidate_batch(
        self,
        mentions: list[str],
        columns: list[str | None],
        top_k: int,
    ) -> list[list[dict[str, Any]]]:
        """Embed spans once and score only the bounded Qdrant shortlist per span."""
        self.last_call_counts = {
            "embedding_calls": 0,
            "vector_searches": 0,
            "value_lookup_db_calls": 0,
        }
        if not mentions:
            return []

        query_embeddings = None
        if self.embedder is not None:
            query_embeddings = self.embedder.embed(mentions)
            self.call_counts["embedding_calls"] = self.call_counts.get("embedding_calls", 0) + 1

        search_limit = min(max(1, int(top_k)), self.top_k_per_span)
        scored: list[list[dict[str, Any]]] = []
        exact_by_column = {
            key: {value.casefold(): value for value in values}
            for key, values in self.values.items()
        }

        for position, mention in enumerate(mentions):
            column = columns[position]
            exact_value = None
            exact_column = column
            if column is not None:
                exact_value = exact_by_column.get(column, {}).get(mention.casefold())
            else:
                for candidate_column, value_map in exact_by_column.items():
                    match = value_map.get(mention.casefold())
                    if match is not None:
                        exact_column, exact_value = candidate_column, match
                        break

            if query_embeddings is not None and self.local_store is not None:
                table_filter, column_filter = (
                    column.rsplit(".", 1) if column else (None, None)
                )
                search_results = self.local_store.search_values(
                    query_embeddings[position:position + 1],
                    top_k=search_limit,
                    table=table_filter,
                    column=column_filter,
                    tenant_id=self.local_store.tenant_id,
                    dataset_id=self.local_store.dataset_id,
                    dataset_metadata_path=self.local_store.dataset_metadata_path,
                    embedding_model_name=self.local_store.model_name,
                    dimension=self.local_store.vector_size,
                )
                self.last_call_counts["vector_searches"] += 1
                self.call_counts["vector_searches"] = self.call_counts.get("vector_searches", 0) + 1
                candidates = []
                for item in search_results:
                    candidate_column = f"{item['table_name']}.{item['column_name']}"
                    value = str(item["value"])
                    lexical_score = _mention_value_score(mention, value) / 100
                    vector_score = max(0.0, float(item.get("similarity", 0.0)))
                    confidence = max(lexical_score, 0.8 * lexical_score + 0.2 * vector_score)
                    if mention.casefold() == value.casefold():
                        confidence = 1.0
                    candidates.append({
                        "column": candidate_column,
                        "value": value,
                        "confidence": confidence,
                    })
            else:
                candidate_values = [
                    (key, value)
                    for key, values in self.values.items()
                    if column is None or key == column
                    for value in values
                    if not self._is_schema_value(value)
                ]
                matches = process.extract(
                    mention,
                    [value for _, value in candidate_values],
                    scorer=_mention_value_score,
                    limit=search_limit,
                )
                candidates = [
                    {
                        "column": candidate_values[index][0],
                        "value": candidate_values[index][1],
                        "confidence": score / 100,
                    }
                    for _, score, index in matches
                ]

            if exact_value is not None and exact_column is not None:
                candidates = [
                    item for item in candidates
                    if (item["column"], item["value"]) != (exact_column, exact_value)
                ]
                candidates.insert(0, {
                    "column": exact_column,
                    "value": exact_value,
                    "confidence": 1.0,
                })

            subset_matches = [
                item for item in candidates
                if _is_token_subset_or_prefix(mention, item["value"])
            ]
            if len(subset_matches) == 1:
                subset_matches[0]["confidence"] = max(
                    subset_matches[0]["confidence"], 0.95
                )
            candidates.sort(key=lambda item: item["confidence"], reverse=True)
            scored.append(candidates[:search_limit])
        return scored

    def _score_candidates(self, mention: str, column: str | None, top_k: int) -> list[dict[str, Any]]:
        """Score one mention through the same bounded batch path used per question."""
        return self._score_candidate_batch([mention], [column], top_k)[0]

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
        eligible_columns = set(self.values) | self.large_columns
        cues = self.config.get("cue_aliases", {})
        for semantic, cue_words in cues.items():
            if not words.intersection({word.casefold() for word in cue_words}):
                continue
            for column in eligible_columns:
                table_name, column_name = column.rsplit(".", 1)
                vocabulary = _word_forms(table_name) | _word_forms(column_name)
                if semantic in vocabulary or any(alias.casefold() in vocabulary for alias in cue_words):
                    result.add(column)
        if not result:
            for column in eligible_columns:
                _, column_name = column.rsplit(".", 1)
                column_words = _word_forms(column_name)
                result.update(
                    key for key in eligible_columns
                    if key == column and words.intersection(column_words)
                )
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
        if len(spans) <= self.phrase_span_limit:
            return spans
        stride = len(spans) / self.phrase_span_limit
        return [spans[int(index * stride)] for index in range(self.phrase_span_limit)]

    def _direct_cue_value(self, question: str, span: dict[str, Any]) -> tuple[str | None, set[str]]:
        """Find a category/product/city/department cue immediately before or after a mention."""
        before = question[:span["start"]]
        before_words = [match.group().casefold() for match in _TOKEN_RE.finditer(before)]
        after = question[span["end"]:]
        after_words = [match.group().casefold() for match in _TOKEN_RE.finditer(after)]
        cue_aliases = self.config.get("cue_aliases", {})
        known_column_cues = {
            word
            for key in set(self.values) | self.large_columns
            for word in _word_forms(key.rsplit(".", 1)[-1])
        }
        for semantic, aliases in cue_aliases.items():
            alias_set = {alias.casefold() for alias in aliases}
            if before_words and before_words[-1] in alias_set:
                columns = self._cue_columns({semantic.casefold()})
                return semantic, columns
            if after_words and after_words[0] in alias_set:
                columns = self._cue_columns({semantic.casefold()})
                return semantic, columns
        for cue_word in (*before_words[-1:], *after_words[:1]):
            if cue_word in known_column_cues:
                return cue_word, self._cue_columns({cue_word})
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
        eligible_spans: list[dict[str, Any]] = []
        cue_columns_by_span: list[set[str]] = []
        for span in spans:
            mention = span["mention"]
            cue, cue_columns = self._direct_cue_value(question, span)

            # Metric-like words ("sales") only count when a cue names their type.
            if not self._is_cued_metric_mention(question, mention, cue):
                continue
            eligible_spans.append(span)
            cue_columns_by_span.append(cue_columns)

        low_value_spans = [
            (span, columns)
            for span, columns in zip(eligible_spans, cue_columns_by_span, strict=True)
            if not columns or not columns.issubset(self.large_columns)
        ]
        scored_by_span = self._score_candidate_batch(
            [span["mention"] for span, _ in low_value_spans],
            [next(iter(columns)) if len(columns) == 1 else None for _, columns in low_value_spans],
            min(max(top_k, self.max_candidates), self.top_k_per_span),
        )
        score_lookup = {
            id(span): matches
            for (span, _), matches in zip(low_value_spans, scored_by_span, strict=True)
        }
        for span, cue_columns, matches in zip(
            eligible_spans,
            cue_columns_by_span,
            [score_lookup.get(id(span), []) for span in eligible_spans],
            strict=True,
        ):
            mention = span["mention"]
            if cue_columns:
                matches = [candidate for candidate in matches if candidate["column"] in cue_columns]
            matches = [candidate for candidate in matches if candidate["confidence"] >= self.min_score]
            high_columns = cue_columns & self.large_columns
            high_resolutions = [
                (column, self.resolve_high_value(column, mention))
                for column in sorted(high_columns)
            ]
            high_resolutions = [
                (column, resolution)
                for column, resolution in high_resolutions
                if resolution["status"] != "not_found"
            ]
            if high_resolutions:
                if len(high_resolutions) > 1 or any(
                    resolution["status"] == "ambiguous"
                    for _, resolution in high_resolutions
                ):
                    candidates = [
                        candidate
                        for column, resolution in high_resolutions
                        for candidate in resolution.get("candidates", [])
                        or ([{"column": column, "value": resolution["value"], "confidence": 1.0}]
                            if resolution.get("status") == "resolved" else [])
                    ]
                    output.append({
                        "mention": mention,
                        "ambiguous": True,
                        "high_cardinality": True,
                        "candidates": candidates[:self.max_candidates],
                        "confidence": 0.0,
                        "start": span["start"],
                        "end": span["end"],
                        "exact_match": False,
                    })
                else:
                    column, resolution = high_resolutions[0]
                    output.append({
                        "mention": mention,
                        "column": column,
                        "value": resolution["value"],
                        "high_cardinality": True,
                        "confidence": 1.0,
                        "start": span["start"],
                        "end": span["end"],
                        "exact_match": mention.casefold() == resolution["value"].casefold(),
                    })
                continue
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
                    "high_cardinality": bool(high_columns),
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