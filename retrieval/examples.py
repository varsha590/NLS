"""Database-namespaced store for verified question and SQL examples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from db.adapter import DatabaseAdapter


class ExampleStore:
    """Persist and retrieve verified examples in a local per-database file."""

    def __init__(self, path: str | Path, adapter: DatabaseAdapter) -> None:
        self.path = Path(path) / adapter.namespace() / "examples.json"

    def _load(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, question: str, sql: str) -> None:
        """Save or replace a verified question/SQL pair."""
        pairs = [pair for pair in self._load() if pair.get("question", "").casefold() != question.casefold()]
        pairs.append({"question": question.strip(), "sql": sql.strip()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(pairs, ensure_ascii=True, indent=2), encoding="utf-8")

    def retrieve(self, question: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Return the most lexically similar verified examples."""
        ranked = sorted(
            self._load(),
            key=lambda pair: fuzz.token_set_ratio(question, pair.get("question", "")),
            reverse=True,
        )
        return ranked[:top_k]