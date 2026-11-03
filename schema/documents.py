"""Shared schema document text builders used for embedding generation and retrieval.

This module intentionally has no database imports so that both the storage layer
and the retrieval layer can use it without circular dependencies.
"""

from __future__ import annotations

from typing import Any


def build_table_document(table: Any) -> str:
    """Return the retrievable text for one table."""
    column_text = [
        f"{column.name} {column.data_type} {column.comment or ''} "
        f"{' '.join(column.sample_values)}"
        for column in table.columns
    ]
    return " ".join([table.name, table.description, *column_text])


def build_column_document(table: Any, column: Any) -> str:
    """Return the retrievable text for one column."""
    return " ".join(
        [
            table.name,
            column.name,
            column.data_type,
            column.comment or "",
            " ".join(column.sample_values),
        ]
    ).strip()


def build_relationship_document(table: Any, relation: dict[str, Any]) -> str:
    """Return the retrievable text for one foreign-key relationship."""
    local = relation.get("column") or relation.get("local_column") or ""
    remote_table = relation.get("remote_table") or ""
    remote_column = relation.get("remote_column") or ""
    return " ".join(
        [table.name, local, "references", remote_table, remote_column]
    ).strip()