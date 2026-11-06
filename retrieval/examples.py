"""Database-namespaced store for verified question and SQL examples."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from db.adapter import DatabaseAdapter
from rapidfuzz import fuzz


class ExampleStore:
    """Persist verified examples in the namespace's local SQLite database."""

    def __init__(
        self,
        path: str | None,
        adapter: DatabaseAdapter,
        local_store: Any = None,
        candidate_limit: int = 500,
    ) -> None:
        del local_store  # examples are kept in their own SQLite table now
        self.path = Path(path) / adapter.namespace() / "examples.sqlite" if path else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.candidate_limit = max(1, candidate_limit)

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS examples ("
            "id INTEGER PRIMARY KEY, question TEXT NOT NULL UNIQUE, "
            "sql TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        return connection

    def save(self, question: str, sql: str) -> bool:
        """Save or replace a verified question/SQL pair.

        Returns True when the example was persisted successfully, False otherwise.
        Callers must check the return value and not claim success when False (0e fix).
        """
        if self.path is None:
            return False
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO examples(question, sql, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(question) DO UPDATE SET sql = excluded.sql, updated_at = excluded.updated_at",
                    (question, sql, time.time()),
                )
            return True
        except sqlite3.DatabaseError:
            return False

    def retrieve(self, question: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Return the most lexically similar verified examples."""
        if self.path is None or not self.path.exists():
            return []
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT question, sql FROM examples ORDER BY updated_at DESC, id DESC LIMIT ?",
                    (self.candidate_limit,),
                ).fetchall()
        except sqlite3.DatabaseError:
            return []
        ranked = sorted(
            [{"question": question_text, "sql": sql_text} for question_text, sql_text in rows],
            key=lambda pair: fuzz.token_set_ratio(question, pair.get("question", "")),
            reverse=True,
        )
        return ranked[:top_k]
