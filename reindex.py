"""Force-refresh or preview the local schema and value index."""

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from catalog.classifier import is_candidate_text_column, parse_enum_options
from catalog.introspect import introspect_catalog
from config.data_policy import get_policy_overrides
from config.settings import Settings
from core.startup import _schema_fingerprints, init_app
from db.adapter import DatabaseAdapter
from retrieval.value_index import ValueIndex


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _file_checksum(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_only_probe(adapter: DatabaseAdapter) -> None:
    with adapter.readonly_connection() as connection:
        connection.exec_driver_sql("SELECT 1")


def create_dry_run_plan(
    settings: Settings,
    adapter: DatabaseAdapter,
) -> dict[str, int | float]:
    """Plan a forced rebuild from schema metadata and local counts only."""
    started = time.perf_counter()
    metadata = introspect_catalog(
        adapter.engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
    )
    table_fingerprints, global_fingerprint = _schema_fingerprints(metadata)
    del global_fingerprint
    store_path = Path(settings.vector_store_path) / adapter.namespace()
    manifest = _read_json(store_path / "manifest.json") or {}
    classification_path = store_path / "classification_cache.json"
    classification_payload = _read_json(classification_path) or {}
    if (
        not manifest.get("classification_cache_sha256")
        or _file_checksum(classification_path)
        != manifest.get("classification_cache_sha256")
    ):
        classification_payload = {}
    previous_classifications = classification_payload.get("tables", {})
    old_table_fingerprints = manifest.get("table_fingerprints", {})
    changed_tables = sum(
        old_table_fingerprints.get(table) != fingerprint
        for table, fingerprint in table_fingerprints.items()
    ) + len(set(old_table_fingerprints) - set(table_fingerprints))

    changed_columns = 0
    scan_columns = 0
    overrides = get_policy_overrides()
    current_columns = 0
    for table in metadata.tables.values():
        if table.name not in table_fingerprints:
            continue
        current_columns += len(table.columns)
        old_column_fingerprints = previous_classifications.get(table.name, {}).get(
            "column_fingerprints", {}
        )
        current_column_fingerprints = {
            column.name: ValueIndex.column_fingerprint(column)
            for column in table.columns
        }
        if old_column_fingerprints:
            changed_columns += sum(
                old_column_fingerprints.get(column) != fingerprint
                for column, fingerprint in current_column_fingerprints.items()
            ) + len(set(old_column_fingerprints) - set(current_column_fingerprints))
        else:
            changed_columns += len(table.columns)
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
                scan_columns += 1

    values_meta_path = store_path / "values_meta.json"
    values_meta = _read_json(values_meta_path)
    if (
        not isinstance(values_meta, list)
        or _file_checksum(values_meta_path) != manifest.get("values_meta_sha256")
    ):
        values_meta = []
    cached_hashes = {
        str(record.get("value_hash", ""))
        for record in values_meta
        if record.get("value_hash")
    }
    embedding_model = str(settings.embedding_model)
    if manifest.get("embedding_model_name") != embedding_model:
        known_values_to_embed = len(cached_hashes)
    else:
        cache_path = store_path / "embed_cache.sqlite"
        cache_hits: set[str] = set()
        if cache_path.is_file() and cached_hashes:
            try:
                with sqlite3.connect(cache_path) as connection:
                    for content_hash in cached_hashes:
                        row = connection.execute(
                            "SELECT 1 FROM embeddings WHERE content_hash = ? AND model_name = ?",
                            (content_hash, embedding_model),
                        ).fetchone()
                        if row:
                            cache_hits.add(content_hash)
            except sqlite3.DatabaseError:
                cache_hits.clear()
        known_values_to_embed = len(cached_hashes - cache_hits)

    estimated_new_values = scan_columns * settings.value_cardinality_threshold
    estimated_values_to_embed = known_values_to_embed + estimated_new_values
    elapsed = time.perf_counter() - started
    estimated_seconds = (
        elapsed
        + 0.02 * scan_columns
        + 0.002 * estimated_values_to_embed
        + 0.005 * current_columns
    )
    return {
        "tables": len(table_fingerprints),
        "tables_changed": int(changed_tables),
        "columns_changed": changed_columns,
        "columns_to_scan": scan_columns,
        "estimated_values_to_embed": estimated_values_to_embed,
        "estimated_seconds": round(estimated_seconds, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect schema metadata and print a counts-only forced rebuild estimate.",
    )
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            settings = Settings.from_env()
            adapter = DatabaseAdapter(
                "sqlite:///:memory:", settings.query_timeout_seconds,
            )
            _read_only_probe(adapter)
            plan = create_dry_run_plan(settings, adapter)
            print("Read-only re-index dry run")
            print(f"Tables: {plan['tables']}")
            print(f"Tables changed: {plan['tables_changed']}")
            print(f"Columns changed: {plan['columns_changed']}")
            print(f"Columns to scan: {plan['columns_to_scan']}")
            print(f"Estimated values to embed: {plan['estimated_values_to_embed']}")
            print(f"Estimated seconds: {plan['estimated_seconds']}")
        else:
            init_app(force=True)
    except Exception as error:
        logging.error("Schema reindexing failed", extra={"error_type": type(error).__name__})
        return 1
    logging.info("Schema re-indexing completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())