"""Tenant- and dataset-scoped Qdrant storage for NLS embedding documents."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence

from qdrant_client import QdrantClient, models

LOGGER = logging.getLogger(__name__)

VECTOR_SIZE = 384
VECTOR_DISTANCE = models.Distance.COSINE
DEFAULT_COLLECTION = "nls_documents"
POINT_NAMESPACE = uuid.UUID("c43a95e6-39d5-4a21-9f2d-c01ebef6952f")


class QdrantStorageError(RuntimeError):
    """Safe user-facing Qdrant error that never includes connection details."""


class QdrantMetadataMismatchError(QdrantStorageError):
    """Dataset embedding metadata does not match the active query model."""


_DATASET_SEARCH_ERROR = (
    "Dataset index is unavailable or incompatible; search was refused."
)


def make_dataset_hash(
    file_bytes: bytes,
    dialect_override: str | None,
    embedding_model_name: str,
) -> str:
    """Hash the upload together with interpretation and embedding configuration."""
    digest = hashlib.sha256()
    digest.update(file_bytes)
    digest.update(b"\0")
    digest.update((dialect_override or "auto").casefold().encode("utf-8"))
    digest.update(b"\0")
    digest.update(embedding_model_name.encode("utf-8"))
    return digest.hexdigest()


def deterministic_point_id(
    tenant_id: str,
    dataset_id: str,
    document_type: str,
    table_name: str,
    column_name: str | None,
    value: str | None = None,
) -> str:
    """Create a stable point ID from the dataset/document identity."""
    identity = json.dumps(
        [tenant_id, dataset_id, document_type, table_name, column_name, value],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return str(uuid.uuid5(POINT_NAMESPACE, identity))


def _validate_scope(tenant_id: str, dataset_id: str) -> None:
    if not tenant_id.strip() or not dataset_id.strip():
        raise ValueError("Both tenant_id and dataset_id are required for Qdrant operations.")


def _dataset_filter(tenant_id: str, dataset_id: str) -> models.Filter:
    _validate_scope(tenant_id, dataset_id)
    return models.Filter(must=_scope_conditions(tenant_id, dataset_id))


def _scope_conditions(tenant_id: str, dataset_id: str) -> list[models.FieldCondition]:
    return [
        models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
        models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset_id)),
    ]


def _read_search_metadata(
    dataset_metadata_path: str | Path,
    tenant_id: str,
    dataset_id: str,
    embedding_model_name: str,
    dimension: int,
) -> dict[str, Any]:
    try:
        metadata = json.loads(Path(dataset_metadata_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Dataset search refused: index metadata is missing or unreadable.")
        raise QdrantStorageError(_DATASET_SEARCH_ERROR) from None
    if metadata.get("tenant_id") != tenant_id or metadata.get("dataset_id") != dataset_id:
        LOGGER.warning("Dataset search refused: index scope is invalid.")
        raise QdrantStorageError(_DATASET_SEARCH_ERROR)
    if metadata.get("indexed") is not True:
        LOGGER.warning("Dataset search refused: index is not marked indexed.")
        raise QdrantStorageError(_DATASET_SEARCH_ERROR)
    if metadata.get("embedding_model_name") != embedding_model_name:
        LOGGER.warning("Dataset search refused: embedding model metadata is incompatible.")
        raise QdrantMetadataMismatchError(_DATASET_SEARCH_ERROR)
    if metadata.get("vector_dimension") != dimension:
        LOGGER.warning("Dataset search refused: embedding dimension metadata is incompatible.")
        raise QdrantMetadataMismatchError(_DATASET_SEARCH_ERROR)
    return metadata


class QdrantVectorStore:
    """One fixed-dimension collection with mandatory tenant/dataset filters."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:6333",
        api_key: str | None = None,
        collection_name: str = DEFAULT_COLLECTION,
        client: QdrantClient | None = None,
        vector_size: int = VECTOR_SIZE,
    ) -> None:
        if vector_size != VECTOR_SIZE:
            raise QdrantStorageError(
                f"The NLS Qdrant collection requires {VECTOR_SIZE}-dimension vectors."
            )
        self.collection_name = collection_name
        self.vector_size = vector_size
        try:
            self.client = client or QdrantClient(
                url=url,
                api_key=api_key or None,
                timeout=5,
            )
            self._ensure_collection()
        except QdrantStorageError:
            raise
        except Exception:
            raise QdrantStorageError(
                "Could not connect to or configure Qdrant; check its availability and settings."
            ) from None

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=VECTOR_DISTANCE,
                ),
            )
        else:
            info = self.client.get_collection(self.collection_name)
            vectors = info.config.params.vectors
            if not isinstance(vectors, models.VectorParams):
                raise QdrantStorageError("The Qdrant collection must use one unnamed dense vector.")
            if vectors.size != self.vector_size or vectors.distance != VECTOR_DISTANCE:
                raise QdrantStorageError(
                    "The existing Qdrant collection has an incompatible vector size or distance."
                )
        for field_name in ("tenant_id", "dataset_id"):
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )

    @staticmethod
    def _prepare_points(
        tenant_id: str,
        dataset_id: str,
        documents: Sequence[dict[str, Any]],
        vectors: Sequence[Sequence[float]],
    ) -> list[models.PointStruct]:
        if len(documents) != len(vectors):
            raise ValueError("Each Qdrant document must have exactly one embedding.")
        points: list[models.PointStruct] = []
        for document, vector in zip(documents, vectors, strict=True):
            if len(vector) != VECTOR_SIZE:
                raise QdrantStorageError(
                    f"Embedding dimension mismatch: expected {VECTOR_SIZE}, received {len(vector)}."
                )
            document_type = str(document.get("document_type") or document.get("metadata_type") or "")
            table_name = str(document.get("table_name") or "")
            column_name = document.get("column_name")
            value = document.get("value") if document_type == "master_value" else None
            if not document_type or not table_name:
                raise ValueError("Qdrant documents require document_type and table_name.")
            payload = {
                **document,
                "tenant_id": tenant_id,
                "dataset_id": dataset_id,
                "table_name": table_name,
                "column_name": column_name,
                "document_type": document_type,
            }
            points.append(models.PointStruct(
                id=deterministic_point_id(
                    tenant_id,
                    dataset_id,
                    document_type,
                    table_name,
                    column_name,
                    str(value) if value is not None else None,
                ),
                vector=[float(item) for item in vector],
                payload=payload,
            ))
        return points

    @staticmethod
    def _write_index_metadata(
        dataset_metadata_path: str | Path,
        dataset_hash: str,
        embedding_model_name: str,
        dimension: int,
    ) -> None:
        path = Path(dataset_metadata_path)
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata.update({
            "dataset_hash": dataset_hash,
            "embedding_model_name": embedding_model_name,
            "vector_dimension": dimension,
            "indexed": True,
        })
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
                json.dump(metadata, file_obj, ensure_ascii=False, sort_keys=True, indent=2)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def reindex_dataset(
        self,
        tenant_id: str,
        dataset_id: str,
        documents: Sequence[dict[str, Any]],
        vectors: Sequence[Sequence[float]],
        dataset_metadata_path: str | Path,
        dataset_hash: str,
        embedding_model_name: str,
        dimension: int,
    ) -> list[str]:
        """Upsert desired points, prune stale scoped points, then mark the dataset indexed."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size:
            raise QdrantStorageError(
                f"Embedding model dimension must be {self.vector_size}; received {dimension}."
            )
        metadata_path = Path(dataset_metadata_path)
        try:
            dataset_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise QdrantStorageError("Dataset metadata is unavailable; indexing was not started.") from None
        if (
            dataset_metadata.get("tenant_id") != tenant_id
            or dataset_metadata.get("dataset_id") != dataset_id
        ):
            raise QdrantStorageError("Dataset metadata scope does not match the indexing request.")
        points = self._prepare_points(tenant_id, dataset_id, documents, vectors)
        point_ids = [str(point.id) for point in points]
        try:
            if points:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            stale_filter = models.Filter(
                must=_scope_conditions(tenant_id, dataset_id),
                must_not=([models.HasIdCondition(has_id=point_ids)] if point_ids else []),
            )
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=stale_filter,
                wait=True,
            )
        except Exception:
            raise QdrantStorageError(
                "Qdrant indexing did not complete; the dataset remains unindexed."
            ) from None

        try:
            self._write_index_metadata(
                metadata_path,
                dataset_hash,
                embedding_model_name,
                dimension,
            )
        except (OSError, ValueError, TypeError):
            raise QdrantStorageError(
                "Qdrant points were updated, but dataset metadata could not be committed."
            ) from None
        return point_ids

    def search(
        self,
        query_vector: Sequence[float],
        tenant_id: str,
        dataset_id: str,
        limit: int,
        dataset_metadata_path: str | Path,
        embedding_model_name: str,
        dimension: int,
        document_types: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search with mandatory tenant and dataset isolation filters."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size or len(query_vector) != self.vector_size:
            raise QdrantStorageError(f"Query embeddings must have {self.vector_size} dimensions.")
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )
        conditions = _scope_conditions(tenant_id, dataset_id)
        if document_types:
            conditions.append(
                models.FieldCondition(
                    key="document_type",
                    match=models.MatchAny(any=list(document_types)),
                )
            )
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=[float(item) for item in query_vector],
                query_filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            raise QdrantStorageError("Qdrant search failed; verify Qdrant availability.") from None
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def search_table(
        self,
        query_vector: Sequence[float],
        tenant_id: str,
        dataset_id: str,
        top_k: int,
        dataset_metadata_path: str | Path,
        embedding_model_name: str,
        dimension: int,
    ) -> list[dict[str, Any]]:
        """Search for table documents with tenant/dataset isolation."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size or len(query_vector) != self.vector_size:
            raise QdrantStorageError(f"Query embeddings must have {self.vector_size} dimensions.")
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value="table")))
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=[float(item) for item in query_vector],
                query_filter=query_filter,
                limit=max(1, int(top_k)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            raise QdrantStorageError("Qdrant search failed; verify Qdrant availability.") from None
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def search_column(
        self,
        query_vector: Sequence[float],
        tenant_id: str,
        dataset_id: str,
        top_k: int,
        dataset_metadata_path: str | Path,
        embedding_model_name: str,
        dimension: int,
    ) -> list[dict[str, Any]]:
        """Search for column documents with tenant/dataset isolation (limit: top_k * 3)."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size or len(query_vector) != self.vector_size:
            raise QdrantStorageError(f"Query embeddings must have {self.vector_size} dimensions.")
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value="column")))
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=[float(item) for item in query_vector],
                query_filter=query_filter,
                limit=max(1, int(top_k * 3)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            raise QdrantStorageError("Qdrant search failed; verify Qdrant availability.") from None
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def search_relationship(
        self,
        query_vector: Sequence[float],
        tenant_id: str,
        dataset_id: str,
        top_k: int,
        dataset_metadata_path: str | Path,
        embedding_model_name: str,
        dimension: int,
    ) -> list[dict[str, Any]]:
        """Search for relationship documents with tenant/dataset isolation (limit: top_k * 2)."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size or len(query_vector) != self.vector_size:
            raise QdrantStorageError(f"Query embeddings must have {self.vector_size} dimensions.")
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value="relationship")))
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=[float(item) for item in query_vector],
                query_filter=query_filter,
                limit=max(1, int(top_k * 2)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            raise QdrantStorageError("Qdrant search failed; verify Qdrant availability.") from None
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def search_master_value(
        self,
        query_vector: Sequence[float],
        tenant_id: str,
        dataset_id: str,
        top_k: int,
        dataset_metadata_path: str | Path,
        embedding_model_name: str,
        dimension: int,
    ) -> list[dict[str, Any]]:
        """Search for master_value documents with tenant/dataset isolation (limit: min(50, top_k * 2))."""
        _validate_scope(tenant_id, dataset_id)
        if dimension != self.vector_size or len(query_vector) != self.vector_size:
            raise QdrantStorageError(f"Query embeddings must have {self.vector_size} dimensions.")
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value="master_value")))
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=[float(item) for item in query_vector],
                query_filter=query_filter,
                limit=max(1, min(50, int(top_k * 2))),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            raise QdrantStorageError("Qdrant search failed; verify Qdrant availability.") from None
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]