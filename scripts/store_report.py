"""Print local index inventory counts without exposing indexed row values."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import faiss

from config.settings import Settings
from db.adapter import DatabaseAdapter
from catalog.introspect import introspect_catalog
from config.data_policy import load_database_overrides


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _matches_checksum(path: Path, expected: str | None) -> bool:
    if not expected or not path.is_file():
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == expected


def format_store_report(
    root: str | Path,
    namespace: str,
    stale_overrides: list[str] | None = None,
    override_warnings: list[str] | None = None,
) -> str:
    """Return classes, counts, and manifest metadata; never format value text."""
    store_path = Path(root) / namespace
    manifest = _read_json(store_path / "manifest.json") or {}
    classification_payload = _read_json(store_path / "classification_cache.json") or {}
    classification_path = store_path / "classification_cache.json"
    if not _matches_checksum(
        classification_path, manifest.get("classification_cache_sha256")
    ):
        classification_payload = {}
    classifications = classification_payload.get("tables", {})

    values_meta_path = store_path / "values_meta.json"
    values_meta = _read_json(values_meta_path)
    if not _matches_checksum(values_meta_path, manifest.get("values_meta_sha256")):
        values_meta = []
    if not isinstance(values_meta, list):
        values_meta = []

    vector_count_by_column: dict[tuple[str, str], int] = {}
    values_count_by_column: dict[tuple[str, str], int] = {}
    for record in values_meta:
        key = (str(record.get("table_name", "")), str(record.get("column_name", "")))
        values_count_by_column[key] = values_count_by_column.get(key, 0) + 1
    values_index_path = store_path / "values.faiss"
    vector_file_valid = _matches_checksum(
        values_index_path, manifest.get("values_index_sha256")
    )
    if vector_file_valid:
        try:
            vector_count = int(faiss.read_index(str(values_index_path)).ntotal)
            if vector_count == len(values_meta):
                vector_count_by_column.update(values_count_by_column)
        except (OSError, RuntimeError, ValueError):
            vector_file_valid = False

    lines = [
        f"Namespace: {namespace}",
        f"Model: {manifest.get('embedding_model_name', 'unknown')}",
        f"Dimension: {manifest.get('vector_dimension', 'unknown')}",
        f"Build time: {manifest.get('build_time', 'unknown')}",
        "Table scan times:",
    ]
    for table_name, scanned_at in sorted(manifest.get("last_value_scan_at", {}).items()):
        lines.append(f"  {table_name}: {scanned_at}")
    lines.append("Indexed columns:")
    all_tables = set(classifications)
    all_tables.update(table for table, _ in values_count_by_column)
    for table_name in sorted(all_tables):
        columns = classifications.get(table_name, {}).get("columns", {})
        column_names = set(columns)
        column_names.update(
            column
            for table, column in values_count_by_column
            if table == table_name
        )
        for column_name in sorted(column_names):
            key = (table_name, column_name)
            column_class = columns.get(column_name, {}).get("class", "unknown")
            vector_count = vector_count_by_column.get(key, 0)
            lines.append(
                f"  {table_name}.{column_name} | {column_class} | "
                f"stored values: {values_count_by_column.get(key, 0)} | vectors: {vector_count}"
            )
    if not vector_file_valid and values_meta:
        lines.append("Vector status: invalid or unavailable")
    lines.extend(["", "STALE OVERRIDES"])
    if stale_overrides:
        lines.extend(f"  {name}" for name in stale_overrides)
    else:
        lines.append("  none")
    for warning in override_warnings or []:
        lines.append(f"Override warning: {warning}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Override VECTOR_STORE_PATH")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    adapter = DatabaseAdapter("sqlite:///:memory:", settings.query_timeout_seconds)
    # Read namespace from stored metadata; introspect_catalog requires a live DB,
    # so we derive the report from stored vector-store files only.
    overrides_path = Path(settings.vector_store_path) / adapter.namespace() / "overrides.yaml"
    _, stale_overrides, override_warnings = load_database_overrides(
        overrides_path, None
    )
    print(format_store_report(
        args.root or settings.vector_store_path,
        adapter.namespace(),
        stale_overrides,
        override_warnings,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())