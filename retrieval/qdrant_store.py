"""Tenant- and dataset-scoped Qdrant storage for NLS embedding documents."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from qdrant_client import QdrantClient, models
from db.credentials import _scrub_credentials
from config.settings import Settings

LOGGER = logging.getLogger(__name__)

VECTOR_SIZE = 384
VECTOR_DISTANCE = models.Distance.COSINE
DEFAULT_COLLECTION = "nls_documents"
POINT_NAMESPACE = uuid.UUID("c43a95e6-39d5-4a21-9f2d-c01ebef6952f")

DEFAULT_TENANT_ID = "default"
DEFAULT_DATASET_ID = "default"


class QdrantStorageError(RuntimeError):
    """Safe user-facing Qdrant error that never includes connection details."""


class QdrantMetadataMismatchError(QdrantStorageError):
    """Dataset embedding metadata does not match the active query model."""


class QdrantIndexNotReadyError(QdrantStorageError):
    """Dataset index metadata is absent or not committed as indexed."""


_DATASET_SEARCH_ERROR = (
    "Dataset index is unavailable or incompatible; search was refused."
)


def _safe_qdrant_message(message: str) -> str:
    safe = _scrub_credentials(message)
    api_key = os.getenv("QDRANT_API_KEY", "")
    if api_key:
        safe = safe.replace(api_key, "***")
    safe = re.sub(r"(?i)\bcredentials\b", "[redacted]", safe)
    safe = re.sub(r"(?i)\bendpoint\b", "[redacted]", safe)
    safe = re.sub(
        r"(?i)(?:['\"]?api[-_]key['\"]?\s*[:=]\s*)(?:'[^']*'|\"[^\"]*\"|[^,}\]\s]+)",
        "[redacted header]",
        safe,
    )
    return re.sub(r"(?i)api[-_]key", "[redacted header]", safe)


def _operation_error(operation: str, error: BaseException) -> QdrantStorageError:
    detail = _safe_qdrant_message(str(error))
    error.args = (detail,)
    return QdrantStorageError(
        f"{operation} failed: {type(error).__name__}: {detail}"
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


def create_qdrant_client(settings: Settings | None = None) -> QdrantClient:
    """Create the shared Qdrant client from validated application settings."""
    settings = settings or Settings.from_env()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=5,
    )


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


def _flatten_query_vector(vector: Any) -> list[float]:
    """Accept a flat vector or a single-row 2D array and return a flat list."""
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    if isinstance(vector, (list, tuple)) and vector and isinstance(vector[0], (list, tuple)):
        vector = vector[0]
    return [float(item) for item in vector]


def _read_search_metadata(
    dataset_metadata_path: str | Path,
    tenant_id: str,
    dataset_id: str,
    embedding_model_name: str,
    dimension: int,
) -> dict[str, Any]:
    try:
        metadata = json.loads(Path(dataset_metadata_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Dataset search refused: index metadata is missing or unreadable.")
        raise QdrantIndexNotReadyError(_DATASET_SEARCH_ERROR) from exc
    if metadata.get("tenant_id") != tenant_id or metadata.get("dataset_id") != dataset_id:
        LOGGER.warning("Dataset search refused: index scope is invalid.")
        exc = ValueError(_DATASET_SEARCH_ERROR)
        raise QdrantStorageError(
            f"search metadata validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
        ) from exc
    if metadata.get("indexed") is not True:
        LOGGER.warning("Dataset search refused: index is not marked indexed.")
        raise QdrantIndexNotReadyError(_DATASET_SEARCH_ERROR)
    if metadata.get("embedding_model_name") != embedding_model_name:
        LOGGER.warning("Dataset search refused: embedding model metadata is incompatible.")
        exc = ValueError(_DATASET_SEARCH_ERROR)
        raise QdrantMetadataMismatchError(
            f"search metadata validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
        ) from exc
    if metadata.get("vector_dimension") != dimension:
        LOGGER.warning("Dataset search refused: embedding dimension metadata is incompatible.")
        exc = ValueError(_DATASET_SEARCH_ERROR)
        raise QdrantMetadataMismatchError(
            f"search metadata validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
        ) from exc
    return metadata


class QdrantVectorStore:
    """One fixed-dimension collection with mandatory tenant/dataset filters."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: QdrantClient | None = None,
        vector_size: int = VECTOR_SIZE,
        tenant_id: str = DEFAULT_TENANT_ID,
        dataset_id: str = DEFAULT_DATASET_ID,
        dataset_metadata_path: str | Path | None = None,
        manifest_path: str | Path | None = None,
    ) -> None:
        settings = settings or Settings.from_env()
        self.collection_name = settings.qdrant_collection
        self.vector_size = int(vector_size)
        self.tenant_id = tenant_id or DEFAULT_TENANT_ID
        self.dataset_id = dataset_id or DEFAULT_DATASET_ID
        self.dataset_metadata_path = (
            Path(dataset_metadata_path) if dataset_metadata_path is not None else None
        )
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        self.model_name = settings.embedding_model
        self.policy_hash = ""
        self.dimension = self.vector_size
        self.path: Path | None = None
        self.embedding_batches = 0
        self.embedded_vectors = 0
        self.embedding_seconds = 0.0
        self.save_seconds = 0.0
        self.failed_value_tables: set[str] = set()
        self._manifest: dict[str, Any] = {}
        self._manifest_valid = False
        self._manifest_loaded = False
        self._parts_compatible = False
        self._metadata_compatible = False
        self._part_valid = {"schema": False, "values": False}
        self._part_metadata_valid = {"schema": False, "values": False}
        try:
            self.client = client if client is not None else create_qdrant_client(settings)
            self._ensure_collection()
        except QdrantStorageError:
            raise
        except Exception as exc:
            detail = _safe_qdrant_message(str(exc))
            exc.args = (detail,)
            raise QdrantStorageError(
                f"Qdrant setup failed: {type(exc).__name__}: {detail}"
            ) from exc
        self._load_manifest()

    def _load_manifest(self) -> None:
        if self.manifest_path is None or not self.manifest_path.exists():
            return
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self._manifest = data
        self._manifest_valid = True
        self._manifest_loaded = True
        self._parts_compatible = True
        self._metadata_compatible = True

    def _ensure_collection(self) -> None:
        try:
            exists = self.client.collection_exists(self.collection_name)
        except Exception as exc:
            raise _operation_error("collection lookup", exc) from exc
        if not exists:
            try:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.vector_size,
                        distance=VECTOR_DISTANCE,
                    ),
                )
            except Exception as exc:
                raise _operation_error("create collection", exc) from exc
        else:
            try:
                info = self.client.get_collection(self.collection_name)
            except Exception as exc:
                raise _operation_error("collection lookup", exc) from exc
            vectors = info.config.params.vectors
            if not isinstance(vectors, models.VectorParams):
                error = ValueError("The Qdrant collection must use one unnamed dense vector.")
                raise QdrantStorageError(str(error)) from error
            if vectors.size != self.vector_size or vectors.distance != VECTOR_DISTANCE:
                error = ValueError(
                    "The existing Qdrant collection has an incompatible vector size or distance."
                )
                raise QdrantStorageError(str(error)) from error
        for field_name in ("tenant_id", "dataset_id"):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                    wait=True,
                )
            except Exception as exc:
                raise _operation_error(f"payload index ({field_name})", exc) from exc

    def _prepare_points(
        self,
        tenant_id: str,
        dataset_id: str,
        documents: Sequence[dict[str, Any]],
        vectors: Sequence[Sequence[float]],
    ) -> list[models.PointStruct]:
        if len(documents) != len(vectors):
            raise ValueError("Each Qdrant document must have exactly one embedding.")
        points: list[models.PointStruct] = []
        for document, vector in zip(documents, vectors, strict=True):
            if len(vector) != self.vector_size:
                exc = ValueError(
                    f"Embedding dimension mismatch: expected {self.vector_size}, received {len(vector)}."
                )
                raise QdrantStorageError(
                    f"point validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
                ) from exc
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
    def _write_metadata(dataset_metadata_path: str | Path, updates: dict[str, Any]) -> None:
        path = Path(dataset_metadata_path)
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata.update(updates)
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

    @staticmethod
    def _write_index_metadata(
        dataset_metadata_path: str | Path,
        dataset_hash: str,
        embedding_model_name: str,
        dimension: int,
    ) -> None:
        QdrantVectorStore._write_metadata(
            dataset_metadata_path,
            {
                "dataset_hash": dataset_hash,
                "embedding_model_name": embedding_model_name,
                "vector_dimension": dimension,
                "indexed": True,
            },
        )

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
        """Replace scoped points and mark the dataset indexed only after all writes succeed."""
        _validate_scope(tenant_id, dataset_id)
        metadata_path = Path(dataset_metadata_path)
        try:
            dataset_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise _operation_error("read indexing metadata", exc) from exc
        if (
            dataset_metadata.get("tenant_id") != tenant_id
            or dataset_metadata.get("dataset_id") != dataset_id
        ):
            exc = ValueError("Dataset metadata scope does not match the indexing request.")
            raise QdrantStorageError(
                f"index metadata validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
        try:
            self._write_metadata(metadata_path, {"indexed": False})
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise _operation_error("mark index unavailable", exc) from exc
        if dimension != self.vector_size:
            exc = ValueError(
                f"Embedding model dimension must be {self.vector_size}; received {dimension}."
            )
            raise QdrantStorageError(
                f"index validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
        points = self._prepare_points(tenant_id, dataset_id, documents, vectors)
        point_ids = [str(point.id) for point in points]
        try:
            dataset_filter = models.Filter(
                must=_scope_conditions(tenant_id, dataset_id),
            )
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=dataset_filter,
                wait=True,
            )
        except Exception as exc:
            raise _operation_error("existing-point deletion", exc) from exc
        if points:
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            except Exception as exc:
                raise _operation_error("upsert", exc) from exc

        try:
            self._write_index_metadata(
                metadata_path,
                dataset_hash,
                embedding_model_name,
                dimension,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise _operation_error("commit index metadata", exc) from exc
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
        query_values = _flatten_query_vector(query_vector)
        if dimension != self.vector_size or len(query_values) != self.vector_size:
            exc = ValueError(f"Query embeddings must have {self.vector_size} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
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
                query=query_values,
                query_filter=query_filter,
                limit=max(1, int(limit)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise _operation_error("search", exc) from exc
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
            exc = ValueError(f"Query embeddings must have {self.vector_size} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
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
        except Exception as exc:
            raise _operation_error("search", exc) from exc
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
            exc = ValueError(f"Query embeddings must have {self.vector_size} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
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
        except Exception as exc:
            raise _operation_error("search", exc) from exc
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
            exc = ValueError(f"Query embeddings must have {self.vector_size} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
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
        except Exception as exc:
            raise _operation_error("search", exc) from exc
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
            exc = ValueError(f"Query embeddings must have {self.vector_size} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
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
        except Exception as exc:
            raise _operation_error("search", exc) from exc
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    # ------------------------------------------------------------------
    # Local-vector-store compatibility surface (used by the catalog
    # startup path). All reads/writes remain scoped to tenant/dataset.
    # ------------------------------------------------------------------

    def _bound_scope(
        self,
        tenant_id: str | None = None,
        dataset_id: str | None = None,
        dataset_metadata_path: str | Path | None = None,
    ) -> tuple[str, str, Path | None]:
        return (
            tenant_id or self.tenant_id,
            dataset_id or self.dataset_id,
            Path(dataset_metadata_path)
            if dataset_metadata_path is not None
            else self.dataset_metadata_path,
        )

    def _validate_bound_scope(
        self,
        tenant_id: str,
        dataset_id: str,
        dataset_metadata_path: Path | None,
        embedding_model_name: str | None = None,
        dimension: int | None = None,
    ) -> None:
        _validate_scope(tenant_id, dataset_id)
        if dataset_metadata_path is None:
            raise QdrantStorageError("dataset metadata path is required for scoped Qdrant reads.")
        embedding_model_name = embedding_model_name or self.model_name
        dimension = self.vector_size if dimension is None else int(dimension)
        _read_search_metadata(
            dataset_metadata_path, tenant_id, dataset_id, embedding_model_name, dimension
        )

    def search_values(
        self,
        query_vector: Sequence[float],
        top_k: int,
        table: str | None = None,
        column: str | None = None,
        tenant_id: str | None = None,
        dataset_id: str | None = None,
        dataset_metadata_path: str | Path | None = None,
        embedding_model_name: str | None = None,
        dimension: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search master_value points, optionally bounded to one table/column."""
        tenant_id, dataset_id, metadata_path = self._bound_scope(
            tenant_id, dataset_id, dataset_metadata_path
        )
        self._validate_bound_scope(
            tenant_id, dataset_id, metadata_path,
            embedding_model_name=embedding_model_name, dimension=dimension,
        )
        dimension = self.vector_size if dimension is None else int(dimension)
        query_values = _flatten_query_vector(query_vector)
        if len(query_values) != dimension:
            exc = ValueError(f"Query embeddings must have {dimension} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value="master_value")))
        if table:
            conditions.append(models.FieldCondition(key="table_name", match=models.MatchValue(value=table)))
        if column:
            conditions.append(models.FieldCondition(key="column_name", match=models.MatchValue(value=column)))
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_values,
                query_filter=query_filter,
                limit=max(1, int(top_k)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise _operation_error("search_values", exc) from exc
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def search_schema(
        self,
        query_embedding: Sequence[float],
        top_k: int,
        metadata_type: str | None = None,
        tenant_id: str | None = None,
        dataset_id: str | None = None,
        dataset_metadata_path: str | Path | None = None,
        embedding_model_name: str | None = None,
        dimension: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search schema documents (table/column/relationship) within scope."""
        tenant_id, dataset_id, metadata_path = self._bound_scope(
            tenant_id, dataset_id, dataset_metadata_path
        )
        self._validate_bound_scope(
            tenant_id, dataset_id, metadata_path,
            embedding_model_name=embedding_model_name, dimension=dimension,
        )
        dimension = self.vector_size if dimension is None else int(dimension)
        query_values = _flatten_query_vector(query_embedding)
        if len(query_values) != dimension:
            exc = ValueError(f"Query embeddings must have {dimension} dimensions.")
            raise QdrantStorageError(
                f"search validation failed: ValueError: {_safe_qdrant_message(str(exc))}"
            ) from exc
        conditions = _scope_conditions(tenant_id, dataset_id)
        if metadata_type:
            conditions.append(
                models.FieldCondition(key="document_type", match=models.MatchValue(value=metadata_type))
            )
        query_filter = models.Filter(must=conditions)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_values,
                query_filter=query_filter,
                limit=max(1, int(top_k)),
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise _operation_error("search_schema", exc) from exc
        return [
            {**(point.payload or {}), "id": str(point.id), "similarity": float(point.score)}
            for point in response.points
        ]

    def count_points(
        self,
        document_type: str | None = None,
        tenant_id: str | None = None,
        dataset_id: str | None = None,
    ) -> int:
        tenant_id, dataset_id, _ = self._bound_scope(tenant_id, dataset_id, None)
        conditions = _scope_conditions(tenant_id, dataset_id)
        if document_type:
            conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value=document_type)))
        try:
            return self.client.count(
                collection_name=self.collection_name,
                count_filter=models.Filter(must=conditions),
                exact=True,
            ).count
        except Exception as exc:
            raise _operation_error("count", exc) from exc

    def count_schema(self) -> int:
        return sum(
            self.count_points(document_type=document_type)
            for document_type in (
                "table_ddl",
                "column_description",
                "relationship",
                "table",
                "column",
            )
        )

    def count_values(self) -> int:
        return self.count_points(document_type="master_value")

    def _scroll_metadata(self, document_type: str | None) -> list[dict[str, Any]]:
        tenant_id, dataset_id, _ = self._bound_scope(None, None, None)
        conditions = _scope_conditions(tenant_id, dataset_id)
        if document_type is not None:
            conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value=document_type)))
        collected: list[dict[str, Any]] = []
        offset = None
        try:
            while True:
                page, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    with_payload=True,
                    with_vectors=False,
                    offset=offset,
                    scroll_filter=models.Filter(must=conditions),
                )
                for point in page:
                    payload = point.payload or {}
                    collected.append({**payload})
                if offset is None:
                    break
        except Exception:
            return collected
        return collected

    @property
    def schema_meta(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self._scroll_metadata(None)
            if item.get("document_type") != "master_value"
        ]

    @property
    def values_meta(self) -> list[dict[str, Any]]:
        return self._scroll_metadata("master_value")

    def _embed_records(
        self, embedder: Any, records: list[dict[str, Any]], text_field: str
    ) -> list[Sequence[float]]:
        texts = [str(record.get(text_field, "")) for record in records]
        if not texts:
            return []
        vectors = embedder.embed(texts)
        import numpy as np
        if isinstance(vectors, np.ndarray):
            vectors = vectors.tolist()
        return [[float(item) for item in vector] for vector in vectors]

    def _replace_document_type(
        self,
        tenant_id: str,
        dataset_id: str,
        document_type: str,
        documents: Sequence[dict[str, Any]],
        vectors: Sequence[Sequence[float]],
        dataset_metadata_path: Path | None = None,
    ) -> list[str]:
        points = self._prepare_points(tenant_id, dataset_id, documents, vectors)
        point_ids = [str(point.id) for point in points]
        conditions = _scope_conditions(tenant_id, dataset_id)
        conditions.append(models.FieldCondition(key="document_type", match=models.MatchValue(value=document_type)))
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.Filter(must=conditions),
                wait=True,
            )
        except Exception as exc:
            raise _operation_error(f"delete {document_type} points", exc) from exc
        if points:
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=points,
                    wait=True,
                )
            except Exception as exc:
                raise _operation_error(f"upsert {document_type} points", exc) from exc
        return point_ids

    def build_schema(
        self,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        current_tables: set[str] | None = None,
    ) -> bool:
        """Embed and replace schema documents for the bound scope."""
        del current_tables  # Qdrant is the single source of truth.
        records = [dict(record) for record in records]
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            content = str(record.get("content", ""))
            if not content:
                continue
            document_type = str(record.get("metadata_type") or "table_ddl")
            groups.setdefault(document_type, []).append(
                {
                    "document_type": document_type,
                    "table_name": str(record.get("table_name", "")),
                    "column_name": record.get("column_name"),
                    "content": content,
                }
            )
        try:
            started = time.perf_counter()
            total = 0
            embedded = 0
            allow_reuse = self._manifest_valid and self._embedding_matches()
            for document_type in ("table_ddl", "column_description", "relationship"):
                documents = groups.get(document_type, [])
                existing = self._existing_vectors(document_type) if allow_reuse else {}
                vectors: list[list[float] | None] = [None] * len(documents)
                missing: list[int] = []
                for index, document in enumerate(documents):
                    point_id = deterministic_point_id(
                        self.tenant_id,
                        self.dataset_id,
                        document_type,
                        document["table_name"],
                        document["column_name"],
                        None,
                    )
                    prior = existing.get(point_id)
                    if (
                        prior is not None
                        and len(prior["vector"]) == self.vector_size
                        and prior["payload"].get("content") == document["content"]
                    ):
                        vectors[index] = prior["vector"]
                    else:
                        missing.append(index)
                if missing:
                    import numpy as np
                    batch = embedder.embed([documents[index]["content"] for index in missing])
                    if isinstance(batch, np.ndarray):
                        batch = batch.tolist()
                    if len(batch) != len(missing):
                        raise ValueError("embedding batch size mismatch")
                    for position, index in enumerate(missing):
                        vector = [float(item) for item in batch[position]]
                        if len(vector) != self.vector_size:
                            raise ValueError("embedding dimension mismatch")
                        vectors[index] = vector
                        embedded += 1
                kept_documents = [
                    document
                    for document, vector in zip(documents, vectors, strict=True)
                    if vector is not None
                ]
                kept_vectors = [vector for vector in vectors if vector is not None]
                self._replace_document_type(
                    self.tenant_id, self.dataset_id, document_type,
                    kept_documents, kept_vectors, self.dataset_metadata_path,
                )
                total += len(kept_documents)
            self.embedding_seconds += time.perf_counter() - started
            self.embedded_vectors += embedded
            self.embedding_batches += 1
            self._part_valid = {"schema": True, "values": self._part_valid.get("values", False)}
            self._part_metadata_valid = {"schema": True, "values": self._part_metadata_valid.get("values", False)}
            self._parts_compatible = True
            self._manifest_valid = True
            return True
        except (OSError, RuntimeError, ValueError, TypeError, QdrantStorageError) as exc:
            LOGGER.warning("Qdrant schema build failed (%s)", type(exc).__name__)
            return False

    def upsert_schema(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        return self.build_schema(records, embedder)

    def _existing_vectors(self, document_type: str) -> dict[str, dict[str, Any]]:
        conditions = _scope_conditions(self.tenant_id, self.dataset_id)
        conditions.append(
            models.FieldCondition(key="document_type", match=models.MatchValue(value=document_type))
        )
        existing: dict[str, dict[str, Any]] = {}
        offset = None
        try:
            while True:
                page, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    limit=256,
                    with_payload=True,
                    with_vectors=True,
                    offset=offset,
                    scroll_filter=models.Filter(must=conditions),
                )
                for point in page:
                    vector = point.vector
                    if isinstance(vector, dict):
                        vector = next(iter(vector.values()), None)
                    if vector is None:
                        continue
                    existing[str(point.id)] = {
                        "vector": [float(item) for item in vector],
                        "payload": point.payload or {},
                    }
                if offset is None:
                    break
        except Exception:
            return existing
        return existing

    def build_values(
        self,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        current_tables: set[str] | None = None,
    ) -> bool:
        """Embed and replace VALUE_LOW documents for the bound scope.

        Existing vectors for unchanged values are reused; only new values are
        embedded. Embedding failures fall back to per-value attempts so one bad
        table cannot discard the rest of the index.
        """
        del current_tables
        records = [dict(record) for record in records if str(record.get("classification", "")) == "VALUE_LOW"]
        documents = [
            {
                "document_type": "master_value",
                "table_name": str(record.get("table_name", "")),
                "column_name": str(record.get("column_name", "")),
                "value": str(record.get("value", "")),
                "content": str(record.get("content", "")) or f"{record.get('table_name','')} {record.get('column_name','')} {record.get('value','')}",
                "value_hash": record.get("value_hash") or hashlib.sha256(str(record.get("value", "")).encode("utf-8")).hexdigest(),
            }
            for record in records
            if record.get("value")
        ]
        try:
            existing = self._existing_vectors("master_value")
            allow_reuse = self._manifest_valid and self._embedding_matches()
            vectors: list[list[float] | None] = [None] * len(documents)
            missing: list[int] = []
            for index, document in enumerate(documents):
                point_id = deterministic_point_id(
                    self.tenant_id,
                    self.dataset_id,
                    "master_value",
                    document["table_name"],
                    document["column_name"],
                    document["value"],
                )
                prior = existing.get(point_id)
                if (
                    allow_reuse
                    and prior is not None
                    and len(prior["vector"]) == self.vector_size
                ):
                    vectors[index] = prior["vector"]
                else:
                    missing.append(index)

            started = time.perf_counter()
            embedded = 0
            failed_tables: set[str] = set()
            if missing:
                try:
                    batch = embedder.embed([documents[index]["value"] for index in missing])
                    import numpy as np
                    if isinstance(batch, np.ndarray):
                        batch = batch.tolist()
                    if len(batch) != len(missing):
                        raise ValueError("embedding batch size mismatch")
                    for position, index in enumerate(missing):
                        vector = [float(item) for item in batch[position]]
                        if len(vector) != self.vector_size:
                            raise ValueError("embedding dimension mismatch")
                        vectors[index] = vector
                        embedded += 1
                except Exception:
                    for index in missing:
                        try:
                            batch = embedder.embed([documents[index]["value"]])
                            import numpy as np
                            if isinstance(batch, np.ndarray):
                                batch = batch.tolist()
                            vector = [float(item) for item in batch[0]]
                            if len(vector) != self.vector_size:
                                raise ValueError("embedding dimension mismatch")
                            vectors[index] = vector
                            embedded += 1
                        except Exception:
                            failed_tables.add(documents[index]["table_name"])

            kept_documents = [
                document
                for document, vector in zip(documents, vectors, strict=True)
                if vector is not None
            ]
            kept_vectors = [vector for vector in vectors if vector is not None]
            kept_ids = {
                deterministic_point_id(
                    self.tenant_id,
                    self.dataset_id,
                    "master_value",
                    document["table_name"],
                    document["column_name"],
                    document["value"],
                )
                for document in kept_documents
            }
            # Preserve the last-known-good points for tables whose new values
            # could not be embedded.
            for point_id, prior in existing.items():
                if point_id in kept_ids:
                    continue
                payload = prior["payload"]
                if str(payload.get("table_name", "")) not in failed_tables:
                    continue
                if len(prior["vector"]) != self.vector_size:
                    continue
                kept_documents.append(
                    {
                        "document_type": "master_value",
                        "table_name": payload.get("table_name", ""),
                        "column_name": payload.get("column_name", ""),
                        "value": payload.get("value", ""),
                        "content": payload.get("content", ""),
                        "value_hash": payload.get("value_hash", ""),
                    }
                )
                kept_vectors.append(prior["vector"])
                kept_ids.add(point_id)
            self._replace_document_type(
                self.tenant_id, self.dataset_id, "master_value",
                kept_documents, kept_vectors, self.dataset_metadata_path,
            )
            self.embedding_seconds += time.perf_counter() - started
            self.embedded_vectors += embedded
            self.embedding_batches += 1
            self.failed_value_tables = failed_tables
            self._part_valid = {**self._part_valid, "values": True}
            self._part_metadata_valid = {**self._part_metadata_valid, "values": True}
            self._parts_compatible = True
            self._manifest_valid = True
            return not failed_tables
        except (OSError, RuntimeError, ValueError, TypeError, QdrantStorageError) as exc:
            LOGGER.warning("Qdrant values build failed (%s)", type(exc).__name__)
            return False

    def upsert_values(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        return self.build_values(records, embedder)

    def reconcile_values(
        self,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        current_tables: set[str] | None = None,
    ) -> bool:
        return self.build_values(records, embedder, current_tables=current_tables)

    def prune_schema(self, keep_keys: set[tuple[str, str | None, str]]) -> None:
        """No-op: Qdrant replaces the whole document-type scope on rebuild."""
        del keep_keys

    def prune_values(self, keep_keys: set[tuple[str, str, str]]) -> None:
        """No-op: Qdrant replaces the whole value scope on rebuild."""
        del keep_keys

    def clear_indexes(self) -> None:
        """Remove all points for the bound scope; examples are unchanged."""
        conditions = _scope_conditions(self.tenant_id, self.dataset_id)
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.Filter(must=conditions),
                wait=True,
            )
        except Exception as exc:
            raise _operation_error("clear indexes", exc) from exc
        self._part_valid = {"schema": False, "values": False}
        self._part_metadata_valid = {"schema": False, "values": False}
        self._manifest_valid = False
        self.classification_cache = None
        if self.manifest_path is not None:
            try:
                self.manifest_path.unlink(missing_ok=True)
            except OSError:
                pass

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    @property
    def classification_cache(self) -> dict[str, Any] | None:
        return self._manifest.get("classification_cache")

    @classification_cache.setter
    def classification_cache(self, value: dict[str, Any] | None) -> None:
        self._manifest["classification_cache"] = value

    def _embedding_matches(self) -> bool:
        return (
            self._manifest.get("embedding_model_name") == self.model_name
            and self._manifest.get("vector_dimension") == self.vector_size
        )

    def _policy_matches(self) -> bool:
        return self._manifest.get("config_policy_hash") == self.policy_hash

    def _manifest_matches(self) -> bool:
        return (
            self._manifest_valid
            and self._embedding_matches()
            and self._policy_matches()
        )

    def part_is_valid(self, part: str) -> bool:
        if part not in ("schema", "values"):
            raise ValueError("Unknown index part.")
        if self._manifest_loaded:
            return self._manifest_valid and self._embedding_matches()
        return bool(self._part_valid.get(part, False)) and self._manifest_valid and self._embedding_matches()

    def part_metadata_is_valid(self, part: str) -> bool:
        if part not in ("schema", "values"):
            raise ValueError("Unknown index part.")
        if self._manifest_loaded:
            return self._manifest_valid and self._policy_matches()
        return bool(self._part_metadata_valid.get(part, False))

    def fast_path_valid(
        self,
        global_schema_fingerprint: str,
        scan_tables: set[str],
        refresh_ttl_hours: float,
        now: float | None = None,
    ) -> bool:
        if not (
            self._manifest_valid
            and self._manifest_matches()
            and self.part_is_valid("schema")
            and self.part_is_valid("values")
            and not self._manifest.get("index_incomplete", False)
            and self._manifest.get("classification_cache") is not None
            and self._manifest.get("global_schema_fingerprint") == global_schema_fingerprint
        ):
            return False
        if refresh_ttl_hours <= 0 and scan_tables:
            return False
        timestamp = time.time() if now is None else float(now)
        last_scans = self._manifest.get("last_value_scan_at", {})
        max_age = float(refresh_ttl_hours) * 3600
        return all(
            table in last_scans
            and timestamp - float(last_scans[table]) < max_age
            for table in scan_tables
        )

    def save_index_state(
        self,
        global_schema_fingerprint: str,
        table_fingerprints: dict[str, str],
        last_value_scan_at: dict[str, float],
        classification_cache: dict[str, Any],
        incomplete_tables: dict[str, str] | None = None,
        generic_policy_hash: str | None = None,
    ) -> None:
        self._manifest.update({
            "store_format_version": 2,
            "embedding_model_name": self.model_name,
            "vector_dimension": self.vector_size,
            "normalization_version": "l2-float32-v1",
            "config_policy_hash": self.policy_hash,
            "generic_policy_hash": generic_policy_hash,
            "global_schema_fingerprint": global_schema_fingerprint,
            "table_fingerprints": dict(table_fingerprints),
            "last_value_scan_at": {key: float(value) for key, value in last_value_scan_at.items()},
            "incomplete_tables": dict(incomplete_tables or {}),
            "index_incomplete": bool(incomplete_tables),
            "build_time": time.time(),
        })
        self._manifest["classification_cache"] = classification_cache
        self._manifest_valid = True
        self._parts_compatible = True
        if self.manifest_path is not None:
            try:
                self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
                self.manifest_path.write_text(
                    json.dumps(self._manifest), encoding="utf-8"
                )
            except (OSError, TypeError, ValueError):
                LOGGER.warning("Qdrant manifest persistence failed")

    def close(self) -> None:
        """No persistent connection is held; present for lifecycle symmetry."""