"""Legacy optional catalog loader retained for the developer description utility."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db.adapter import DatabaseAdapter


class CatalogStore:
    """Read legacy catalog JSON; save and description-progress methods are no-ops."""

    def __init__(self, path: str | Path, adapter: DatabaseAdapter) -> None:
        self.path = Path(path) / adapter.namespace() / "catalog.json"

    def load(self) -> dict[str, Any] | None:
        """Load a legacy catalog file if one exists."""
        try:
            if not self.path.exists():
                return None
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def is_current(self, schema_hash: str, embedding_model: str) -> bool:
        """Return False because this legacy file has no validity manifest."""
        return False

    def save(self, payload: dict[str, Any]) -> None:
        """Retained compatibility method; the application no longer saves catalogs here."""

    @property
    def description_progress_path(self) -> Path:
        """Return the former description-progress file location."""
        return self.path.with_name("description-progress.json")

    def load_description_progress(self) -> set[str]:
        """Return no progress because this legacy utility does not persist it."""
        return set()

    def save_description_progress(self, completed: set[str]) -> None:
        """Retained compatibility method; no progress is written."""