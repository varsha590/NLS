"""Shared schema document text builders used for embedding generation and retrieval.

This module intentionally formats schema documents using names, types, keys,
and comments only (no row sample values). BLOCKED columns are omitted entirely
so sensitive names never enter embeddings or retrieval context.
"""

from __future__ import annotations

from typing import Any

from config.data_policy import is_blocked


def build_table_document(table: Any) -> str:
    """Return the retrievable text for one table, excluding BLOCKED columns and sample values."""
    column_text = [
        f"{column.name} {column.data_type} {column.comment or ''}".strip()
        for column in table.columns
        if not is_blocked(f"{table.name}.{column.name}")
    ]
    parts = [table.name, table.description or f"Table {table.name}"]
    if column_text:
        parts.extend(column_text)
    return " ".join(parts).strip()


def build_column_document(table: Any, column: Any) -> str:
    """Return the retrievable text for one column, excluding sample values."""
    if is_blocked(f"{table.name}.{column.name}"):
        return ""
    parts = [table.name, column.name, column.data_type, column.comment or ""]
    return " ".join(part for part in parts if part).strip()


def build_relationship_document(table: Any, relation: dict[str, Any]) -> str:
    """Return the retrievable text for one foreign-key relationship."""
    local = relation.get("column") or relation.get("local_column") or ""
    remote_table = relation.get("remote_table") or ""
    remote_column = relation.get("remote_column") or ""
    return " ".join(
        [table.name, local, "references", remote_table, remote_column]
    ).strip()
