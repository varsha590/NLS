"""Application startup and process-wide database-agnostic resources."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from catalog.classifier import is_candidate_text_column, parse_enum_options
from catalog.introspect import introspect_catalog
from config.data_policy import get_policy_overrides, load_database_overrides
from config.settings import Settings
from db.adapter import DatabaseAdapter
from llm.generator import GroqGenerator
from pipeline.orchestrator import TextToSQLPipeline
from retrieval.embeddings import EmbeddingModel
from retrieval.examples import ExampleStore
from retrieval.local_store import LocalVectorStore
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.value_index import ValueIndex
from schema.documents import (
    build_column_document,
    build_relationship_document,
    build_table_document,
)
from schema.metadata import is_internal_table_name

LOGGER = logging.getLogger(__name__)
_runtime: dict[str, Any] = {}


def _generic_policy_hash(threshold: int) -> str:
    """Fingerprint generic policy/config inputs that affect every table."""
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for relative_path in ("config/data_policy.yaml", "config/value_resolution.yaml"):
        digest.update((root / relative_path).read_bytes())
    digest.update(str(threshold).encode("ascii"))
    return digest.hexdigest()


def _config_policy_hash(threshold: int) -> str:
    """Fingerprint generic policy/config inputs that affect every table."""
    return _generic_policy_hash(threshold)


def _namespace_policy_hash(threshold: int, overrides_path: Path) -> str:
    """Fingerprint generic policy plus the active namespace's overrides file."""
    digest = hashlib.sha256()
    digest.update(_config_policy_hash(threshold).encode("ascii"))
    if overrides_path.is_file():
        digest.update(overrides_path.read_bytes())
    else:
        digest.update(b"no-database-overrides")
    return digest.hexdigest()


def _schema_records(metadata: Any) -> list[dict[str, Any]]:
    """Build schema-only documents from unprotected catalog structure."""
    records: list[dict[str, Any]] = []
    for table in metadata.tables.values():
        if is_internal_table_name(table.name):
            continue
        records.append({
            "table_name": table.name,
            "column_name": None,
            "metadata_type": "table_ddl",
            "content": build_table_document(table),
        })
        for column in table.columns:
            content = build_column_document(table, column)
            if content:
                records.append({
                    "table_name": table.name,
                    "column_name": column.name,
                    "metadata_type": "column_description",
                    "content": content,
                })
        for index, relation in enumerate(table.foreign_keys):
            content = build_relationship_document(table, relation)
            if content:
                column_name = (
                    relation.get("column")
                    or relation.get("local_column")
                    or f"relationship_{index}"
                )
                records.append({
                    "table_name": table.name,
                    "column_name": column_name,
                    "metadata_type": "relationship",
                    "content": content,
                })
    return records


def _table_fingerprint(table: Any) -> str:
    payload = {
        "name": table.name,
        "schema": table.schema,
        "comment": table.comment,
        "columns": [
            {
                "name": column.name,
                "type": column.data_type,
                "enum_options": column.enum_options or parse_enum_options(column.data_type),
                "nullable": column.nullable,
                "primary_key": column.is_primary_key,
                "foreign_key": column.is_foreign_key,
                "foreign_table": column.foreign_table,
                "foreign_column": column.foreign_column,
                "comment": column.comment,
            }
            for column in table.columns
        ],
        "primary_keys": sorted(table.primary_key_names),
        "unique_constraints": sorted(
            sorted(columns) for columns in table.unique_constraints
        ),
        "foreign_keys": sorted(
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            for item in table.foreign_keys
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _schema_fingerprints(metadata: Any) -> tuple[dict[str, str], str]:
    table_fingerprints = {
        name: _table_fingerprint(table)
        for name, table in sorted(metadata.tables.items())
        if not is_internal_table_name(name)
    }
    global_fingerprint = hashlib.sha256(
        json.dumps(table_fingerprints, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return table_fingerprints, global_fingerprint


def _scan_eligible_tables(
    metadata: Any,
    policy_overrides: dict[str, Any] | None = None,
) -> set[str]:
    overrides = policy_overrides if policy_overrides is not None else get_policy_overrides()
    result: set[str] = set()
    for table in metadata.tables.values():
        if is_internal_table_name(table.name):
            continue
        for column in table.columns:
            if (
                is_candidate_text_column(
                    table_name=table.name,
                    column_name=column.name,
                    sql_type=column.data_type,
                    is_primary_key=column.is_primary_key,
                    is_foreign_key=column.is_foreign_key,
                    overrides=overrides,
                )
                and column.enum_options is None
                and parse_enum_options(column.data_type) is None
            ):
                result.add(table.name)
                break
    return result


def init_app(
    force: bool = False,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Load a current local index or incrementally rebuild it from read-only metadata."""
    settings = Settings.from_env()
    adapter = DatabaseAdapter(settings.database_url, settings.query_timeout_seconds)
    connection = adapter.connect()
    try:
        connection.exec_driver_sql("SELECT 1")
    finally:
        connection.close()

    embedding_model = EmbeddingModel(settings.embedding_model)
    overrides_path = Path(settings.vector_store_path) / adapter.namespace() / "overrides.yaml"
    generic_policy_hash = _config_policy_hash(settings.value_cardinality_threshold)
    local_store = LocalVectorStore(
        root=settings.vector_store_path,
        namespace=adapter.namespace(),
        model_name=embedding_model.model_name,
        dimension=embedding_model.dim,
        policy_hash=_namespace_policy_hash(settings.value_cardinality_threshold, overrides_path),
        example_candidate_limit=settings.example_candidate_limit,
        clock=clock,
        embed_cache_max_entries=settings.embed_cache_max_entries,
    )

    introspect_started = time.perf_counter()
    metadata = introspect_catalog(
        adapter.engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
    )
    introspect_seconds = time.perf_counter() - introspect_started
    database_overrides, stale_overrides, override_warnings = load_database_overrides(
        overrides_path, metadata
    )
    policy_overrides = get_policy_overrides(database_overrides)
    table_fingerprints, global_fingerprint = _schema_fingerprints(metadata)
    scan_tables = _scan_eligible_tables(metadata, policy_overrides)
    now = clock() if clock is not None else time.time()
    previous_manifest = local_store.manifest
    old_table_fingerprints = previous_manifest.get("table_fingerprints", {})
    old_scan_times = previous_manifest.get("last_value_scan_at", {})
    policy_changed = previous_manifest.get("config_policy_hash") != local_store.policy_hash
    generic_policy_changed = (
        previous_manifest.get("generic_policy_hash") != generic_policy_hash
    )
    changed_tables = {
        table_name
        for table_name, fingerprint in table_fingerprints.items()
        if old_table_fingerprints.get(table_name) != fingerprint
    }
    if generic_policy_changed:
        changed_tables.update(table_fingerprints)
    force_rebuild = bool(force)
    fast_path = not force_rebuild and local_store.fast_path_valid(
        global_fingerprint,
        scan_tables,
        settings.index_refresh_ttl_hours,
        now=now,
    )

    value_index = ValueIndex(
        adapter=adapter,
        metadata=metadata,
        cardinality_threshold=settings.value_cardinality_threshold,
        embedder=embedding_model,
        local_store=local_store,
        phrase_span_limit=settings.value_phrase_span_limit,
        top_k_per_span=settings.value_top_k_per_span,
        high_cache_max_values=settings.value_high_cache_max_values,
        high_cache_total_values=settings.value_high_cache_total_values,
        high_db_lookup_limit=settings.value_high_db_lookup_limit,
        index_refresh_ttl_hours=settings.index_refresh_ttl_hours,
        database_overrides=database_overrides,
        policy_overrides=policy_overrides,
    )
    index_metrics: dict[str, Any] = {
        "path": "fast_path" if fast_path else "rebuild",
        "index_age_seconds": max(0.0, now - float(previous_manifest.get("build_time", now))),
        "stages": {
            "introspect": {
                "status": "complete",
                "seconds": round(introspect_seconds, 3),
                "tables": len(metadata.tables),
            },
            "classify": {"status": "skipped" if fast_path else "pending", "seconds": 0.0, "columns": 0},
            "scan": {"status": "skipped" if fast_path else "pending", "seconds": 0.0, "queries": 0, "tables": 0},
            "embed": {"status": "skipped" if fast_path else "pending", "seconds": 0.0, "batches": 0, "vectors": 0},
            "save": {
                "status": "skipped" if fast_path else "pending",
                "seconds": 0.0,
                "schema_vectors": local_store.count_schema(),
                "value_vectors": local_store.count_values(),
            },
        },
    }
    schema_ok = True
    value_ok = True
    incomplete_tables: dict[str, str] = {}
    if fast_path:
        value_index.load_cached(local_store.classification_cache)
    else:
        schema_changed = (
            force_rebuild
            or not local_store.part_is_valid("schema")
            or generic_policy_changed
            or bool(changed_tables)
            or set(old_table_fingerprints) != set(table_fingerprints)
        )
        embed_batches_before = local_store.embedding_batches
        embedded_vectors_before = local_store.embedded_vectors
        embedded_seconds_before = local_store.embedding_seconds
        save_seconds_before = local_store.save_seconds
        if schema_changed:
            schema_ok = local_store.build_schema(_schema_records(metadata), embedding_model)

        previous_classifications = local_store.classification_cache or {}
        stale_tables = set()
        for table_name in scan_tables:
            scanned_at = old_scan_times.get(table_name)
            if (
                force_rebuild
                or settings.index_refresh_ttl_hours <= 0
                or scanned_at is None
                or now - float(scanned_at) >= settings.index_refresh_ttl_hours * 3600
            ):
                stale_tables.add(table_name)

        value_index.build_incremental(
            classification_cache=local_store.classification_cache,
            table_fingerprints=table_fingerprints,
            changed_tables=changed_tables,
            stale_tables=stale_tables,
            value_part_valid=local_store.part_is_valid("values"),
            reuse_value_metadata=local_store.part_metadata_is_valid("values"),
            last_value_scan_at=old_scan_times,
            force=force_rebuild,
            workers=settings.index_scan_workers,
            now=now,
        )
        scan_seconds = value_index.scan_seconds
        value_ok = local_store.build_values(
            value_index.value_records,
            embedding_model,
            current_tables=set(table_fingerprints),
        )
        incomplete_tables.update(value_index.incomplete_tables)
        incomplete_tables.update({
            table_name: "embedding_error"
            for table_name in local_store.failed_value_tables
        })
        for table_name in local_store.failed_value_tables:
            previous_classification = previous_classifications.get(table_name)
            if previous_classification is not None:
                value_index.restore_table_from_store(
                    table_name, previous_classification
                )
            if table_name in old_scan_times:
                value_index.last_value_scan_at[table_name] = old_scan_times[table_name]
            else:
                value_index.last_value_scan_at.pop(table_name, None)

        previous_table_fingerprints = dict(old_table_fingerprints)
        for table_name in set(previous_table_fingerprints) - set(table_fingerprints):
            previous_table_fingerprints.pop(table_name, None)
        for table_name, fingerprint in table_fingerprints.items():
            if table_name not in incomplete_tables:
                previous_table_fingerprints[table_name] = fingerprint
        next_scan_times = {
            table: timestamp
            for table, timestamp in value_index.last_value_scan_at.items()
            if table in table_fingerprints
        }
        if schema_ok and value_ok and not incomplete_tables:
            persisted_global_fingerprint = global_fingerprint
        else:
            persisted_global_fingerprint = previous_manifest.get(
                "global_schema_fingerprint", ""
            )
        state_save_started = time.perf_counter()
        local_store.save_index_state(
            global_schema_fingerprint=persisted_global_fingerprint,
            table_fingerprints=previous_table_fingerprints,
            last_value_scan_at=next_scan_times,
            classification_cache=value_index.classification_cache,
            incomplete_tables=incomplete_tables,
            generic_policy_hash=generic_policy_hash,
        )
        state_save_seconds = time.perf_counter() - state_save_started
        index_metrics["stages"].update({
            "classify": {
                "status": "incomplete" if incomplete_tables else "complete",
                "seconds": round(value_index.classify_seconds, 3),
                "columns": sum(len(item.get("columns", {})) for item in value_index.classification_cache.values()),
            },
            "scan": {
                "status": "incomplete" if incomplete_tables else "complete",
                "seconds": round(scan_seconds, 3),
                "queries": value_index.scan_count,
                "tables": value_index.scanned_tables,
            },
            "embed": {
                "status": "incomplete" if not value_ok or not schema_ok else "complete",
                "seconds": round(local_store.embedding_seconds - embedded_seconds_before, 3),
                "batches": local_store.embedding_batches - embed_batches_before,
                "vectors": local_store.embedded_vectors - embedded_vectors_before,
            },
            "save": {
                "status": "incomplete" if not value_ok or not schema_ok else "complete",
                "seconds": round(
                    local_store.save_seconds - save_seconds_before + state_save_seconds,
                    3,
                ),
                "schema_vectors": local_store.count_schema(),
                "value_vectors": local_store.count_values(),
            },
        })

    index_complete = schema_ok and value_ok and not incomplete_tables
    if not index_complete:
        LOGGER.warning(
            "Local index build completed with errors",
            extra={
                "dialect": adapter.get_dialect(),
                "incomplete_tables": sorted(incomplete_tables),
                "error_categories": sorted(set(incomplete_tables.values())),
            },
        )

    retriever = HybridSchemaRetriever(
        metadata,
        embedding_model,
        local_store=local_store,
        policy_overrides=policy_overrides,
    )
    generator = GroqGenerator(settings.groq_api_key, settings.llm_model)
    examples = ExampleStore(
        settings.vector_store_path,
        adapter,
        local_store=local_store,
        candidate_limit=settings.example_candidate_limit,
    )
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=metadata,
        retriever=retriever,
        generator=generator,
        value_index=value_index,
        examples=examples,
        max_rows=settings.max_rows,
        max_retries=settings.max_retries,
        schema_top_k=settings.schema_top_k,
        value_top_k=settings.value_top_k,
        send_high_cardinality_values_to_llm=settings.send_high_cardinality_values_to_llm,
    )

    catalog_status = (
        "incomplete"
        if not index_complete
        else "cached" if fast_path
        else "indexed"
    )
    runtime = {
        "settings": settings,
        "adapter": adapter,
        "engine": adapter.engine,
        "metadata": metadata,
        "retriever": retriever,
        "local_store": local_store,
        "value_index": value_index,
        "examples": examples,
        "pipeline": pipeline,
        "indexed_tables": len(metadata.tables),
        "catalog_status": catalog_status,
        "index_complete": index_complete,
        "incomplete_tables": incomplete_tables,
        "index_metrics": index_metrics,
        "stale_overrides": stale_overrides,
        "override_warnings": override_warnings,
        "overrides_path": str(overrides_path),
    }
    _runtime.clear()
    _runtime.update(runtime)
    LOGGER.info(
        "Application ready",
        extra={"dialect": adapter.get_dialect(), "indexed_tables": len(metadata.tables)},
    )
    LOGGER.info(
        "Local index startup stages",
        extra={"index_metrics": index_metrics},
    )
    return runtime


def get_runtime() -> dict[str, Any]:
    """Return resources created by the most recent successful initialization."""
    if not _runtime:
        raise RuntimeError("Application startup has not completed.")
    return _runtime