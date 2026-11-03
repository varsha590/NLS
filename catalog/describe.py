"""Optional, resumable LLM descriptions for catalog objects."""

from __future__ import annotations

from typing import Callable

from catalog.store import CatalogStore
from schema.metadata import SchemaMetadata


def describe_catalog(
    metadata: SchemaMetadata,
    describe_text: Callable[[str], str],
    completed: set[str] | None = None,
    store: CatalogStore | None = None,
) -> set[str]:
    """Describe tables and columns once, skipping keys already completed."""
    completed_keys = set(completed or ())
    if store is not None:
        completed_keys.update(store.load_description_progress())
    for table in metadata.tables.values():
        table_key = f"table:{table.name}"
        if table_key not in completed_keys:
            table.description = describe_text(
                f"Write one concise plain-English description for a database table.\n{table.name}: {table.comment or ''}"
            )
            completed_keys.add(table_key)
            if store is not None:
                store.save_description_progress(completed_keys)
        for column in table.columns:
            column_key = f"column:{table.name}.{column.name}"
            if column_key not in completed_keys:
                column.comment = column.comment or describe_text(
                    f"Describe this database column briefly: {table.name}.{column.name} ({column.data_type})."
                )
                completed_keys.add(column_key)
                if store is not None:
                    store.save_description_progress(completed_keys)
    return completed_keys