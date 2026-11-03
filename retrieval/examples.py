"""Database-namespaced store for verified question and SQL examples."""

from __future__ import annotations

from typing import Any

from db.adapter import DatabaseAdapter
from retrieval.local_store import LocalVectorStore
from rapidfuzz import fuzz


class ExampleStore:
    """Persist verified examples in the namespace's local SQLite database."""

    def __init__(
        self,
        path: str | None,
        adapter: DatabaseAdapter,
        local_store: LocalVectorStore | None = None,
        candidate_limit: int = 500,
    ) -> None:
        self.local_store = local_store
        self.candidate_limit = max(1, candidate_limit)

    def save(self, question: str, sql: str) -> bool:
        """Save or replace a verified question/SQL pair.

        Returns True when the example was persisted successfully, False otherwise.
        Callers must check the return value and not claim success when False (0e fix).
        """
        return self.local_store.save_example(question, sql) if self.local_store else False

    def retrieve(self, question: str, top_k: int = 3) -> list[dict[str, Any]]:
        """Return the most lexically similar verified examples."""
        if self.local_store is None:
            return []
        ranked = sorted(
            self.local_store.get_examples(limit=self.candidate_limit),
            key=lambda pair: fuzz.token_set_ratio(question, pair.get("question", "")),
            reverse=True,
        )
        return ranked[:top_k]