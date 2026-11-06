"""Hybrid schema retrieval with Qdrant vectors, lexical ranking, and FK expansion."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Protocol

import numpy as np

from config.data_policy import is_blocked, is_masked
from config.settings import Settings
from retrieval.embeddings import EmbeddingModel
from retrieval.qdrant_store import QdrantVectorStore
from schema.metadata import SchemaMetadata, is_internal_table_name

DEFAULT_TOP_K = 8
MAX_TOP_K = 20


class Embedder(Protocol):
    """Minimal interface implemented by the local embedding model."""

    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _lexical_tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9_]+", value.casefold())


class HybridSchemaRetriever:
    """Rank schema documents using Qdrant vectors and lexical relevance."""

    def __init__(
        self, 
        metadata: SchemaMetadata, 
        embedding_model: Embedder, 
        local_store: QdrantVectorStore | None = None,
        policy_overrides: dict[str, Any] | None = None,
    ):
        self.metadata = metadata
        self.embedding_model = embedding_model
        self.local_store = local_store
        self.policy_overrides = policy_overrides
        self.call_counts = {"embedding_calls": 0, "vector_searches": 0}
        self.documents = []
        for table in metadata.tables.values():
            if is_internal_table_name(table.name):
                continue
            column_text = [
                f"{column.name} {column.data_type} {column.comment or ''}".strip()
                for column in table.columns
                if not is_blocked(f"{table.name}.{column.name}", policy_overrides=policy_overrides)
                and not is_masked(f"{table.name}.{column.name}", policy_overrides=policy_overrides)
            ]
            self.documents.append({
                "table_name": table.name,
                "text": " ".join([table.name, table.description or f"Table {table.name}", *column_text]),
                "relationships": table.foreign_keys,
            })

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Return semantically and lexically ranked tables plus FK neighbors."""
        if not self.documents:
            return {"documents": [], "tables": [], "ddl": "", "scores": {}}
        
        query_tokens = _lexical_tokens(query)
        query_vector = self.embedding_model.embed([query])[0]
        self.call_counts["embedding_calls"] += 1
        
        # Search local vectors and associate results by schema-qualified table key.
        semantic_results = []
        if self.local_store is not None:
            semantic_results = self.local_store.search_schema(
                query_vector.tolist(),
                top_k=max(top_k, MAX_TOP_K),
                metadata_type="table_ddl",
                tenant_id=self.local_store.tenant_id,
                dataset_id=self.local_store.dataset_id,
                dataset_metadata_path=self.local_store.dataset_metadata_path,
                embedding_model_name=self.local_store.model_name,
                dimension=self.local_store.vector_size,
            )
            self.call_counts["vector_searches"] += 1
        
        # Build a lookup of semantic scores from the search results, keyed by
        # the schema-qualified table name returned by the store.  The store key
        # matches the fully-qualified name (schema.table or bare table) that was
        # used when the embedding was built.  We must NOT fall back to positional
        # indexing because semantic results are similarity-ranked, so position
        # does not correspond to document position (0c fix).
        semantic_scores: dict[str, float] = {}
        for result in semantic_results:
            table_name = result.get("table_name", "")
            if table_name:
                semantic_scores[table_name] = result.get("similarity", 0.0)
        
        ranked = []
        for index, document in enumerate(self.documents):
            # Lexical scoring
            tokens = Counter(_lexical_tokens(document["text"]))
            lexical = sum(
                min(tokens[token], query_tokens.count(token)) for token in set(query_tokens)
            ) / max(1, len(set(query_tokens)))
            
            # Semantic scoring: match by schema-qualified key first, then by
            # bare table name.  Never fall back to positional indexing because
            # semantic_results are similarity-ranked (0c fix).
            table_name = document["table_name"]
            bare_name = table_name.rsplit(".", 1)[-1]
            if table_name in semantic_scores:
                semantic = semantic_scores[table_name]
            elif bare_name in semantic_scores:
                semantic = semantic_scores[bare_name]
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

    def _document_for(self, table: Any) -> dict[str, Any]:
        unblocked_columns = [
            column.name
            for column in table.columns
            if not is_blocked(f"{table.name}.{column.name}", policy_overrides=self.policy_overrides)
            and not is_masked(f"{table.name}.{column.name}", policy_overrides=self.policy_overrides)
        ]
        return {
            "table_name": table.name,
            "text": " ".join([table.name, table.description or f"Table {table.name}", *unblocked_columns]),
            "relationships": table.foreign_keys,
        }

    def compact_ddl(self, table_names: list[str]) -> str:
        """Render exact names and types for only the selected tables, omitting BLOCKED columns."""
        definitions = []
        for table_name in table_names:
            table = self.metadata.tables.get(table_name)
            if table is None or is_internal_table_name(table_name):
                continue
            columns = []
            for column in table.columns:
                # Omit BLOCKED columns completely from DDL
                if is_blocked(
                    f"{table.name}.{column.name}", policy_overrides=self.policy_overrides
                ):
                    continue
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

    # If indexer is provided, use its embedding store
    if indexer is not None:
        initial = indexer.search_similar(query, top_k=top_k)
        initial_tables = [document["table_name"] for document in initial]
        retriever = HybridSchemaRetriever(metadata, indexer.embedding_model, local_store=indexer.local_store)
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