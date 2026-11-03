"""Hybrid schema retrieval with pgvector embeddings, lexical ranking, and FK expansion."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Protocol

import numpy as np

from db.adapter import EmbeddingStore
from config.settings import Settings
from schema.index_schema import cosine_similarity
from schema.metadata import SchemaMetadata

DEFAULT_TOP_K = 8
MAX_TOP_K = 20


class Embedder(Protocol):
    """Minimal interface implemented by the local embedding model."""

    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _lexical_tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+", value.casefold())


class HybridSchemaRetriever:
    """Rank schema documents using pgvector embeddings and lexical relevance."""

    def __init__(
        self, 
        metadata: SchemaMetadata, 
        embedding_model: Embedder, 
        embedding_store: EmbeddingStore | None = None
    ):
        self.metadata = metadata
        self.embedding_model = embedding_model
        self.embedding_store = embedding_store
        self.documents = []
        for table in metadata.tables.values():
            column_text = [
                f"{column.name} {column.data_type} {column.comment or ''} "
                f"{' '.join(column.sample_values)}"
                for column in table.columns
            ]
            self.documents.append({
                "table_name": table.name,
                "text": " ".join([table.name, table.description, *column_text]),
                "relationships": table.foreign_keys,
            })
        # Embeddings are now fetched from EmbeddingStore as needed

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Return semantically and lexically ranked tables plus FK neighbors."""
        if not self.documents:
            return {"documents": [], "tables": [], "ddl": "", "scores": {}}
        
        query_tokens = _lexical_tokens(query)
        query_vector = self.embedding_model.embed([query])[0]
        
        # Use EmbeddingStore to find similar schema embeddings if available
        semantic_results = []
        if self.embedding_store is not None:
            semantic_results = self.embedding_store.search_schema(
                query_vector.tolist(), top_k=max(top_k, MAX_TOP_K), metadata_type="table_ddl"
            )
        
        # Build a lookup of semantic scores from the search results
        semantic_scores: dict[str, float] = {}
        for result in semantic_results:
            table_name = result.get("table_name", "")
            # Store per-table similarity
            semantic_scores[table_name] = result.get("similarity", 0.0)
        
        ranked = []
        for index, document in enumerate(self.documents):
            # Lexical scoring
            tokens = Counter(_lexical_tokens(document["text"]))
            lexical = sum(
                min(tokens[token], query_tokens.count(token)) for token in set(query_tokens)
            ) / max(1, len(set(query_tokens)))
            
            # Semantic scoring: use from EmbeddingStore if available, else fallback
            table_name = document["table_name"]
            if table_name in semantic_scores:
                semantic = semantic_scores[table_name]
            elif self.embedding_store is not None and len(semantic_results) > index:
                semantic = semantic_results[index].get("similarity", 0.0)
            else:
                semantic = 0.0
            
            combined = 0.65 * semantic + 0.35 * lexical
            ranked.append((combined, document))
        
        ranked.sort(key=lambda item: item[0], reverse=True)
        chosen = ranked[:max(1, min(top_k, MAX_TOP_K))]
        names = {document["table_name"] for _, document in chosen}
        expanded = list(chosen)
        for score, document in chosen:
            for relation in document["relationships"]:
                related_name = relation.get("remote_table")
                if related_name and related_name not in names and related_name in self.metadata.tables:
                    names.add(related_name)
                    table = self.metadata.tables[related_name]
                    expanded.append((score * 0.8, self._document_for(table)))
        table_names = [document["table_name"] for _, document in expanded]
        return {
            "documents": [dict(document, similarity_score=float(score)) for score, document in expanded],
            "tables": table_names,
            "ddl": self.compact_ddl(table_names),
            "scores": {document["table_name"]: float(score) for score, document in expanded},
        }

    @staticmethod
    def _document_for(table: Any) -> dict[str, Any]:
        return {
            "table_name": table.name,
            "text": " ".join([table.name, table.description, *(column.name for column in table.columns)]),
            "relationships": table.foreign_keys,
        }

    def compact_ddl(self, table_names: list[str]) -> str:
        """Render exact names and types for only the selected tables."""
        definitions = []
        for table_name in table_names:
            table = self.metadata.tables.get(table_name)
            if table is None:
                continue
            columns = []
            for column in table.columns:
                details = f"{column.name} {column.data_type}"
                if column.is_primary_key:
                    details += " PRIMARY KEY"
                if column.is_foreign_key and column.foreign_table and column.foreign_column:
                    details += f" REFERENCES {column.foreign_table}({column.foreign_column})"
                columns.append(details)
            definitions.append(f"TABLE {table.name} ({', '.join(columns)})")
        return "\n".join(definitions)


def retrieve_schema(engine, query: str, top_k: int = DEFAULT_TOP_K, indexer=None) -> dict[str, Any]:
    """Compatibility wrapper that retrieves from a live SQLAlchemy schema."""
    import time

    started = time.monotonic()
    metadata = SchemaMetadata.from_engine(engine)
    from db.adapter import EmbeddingStore
    
    # Get or create embedding store from engine connection
    adapter = None
    # Try to get adapter from somewhere - for compatibility, create a basic lookup
    # If indexer is provided, use its embedding store
    if indexer is not None:
        initial = indexer.search_similar(query, top_k=top_k)
        initial_tables = [document["table_name"] for document in initial]
        retriever = HybridSchemaRetriever(metadata, indexer.embedding_model, embedding_store=indexer.embedding_store)
        result = retriever.retrieve(query, top_k=top_k)
        if initial_tables:
            result["tables"] = list(dict.fromkeys(initial_tables + result["tables"]))
            result["ddl"] = retriever.compact_ddl(result["tables"])
    else:
        retriever = HybridSchemaRetriever(metadata, EmbeddingModel(Settings.from_env().embedding_model))
        result = retriever.retrieve(query, top_k=top_k)
    result["retrieval_time_ms"] = int((time.monotonic() - started) * 1000)
    result["top_k_used"] = top_k
    result["expanded"] = len(result["tables"])
    return result


def expand_with_required_relationships(retrieved: list[dict[str, Any]], engine) -> list[dict[str, Any]]:
    """Compatibility helper to append all directly related reflected tables."""
    metadata = SchemaMetadata.from_engine(engine)
    names = {document.get("table_name") for document in retrieved}
    result = list(retrieved)
    for document in list(result):
        table = metadata.tables.get(document.get("table_name", ""))
        if table is None:
            continue
        for relationship in table.foreign_keys:
            related = relationship.get("remote_table")
            if related and related not in names and related in metadata.tables:
                target = metadata.tables[related]
                result.append({
                    "table_name": related,
                    "description": target.description,
                    "relationships": target.foreign_keys,
                    "similarity_score": 0.0,
                })
                names.add(related)
    return result