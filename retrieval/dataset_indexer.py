"""Build and index separate schema/value documents for registered datasets."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from config.data_policy import is_blocked, is_masked
from ingestion.datasets import DatasetRegistry
from retrieval.qdrant_store import QdrantStorageError, QdrantVectorStore, make_dataset_hash
from schema.documents import build_column_document, build_table_document
from schema.metadata import SchemaMetadata


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def build_embedding_documents(
    schema: SchemaMetadata,
    value_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create table, column, relationship, and low-cardinality value documents."""
    documents: list[dict[str, Any]] = []
    for table in schema.tables.values():
        documents.append({
            "document_type": "table",
            "table_name": table.name,
            "column_name": None,
            "content": build_table_document(table),
        })
        for column in table.columns:
            content = build_column_document(table, column)
            if content:
                documents.append({
                    "document_type": "column",
                    "table_name": table.name,
                    "column_name": column.name,
                    "content": content,
                })
        for index, relationship in enumerate(table.foreign_keys):
            local_columns = relationship.get("local_cols") or []
            remote_columns = relationship.get("remote_cols") or []
            remote_table = str(relationship.get("remote_table") or "")
            if not local_columns or not remote_columns:
                continue
            local_name = ", ".join(str(name) for name in local_columns)
            remote_name = ", ".join(str(name) for name in remote_columns)
            protected = any(
                is_blocked(f"{table.name}.{name}") or is_masked(f"{table.name}.{name}")
                for name in local_columns
            ) or any(
                is_blocked(f"{remote_table}.{name}") or is_masked(f"{remote_table}.{name}")
                for name in remote_columns
            )
            if protected:
                continue
            documents.append({
                "document_type": "relationship",
                "table_name": table.name,
                "column_name": f"relationship_{index}",
                "content": f"{table.name} {local_name} references {remote_table} {remote_name}",
            })

    for value_document in value_documents:
        documents.append({
            "document_type": "master_value",
            "table_name": str(value_document["table_name"]),
            "column_name": str(value_document["column_name"]),
            "value": str(value_document["value"]),
            "content": str(value_document["content"]),
        })
    return [document for document in documents if document["content"]]


def index_registered_dataset(
    registry: DatasetRegistry,
    store: QdrantVectorStore,
    tenant_id: str,
    dataset_id: str,
    dataset_hash: str,
    embedding_model: Embedder,
) -> int:
    """Embed and re-index one dataset, committing indexed metadata only on success."""
    if embedding_model.dim != store.vector_size:
        raise QdrantStorageError(
            f"Embedding model dimension must be {store.vector_size}; received {embedding_model.dim}."
        )
    schema = registry.load_schema(tenant_id, dataset_id)
    value_documents = registry.load_value_documents(tenant_id, dataset_id)
    documents = build_embedding_documents(schema, value_documents)
    vectors = embedding_model.embed([document["content"] for document in documents])
    if vectors.ndim != 2 or vectors.shape != (len(documents), store.vector_size):
        found_dimension = vectors.shape[-1] if vectors.ndim else 0
        raise QdrantStorageError(
            f"Embedding model output must have {store.vector_size} dimensions; received {found_dimension}."
        )
    dataset_dir = registry.dataset_directory(tenant_id, dataset_id)
    store.reindex_dataset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        documents=documents,
        vectors=vectors.tolist(),
        dataset_metadata_path=dataset_dir / "dataset.json",
        dataset_hash=dataset_hash,
        embedding_model_name=embedding_model.model_name,
        dimension=embedding_model.dim,
    )
    return len(documents)


def expected_dataset_hash(file_bytes: bytes, dialect_override: str | None, model_name: str) -> str:
    """Public hash helper used by registration UI and tests."""
    return make_dataset_hash(file_bytes, dialect_override, model_name)