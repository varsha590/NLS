"""Database-namespaced store for verified question and SQL examples."""

from __future__ import annotations

from typing import Any

from db.adapter import DatabaseAdapter, EmbeddingStore
from rapidfuzz import fuzz


class ExampleStore:
    """Persist and retrieve verified examples in PostgreSQL per database."""

    def __init__(self, path: str | None, adapter: DatabaseAdapter) -> None:
        self.embedding_store = EmbeddingStore(adapter)

    def save(self, question: str, sql: str) -> None:
        """Save or replace a verified question/SQL pair."""
        self.embedding_store.upsert_example(question, sql)

    def retrieve(self, question: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Return the most lexically similar verified examples."""
        ranked = sorted(
            self.embedding_store.get_examples(),
            key=lambda pair: fuzz.token_set_ratio(question, pair.get("question", "")),
            reverse=True,
        )
        return ranked[:top_k]