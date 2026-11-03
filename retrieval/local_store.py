"""Atomic, namespace-scoped local vector and verified-example storage."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable

import faiss
import numpy as np

LOGGER = logging.getLogger(__name__)
STORE_FORMAT_VERSION = 1
NORMALIZATION_VERSION = "l2-float32-v1"
_LOCKS_GUARD = threading.Lock()
_NAMESPACE_LOCKS: dict[str, threading.RLock] = {}


class LocalVectorStore:
    """Store schema/value vectors and verified examples outside the target database."""

    def __init__(
        self,
        root: str | Path,
        namespace: str,
        model_name: str,
        dimension: int,
        policy_hash: str,
        example_candidate_limit: int = 500,
    ) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive.")
        self.path = Path(root) / namespace
        self.path.mkdir(parents=True, exist_ok=True)
        self.model_name = str(model_name)
        self.dimension = int(dimension)
        self.policy_hash = str(policy_hash)
        self.example_candidate_limit = max(1, int(example_candidate_limit))
        lock_key = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _NAMESPACE_LOCKS.setdefault(lock_key, threading.RLock())
        self._manifest_path = self.path / "manifest.json"
        self._cache_path = self.path / "embed_cache.sqlite"
        self._examples_path = self.path / "examples.sqlite"
        with self._lock:
            self._manifest = self._load_manifest()
            self.schema_index, self.schema_meta = self._load_part("schema")
            self.values_index, self.values_meta = self._load_part("values")
            self._initialize_sqlite(self._cache_path, "embed cache")
            self._initialize_sqlite(self._examples_path, "examples")
            self._ensure_manifest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file_obj:
            for block in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _atomic_bytes(self, target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as file_obj:
                file_obj.write(payload)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_json(self, target: Path, payload: Any) -> None:
        self._atomic_bytes(
            target,
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        )

    def _manifest_template(self) -> dict[str, Any]:
        return {
            "store_format_version": STORE_FORMAT_VERSION,
            "embedding_model_name": self.model_name,
            "vector_dimension": self.dimension,
            "normalization_version": NORMALIZATION_VERSION,
            "config_policy_hash": self.policy_hash,
            "build_time": time.time(),
            "schema_index_sha256": None,
            "schema_meta_sha256": None,
            "values_index_sha256": None,
            "values_meta_sha256": None,
        }

    def _load_manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.exists():
            LOGGER.info("Local store part manifest unavailable: missing")
            self._discard_part_files("schema")
            self._discard_part_files("values")
            return None
        try:
            manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("invalid manifest shape")
            expected = self._manifest_template()
            mismatches = [
                key
                for key in (
                    "store_format_version",
                    "embedding_model_name",
                    "vector_dimension",
                    "normalization_version",
                    "config_policy_hash",
                )
                if manifest.get(key) != expected[key]
            ]
            if mismatches:
                LOGGER.warning(
                    "Local store indexes invalidated: manifest mismatch (%s)",
                    ",".join(mismatches),
                )
                self._discard_part_files("schema")
                self._discard_part_files("values")
                return None
            return manifest
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
            LOGGER.warning(
                "Local store indexes invalidated: manifest %s",
                type(error).__name__,
            )
            self._discard_part_files("schema")
            self._discard_part_files("values")
            return None

    def _part_paths(self, part: str) -> tuple[Path, Path]:
        return self.path / f"{part}.faiss", self.path / f"{part}_meta.json"

    def _discard_part_files(self, part: str) -> None:
        index_path, meta_path = self._part_paths(part)
        index_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    def _load_part(self, part: str) -> tuple[Any, list[dict[str, Any]]]:
        index_path, meta_path = self._part_paths(part)
        if self._manifest is None:
            return faiss.IndexFlatIP(self.dimension), []
        if not index_path.exists() or not meta_path.exists():
            LOGGER.info("Local store %s index invalidated: paired file missing", part)
            self._discard_part_files(part)
            return faiss.IndexFlatIP(self.dimension), []
        try:
            expected_index_hash = self._manifest.get(f"{part}_index_sha256")
            expected_meta_hash = self._manifest.get(f"{part}_meta_sha256")
            if (
                not expected_index_hash
                or not expected_meta_hash
                or self._sha256_file(index_path) != expected_index_hash
                or self._sha256_file(meta_path) != expected_meta_hash
            ):
                raise ValueError("paired file checksum mismatch")
            index = faiss.read_index(str(index_path))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, list):
                raise ValueError("metadata is not a list")
            if not isinstance(index, faiss.IndexFlatIP):
                raise ValueError("index is not IndexFlatIP")
            if index.d != self.dimension or index.ntotal != len(meta):
                raise ValueError("dimension or row count mismatch")
            return index, meta
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as error:
            LOGGER.warning("Local store %s index invalidated: %s", part, type(error).__name__)
            self._discard_part_files(part)
            return faiss.IndexFlatIP(self.dimension), []

    def _ensure_manifest(self) -> None:
        if self._manifest is None:
            self._manifest = self._manifest_template()
            self._write_manifest()

    def _write_manifest(self) -> None:
        self._manifest["build_time"] = time.time()
        self._atomic_json(self._manifest_path, self._manifest)

    def _write_part(
        self,
        part: str,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        index = faiss.IndexFlatIP(self.dimension)
        if len(vectors):
            add_vectors = getattr(index, "add")
            add_vectors(np.ascontiguousarray(vectors, dtype=np.float32))
        index_path, meta_path = self._part_paths(part)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{part}.", suffix=".faiss.tmp", dir=self.path
        )
        os.close(descriptor)
        temporary_index = Path(temporary_name)
        try:
            faiss.write_index(index, str(temporary_index))
            with temporary_index.open("rb") as file_obj:
                os.fsync(file_obj.fileno())
            temporary_meta = meta_path.with_name(f".{meta_path.name}.tmp")
            self._atomic_json(temporary_meta, metadata)
            os.replace(temporary_index, index_path)
            os.replace(temporary_meta, meta_path)
            directory_fd = os.open(self.path, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary_index.unlink(missing_ok=True)
            meta_path.with_name(f".{meta_path.name}.tmp").unlink(missing_ok=True)

        self._manifest[f"{part}_index_sha256"] = self._sha256_file(index_path)
        self._manifest[f"{part}_meta_sha256"] = self._sha256_file(meta_path)
        self._write_manifest()
        if part == "schema":
            self.schema_index, self.schema_meta = index, metadata
        else:
            self.values_index, self.values_meta = index, metadata

    @staticmethod
    def _normalize_vectors(vectors: Any, dimension: int) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != dimension:
            raise ValueError("Embedding dimension does not match local-store manifest.")
        if not np.isfinite(matrix).all():
            raise ValueError("Embeddings must be finite.")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise ValueError("Zero vectors cannot be indexed.")
        return np.ascontiguousarray(matrix / norms[:, None], dtype=np.float32)

    def _initialize_sqlite(self, path: Path, label: str) -> None:
        try:
            with sqlite3.connect(path) as connection:
                if label == "embed cache":
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS embeddings ("
                        "content_hash TEXT NOT NULL, model_name TEXT NOT NULL, "
                        "dimension INTEGER NOT NULL, vector BLOB NOT NULL, "
                        "PRIMARY KEY(content_hash, model_name))"
                    )
                else:
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS examples ("
                        "id INTEGER PRIMARY KEY, question TEXT NOT NULL UNIQUE, "
                        "sql TEXT NOT NULL, updated_at REAL NOT NULL)"
                    )
        except sqlite3.DatabaseError as error:
            LOGGER.warning("Local %s database rebuilt: %s", label, type(error).__name__)
            path.unlink(missing_ok=True)
            with sqlite3.connect(path) as connection:
                if label == "embed cache":
                    connection.execute(
                        "CREATE TABLE embeddings (content_hash TEXT NOT NULL, model_name TEXT NOT NULL, "
                        "dimension INTEGER NOT NULL, vector BLOB NOT NULL, "
                        "PRIMARY KEY(content_hash, model_name))"
                    )
                else:
                    connection.execute(
                        "CREATE TABLE examples (id INTEGER PRIMARY KEY, question TEXT NOT NULL UNIQUE, "
                        "sql TEXT NOT NULL, updated_at REAL NOT NULL)"
                    )

    def _cache_get(self, content_hash: str) -> np.ndarray | None:
        with sqlite3.connect(self._cache_path) as connection:
            row = connection.execute(
                "SELECT dimension, vector FROM embeddings WHERE content_hash = ? AND model_name = ?",
                (content_hash, self.model_name),
            ).fetchone()
        if row is None or row[0] != self.dimension:
            return None
        vector = np.frombuffer(row[1], dtype=np.float32)
        if vector.size != self.dimension or not np.isfinite(vector).all():
            return None
        norm = np.linalg.norm(vector)
        if norm == 0:
            return None
        return np.asarray(vector / norm, dtype=np.float32)

    def _cache_put(self, content_hash: str, vector: np.ndarray) -> None:
        normalized = self._normalize_vectors(vector, self.dimension)[0]
        with sqlite3.connect(self._cache_path) as connection:
            connection.execute(
                "INSERT INTO embeddings(content_hash, model_name, dimension, vector) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(content_hash, model_name) DO UPDATE SET "
                "dimension = excluded.dimension, vector = excluded.vector",
                (content_hash, self.model_name, self.dimension, normalized.tobytes()),
            )

    def _vectors_for(
        self,
        records: list[dict[str, Any]],
        embedder: Any,
        text_field: str,
        hash_field: str,
    ) -> np.ndarray:
        vectors: list[np.ndarray | None] = [None] * len(records)
        missing_indices: list[int] = []
        missing_hashes: list[str] = []
        for index, record in enumerate(records):
            vector = self._cache_get(record[hash_field])
            if vector is None:
                missing_indices.append(index)
                missing_hashes.append(record[hash_field])
            else:
                vectors[index] = vector

        unique_hashes = list(dict.fromkeys(missing_hashes))
        if unique_hashes:
            hash_to_text: dict[str, str] = {}
            for record in records:
                hash_to_text.setdefault(record[hash_field], record[text_field])
            embedded = self._normalize_vectors(
                embedder.embed([hash_to_text[value] for value in unique_hashes]),
                self.dimension,
            )
            for content_hash, vector in zip(unique_hashes, embedded, strict=True):
                self._cache_put(content_hash, vector)
            cached = {content_hash: vector for content_hash, vector in zip(unique_hashes, embedded, strict=True)}
            for index in missing_indices:
                vectors[index] = cached[records[index][hash_field]]

        return np.ascontiguousarray(np.stack(vectors), dtype=np.float32) if vectors else np.empty((0, self.dimension), dtype=np.float32)

    def _build_part(
        self,
        part: str,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        text_field: str,
        hash_field: str,
        required_fields: tuple[str, ...],
    ) -> bool:
        prepared: list[dict[str, Any]] = []
        for source in records:
            record = dict(source)
            if part == "values" and record.pop("classification", None) != "VALUE_LOW":
                continue
            content = str(record.get(text_field, ""))
            if not content or (part == "values" and not record.get("value")):
                continue
            record[hash_field] = record.get(hash_field) or self._content_hash(content)
            if any(field not in record for field in required_fields):
                raise ValueError(f"Missing {part} metadata field.")
            prepared.append(record)
        with self._lock:
            try:
                vectors = self._vectors_for(prepared, embedder, text_field, hash_field)
                metadata = prepared if part == "values" else [
                    {key: value for key, value in row.items() if key != text_field}
                    for row in prepared
                ]
                self._write_part(part, vectors, metadata)
                return True
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.DatabaseError) as error:
                LOGGER.warning("Local %s index build failed (%s)", part, type(error).__name__)
                return False

    def build_schema(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        """Build/reconcile schema rows with metadata fields and an internal content field."""
        return self._build_part(
            "schema",
            records,
            embedder,
            "content",
            "content_hash",
            ("table_name", "column_name", "metadata_type"),
        )

    def upsert_schema(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        """Compatibility alias for a full schema-index reconciliation build."""
        return self.build_schema(records, embedder)

    def build_values(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        """Build/reconcile VALUE_LOW rows; callers must not pass other value classes."""
        return self._build_part(
            "values",
            records,
            embedder,
            "value",
            "value_hash",
            ("table_name", "column_name"),
        )

    def upsert_values(self, records: Iterable[dict[str, Any]], embedder: Any) -> bool:
        """Compatibility alias for a full value-index reconciliation build."""
        return self.build_values(records, embedder)

    def prune_schema(self, keep_keys: set[tuple[str, str | None, str]]) -> None:
        """Batch-prune schema metadata and vectors absent from the keep set."""
        with self._lock:
            kept = [
                (meta, self.schema_index.reconstruct(index))
                for index, meta in enumerate(self.schema_meta)
                if (meta["table_name"], meta.get("column_name"), meta["metadata_type"]) in keep_keys
            ]
            vectors = np.stack([vector for _, vector in kept]) if kept else np.empty((0, self.dimension), dtype=np.float32)
            self._write_part("schema", vectors, [meta for meta, _ in kept])

    def prune_values(self, keep_keys: set[tuple[str, str, str]]) -> None:
        """Batch-prune value metadata and vectors absent from the keep set."""
        with self._lock:
            kept = [
                (meta, self.values_index.reconstruct(index))
                for index, meta in enumerate(self.values_meta)
                if (meta["table_name"], meta["column_name"], meta["value_hash"]) in keep_keys
            ]
            vectors = np.stack([vector for _, vector in kept]) if kept else np.empty((0, self.dimension), dtype=np.float32)
            self._write_part("values", vectors, [meta for meta, _ in kept])

    def search_schema(
        self,
        query_embedding: Any,
        top_k: int,
        metadata_type: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._search(self.schema_index, self.schema_meta, query_embedding, top_k, metadata_type=metadata_type)

    def search_values(
        self,
        query_embedding: Any,
        top_k: int,
        table: str | None = None,
        column: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._search(self.values_index, self.values_meta, query_embedding, top_k, table=table, column=column)

    def _search(
        self,
        index: Any,
        metadata: list[dict[str, Any]],
        query_embedding: Any,
        top_k: int,
        metadata_type: str | None = None,
        table: str | None = None,
        column: str | None = None,
    ) -> list[dict[str, Any]]:
        requested = max(0, int(top_k))
        if requested == 0 or index.ntotal == 0:
            return []
        query = self._normalize_vectors(query_embedding, self.dimension)
        search_k = min(index.ntotal, max(requested, requested * 2))
        matches: list[dict[str, Any]] = []
        while True:
            scores, ids = index.search(query, search_k)
            matches = []
            for score, row_id in zip(scores[0], ids[0], strict=True):
                if row_id < 0:
                    continue
                row = metadata[int(row_id)]
                if metadata_type is not None and row.get("metadata_type") != metadata_type:
                    continue
                if table is not None and row.get("table_name") != table:
                    continue
                if column is not None and row.get("column_name") != column:
                    continue
                matches.append({**row, "similarity": float(score)})
                if len(matches) >= requested:
                    return matches
            if search_k == index.ntotal:
                return matches
            search_k = min(index.ntotal, max(search_k + 1, search_k * 2))

    def count_schema(self) -> int:
        with self._lock:
            return len(self.schema_meta)

    def count_values(self) -> int:
        with self._lock:
            return len(self.values_meta)

    def get_examples(self, limit: int | None = None) -> list[dict[str, str]]:
        candidate_limit = min(
            self.example_candidate_limit,
            max(1, int(limit)) if limit is not None else self.example_candidate_limit,
        )
        with self._lock:
            with sqlite3.connect(self._examples_path) as connection:
                rows = connection.execute(
                    "SELECT question, sql FROM examples ORDER BY updated_at DESC, id DESC LIMIT ?",
                    (candidate_limit,),
                ).fetchall()
        return [{"question": question, "sql": sql} for question, sql in rows]

    def save_example(self, question: str, sql: str) -> bool:
        try:
            with self._lock:
                with sqlite3.connect(self._examples_path) as connection:
                    connection.execute(
                        "INSERT INTO examples(question, sql, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(question) DO UPDATE SET sql = excluded.sql, updated_at = excluded.updated_at",
                        (question, sql, time.time()),
                    )
            return True
        except sqlite3.DatabaseError:
            LOGGER.warning("Local example persistence failed")
            return False

    def clear_indexes(self) -> None:
        """Clear only this namespace's indexes and embedding cache; retain verified examples."""
        with self._lock:
            for part in ("schema", "values"):
                self._discard_part_files(part)
            self._manifest_path.unlink(missing_ok=True)
            self._cache_path.unlink(missing_ok=True)
            self._manifest = None
            self.schema_index = faiss.IndexFlatIP(self.dimension)
            self.schema_meta = []
            self.values_index = faiss.IndexFlatIP(self.dimension)
            self.values_meta = []
            self._initialize_sqlite(self._cache_path, "embed cache")
            self._ensure_manifest()

    def close(self) -> None:
        """No persistent connection is held; present for lifecycle symmetry."""