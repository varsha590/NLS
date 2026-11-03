"""Credential-free local persistence for schema catalogs and embeddings.

Note: Embedding data is now stored in PostgreSQL via EmbeddingStore.
This class is kept for backwards compatibility but does not persist to local disk.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from db.adapter import DatabaseAdapter


class CatalogStore:
    """Persist a database's catalog and vectors in its own local namespace.

    .. note::
        Embedding data is now stored in PostgreSQL via EmbeddingStore.
        This class no longer writes to local disk.
    """

    def __init__(self, path: str | Path, adapter: DatabaseAdapter) -> None:
        self.path = Path(path) / adapter.namespace() / "catalog.json"

    def load(self) -> dict[str, Any] | None:
        """Load a previously indexed catalog, if present and readable.

        .. note::
            Returns None as embedding data is now in PostgreSQL.
        """
        try:
            if not self.path.exists():
                return None
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def is_current(self, schema_hash: str, embedding_model: str) -> bool:
        """Check whether cached schema and embedding model match current settings.

        .. note::
            Always returns False as embedding data is now in PostgreSQL;
            check via EmbeddingStore instead.
        """
        return False

    def save(self, payload: dict[str, Any]) -> None:
        """Atomically write a catalog payload to local storage.

        .. note::
            No longer writes to local disk; embedding data is upserted
            into PostgreSQL by the caller.
        """
        # Embedding data is now stored in PostgreSQL via EmbeddingStore.upsert_schema()
        pass

    @property
    def description_progress_path(self) -> Path:
        """Return the resumable description-progress file path."""
        return self.path.with_name("description-progress.json")

    def load_description_progress(self) -> set[str]:
        """Load completed description keys for this database namespace.

        .. note::
            Returns empty set as description progress is no longer persisted to local disk.
        """
        return set()

    def save_description_progress(self, completed: set[str]) -> None:
        """Persist completed description keys after each LLM call.

        .. note::
            No longer persists to local disk.
        """
        pass