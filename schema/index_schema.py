"""Database-independent local schema document and embedding helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import sqlalchemy as sa

from config.settings import Settings
from db.adapter import DatabaseAdapter
from retrieval.embeddings import EmbeddingModel
from schema.metadata import EXCLUDED_SCHEMA_OBJECTS, SchemaMetadata

try:
    from config.data_policy import is_blocked
except Exception:
    def is_blocked(key: str) -> bool:
        return False

def format_table_document(table: Any) -> str:
    """Format a normalized table with exact identifiers for retrieval."""
    columns = []
    for column in table.columns:
        if is_blocked(f"{table.name}.{column.name}"):
            continue
        details = f"- {column.name}: {column.data_type}"
        if column.is_primary_key:
            details += " (primary key)"
        if column.is_foreign_key and column.foreign_table and column.foreign_column:
            details += f" (foreign key to {column.foreign_table}.{column.foreign_column})"
        if column.comment:
            details += f"; {column.comment}"
        columns.append(details)
    return "\n".join([f"Table: {table.name}", f"Description: {table.description}", *columns])


def format_schema_documents(metadata: SchemaMetadata) -> list[dict[str, Any]]:
    """Return normalized retrievable documents without database-specific content."""
    documents = []
    for name, table in metadata.tables.items():
        if name in EXCLUDED_SCHEMA_OBJECTS:
            continue
        documents.append({
            "id": f"table:{name}",
            "table_name": name,
            "description": table.description,
            "relationships": table.foreign_keys,
            "business_relevance": "",
            "doc_text": format_table_document(table),
        })
    return documents


def cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    """Compute cosine similarity for two vectors."""
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    return float(np.dot(first, second) / denominator) if denominator else 0.0


def cosine_similarity_batch(embeddings: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between each stored vector and one query."""
    norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(query)
    return np.divide(
        embeddings @ query,
        norms,
        out=np.zeros(len(embeddings), dtype=float),
        where=norms != 0,
    )


def compute_doc_hash(documents: list[dict[str, Any]]) -> str:
    """Create a deterministic hash of normalized schema documents."""
    digest = hashlib.sha256()
    for document in documents:
        digest.update(json.dumps(document, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


class SchemaIndexer:
    """Compatibility indexer storing documents and embeddings locally."""

    def __init__(self, engine: sa.Engine, embedding_model=None, top_k: int = 8):
        self.engine = engine
        self.embedding_model = embedding_model or EmbeddingModel(Settings.from_env().embedding_model)
        self.top_k = top_k
        self.adapter = DatabaseAdapter(engine.url, engine=engine)
        self.documents: list[dict[str, Any]] = []
        self.embeddings = np.empty((0, 0))

    def remove_excluded_documents(self) -> None:
        """No database cleanup is needed for local catalog storage."""

    def index_schema(self, refresh: bool = False) -> dict[str, Any]:
        """Build and save a local schema embedding index."""
        from catalog.introspect import introspect_catalog
        from catalog.store import CatalogStore

        metadata = introspect_catalog(self.engine)
        self.documents = format_schema_documents(metadata)
        self.embeddings = self.embedding_model.embed(
            [document["doc_text"] for document in self.documents]
        ) if self.documents else np.empty((0, self.embedding_model.dim))
        store = CatalogStore(Settings.from_env().vector_store_path, self.adapter)
        store.save({
            "schema_hash": compute_doc_hash(self.documents),
            "embedding_model": self.embedding_model.model_name,
            "catalog": metadata.to_dict(),
            "documents": self.documents,
            "schema_embeddings": self.embeddings.tolist(),
        })
        return {"status": "indexed", "documents_indexed": len(self.documents)}

    def search_similar(self, query_text: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """Rank local schema documents by cosine similarity."""
        from catalog.store import CatalogStore

        if not self.documents:
            cached = CatalogStore(Settings.from_env().vector_store_path, self.adapter).load() or {}
            self.documents = cached.get("documents", [])
            self.embeddings = np.asarray(cached.get("schema_embeddings", []), dtype=float)
        if not self.documents:
            return []
        query = self.embedding_model.embed([query_text])[0]
        scores = cosine_similarity_batch(self.embeddings, query)
        order = np.argsort(scores)[::-1][:top_k or self.top_k]
        return [dict(self.documents[index], similarity_score=float(scores[index])) for index in order]

    def expand_relationships(self, retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Include known foreign-key neighbors of retrieved tables."""
        expanded = list(retrieved_docs)
        included = {document.get("table_name") for document in expanded}
        metadata = SchemaMetadata.from_engine(self.engine)
        for document in list(expanded):
            table = metadata.tables.get(document.get("table_name", ""))
            if table is None:
                continue
            for relation in table.foreign_keys:
                related = relation.get("remote_table")
                if related and related not in included and related in metadata.tables:
                    related_table = metadata.tables[related]
                    expanded.append({
                        "id": f"table:{related}",
                        "table_name": related,
                        "description": related_table.description,
                        "relationships": related_table.foreign_keys,
                        "business_relevance": "",
                    })
                    included.add(related)
        return expanded


def run_indexing(
    engine: sa.Engine,
    embedding_model_name: str | None = None,
    top_k: int = 8,
    refresh: bool = False,
    embedding_model=None,
) -> dict[str, Any]:
    """Compatibility helper for manually refreshing the local schema index."""
    configured_model = embedding_model_name or Settings.from_env().embedding_model
    indexer = SchemaIndexer(engine, embedding_model or EmbeddingModel(configured_model), top_k)
    return indexer.index_schema(refresh=refresh)
