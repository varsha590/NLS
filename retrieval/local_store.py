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
from typing import Any, Callable, Iterable

import faiss
import numpy as np

LOGGER = logging.getLogger(__name__)
STORE_FORMAT_VERSION = 2
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
        clock: Callable[[], float] | None = None,
        embed_cache_max_entries: int = 250000,
    ) -> None:
        if dimension < 1:
            raise ValueError("Embedding dimension must be positive.")
        self.path = Path(root) / namespace
        self.path.mkdir(parents=True, exist_ok=True)
        self.model_name = str(model_name)
        self.dimension = int(dimension)
        self.policy_hash = str(policy_hash)
        self.example_candidate_limit = max(1, int(example_candidate_limit))
        self._clock = clock or time.time
        self.embed_cache_max_entries = max(1, int(embed_cache_max_entries))
        self._manifest_valid = False
        self._parts_compatible = False
        self._metadata_compatible = False
        self._part_valid = {"schema": False, "values": False}
        self._part_metadata_valid = {"schema": False, "values": False}
        self.failed_value_tables: set[str] = set()
        self.embedding_batches = 0
        self.embedded_vectors = 0
        self.embedding_seconds = 0.0
        self.save_seconds = 0.0
        lock_key = str(self.path.resolve())
        with _LOCKS_GUARD:
            self._lock = _NAMESPACE_LOCKS.setdefault(lock_key, threading.RLock())
        self._manifest_path = self.path / "manifest.json"
        self.classification_cache_path = self.path / "classification_cache.json"
        self._cache_path = self.path / "embed_cache.sqlite"
        self._examples_path = self.path / "examples.sqlite"
        with self._lock:
            self._manifest = self._load_manifest()
            self.schema_index, self.schema_meta = self._load_part("schema")
            self.values_index, self.values_meta = self._load_part("values")
            self.classification_cache = self.load_classification_cache()
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
            "generic_policy_hash": None,
            "build_time": self._clock(),
            "global_schema_fingerprint": None,
            "table_fingerprints": {},
            "last_value_scan_at": {},
            "classification_cache_sha256": None,
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
            self._metadata_compatible = (
                manifest.get("store_format_version") == expected["store_format_version"]
            )
            self._parts_compatible = self._metadata_compatible and all(
                manifest.get(key) == expected[key]
                for key in (
                    "embedding_model_name",
                    "vector_dimension",
                    "normalization_version",
                )
            )
            self._manifest_valid = self._parts_compatible and (
                manifest.get("config_policy_hash") == self.policy_hash
            )
            if not self._parts_compatible:
                LOGGER.warning(
                    "Local store vector parts require rebuild: runtime manifest mismatch"
                )
            elif manifest.get("config_policy_hash") != self.policy_hash:
                LOGGER.info("Local store classification cache requires policy refresh")
            return manifest
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
            LOGGER.warning(
                "Local store indexes invalidated: manifest %s",
                type(error).__name__,
            )
            self._discard_part_files("schema")
            self._discard_part_files("values")
            self.classification_cache_path.unlink(missing_ok=True)
            return None

    def _part_paths(self, part: str) -> tuple[Path, Path]:
        return self.path / f"{part}.faiss", self.path / f"{part}_meta.json"

    def _discard_part_files(self, part: str) -> None:
        index_path, meta_path = self._part_paths(part)
        index_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    def _load_part(self, part: str) -> tuple[Any, list[dict[str, Any]]]:
        index_path, meta_path = self._part_paths(part)
        if self._manifest is None or not self._metadata_compatible:
            return faiss.IndexFlatIP(self.dimension), []
        if not meta_path.exists():
            LOGGER.info("Local store %s metadata invalidated: file missing", part)
            self._discard_part_files(part)
            return faiss.IndexFlatIP(self.dimension), []
        try:
            expected_meta_hash = self._manifest.get(f"{part}_meta_sha256")
            if not expected_meta_hash or self._sha256_file(meta_path) != expected_meta_hash:
                raise ValueError("metadata checksum mismatch")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, list):
                raise ValueError("metadata is not a list")
            self._part_metadata_valid[part] = True
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as error:
            LOGGER.warning(
                "Local store %s metadata invalidated (%s)", part, type(error).__name__
            )
            self._discard_part_files(part)
            return faiss.IndexFlatIP(self.dimension), []

        expected_index_hash = self._manifest.get(f"{part}_index_sha256")
        if (
            not index_path.exists()
            or not expected_index_hash
            or self._sha256_file(index_path) != expected_index_hash
        ):
            LOGGER.info("Local store %s vectors require rebuild", part)
            index_path.unlink(missing_ok=True)
            return faiss.IndexFlatIP(self.dimension), meta
        try:
            index = faiss.read_index(str(index_path))
            if not isinstance(index, faiss.IndexFlatIP) or index.ntotal != len(meta):
                raise ValueError("index type or row count mismatch")
            if not self._parts_compatible or index.d != self.dimension:
                return faiss.IndexFlatIP(self.dimension), meta
            self._part_valid[part] = True
            return index, meta
        except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError) as error:
            LOGGER.warning("Local store %s index invalidated: %s", part, type(error).__name__)
            index_path.unlink(missing_ok=True)
            return faiss.IndexFlatIP(self.dimension), meta

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest or {})

    def part_is_valid(self, part: str) -> bool:
        if part not in self._part_valid:
            raise ValueError("Unknown local index part.")
        return self._part_valid[part]

    def part_metadata_is_valid(self, part: str) -> bool:
        if part not in self._part_metadata_valid:
            raise ValueError("Unknown local index part.")
        return self._part_metadata_valid[part]

    def load_classification_cache(self) -> dict[str, Any] | None:
        """Load only count/classification metadata matching the active policy."""
        manifest = self._manifest or {}
        expected_hash = manifest.get("classification_cache_sha256")
        if (
            not expected_hash
            or not self.classification_cache_path.exists()
        ):
            return None
        try:
            if self._sha256_file(self.classification_cache_path) != expected_hash:
                raise ValueError("classification cache checksum mismatch")
            payload = json.loads(self.classification_cache_path.read_text(encoding="utf-8"))
            if (
                payload.get("policy_hash") != manifest.get("config_policy_hash")
                or not isinstance(payload.get("tables"), dict)
            ):
                raise ValueError("classification cache metadata mismatch")
            return payload["tables"]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            LOGGER.warning("Classification cache unavailable (%s)", type(error).__name__)
            return None

    def save_index_state(
        self,
        global_schema_fingerprint: str,
        table_fingerprints: dict[str, str],
        last_value_scan_at: dict[str, float],
        classification_cache: dict[str, Any],
        incomplete_tables: dict[str, str] | None = None,
        generic_policy_hash: str | None = None,
    ) -> None:
        """Atomically persist fingerprints and count/class-only classifications."""
        safe_tables: dict[str, Any] = {}
        for table_name, table_cache in classification_cache.items():
            safe_columns: dict[str, Any] = {}
            for column_name, entry in table_cache.get("columns", {}).items():
                safe_columns[column_name] = {
                    key: entry.get(key)
                    for key in (
                        "class",
                        "reason",
                        "distinct_count",
                        "non_null_count",
                        "avg_text_length",
                    )
                }
            safe_entry = {
                "fingerprint": table_cache.get("fingerprint"),
                "columns": safe_columns,
            }
            if "policy_fingerprint" in table_cache:
                safe_entry["policy_fingerprint"] = table_cache["policy_fingerprint"]
            if "column_fingerprints" in table_cache:
                safe_entry["column_fingerprints"] = {
                    key: str(value)
                    for key, value in table_cache["column_fingerprints"].items()
                }
            safe_tables[table_name] = safe_entry
        cache_payload = {"policy_hash": self.policy_hash, "tables": safe_tables}
        self._atomic_json(self.classification_cache_path, cache_payload)
        with self._lock:
            if self._manifest is None:
                self._manifest = self._manifest_template()
            self._manifest.update({
                "store_format_version": STORE_FORMAT_VERSION,
                "embedding_model_name": self.model_name,
                "vector_dimension": self.dimension,
                "normalization_version": NORMALIZATION_VERSION,
                "config_policy_hash": self.policy_hash,
                "generic_policy_hash": generic_policy_hash,
                "global_schema_fingerprint": global_schema_fingerprint,
                "table_fingerprints": dict(table_fingerprints),
                "last_value_scan_at": {
                    key: float(value) for key, value in last_value_scan_at.items()
                },
                "incomplete_tables": dict(incomplete_tables or {}),
                "index_incomplete": bool(incomplete_tables),
                "classification_cache_sha256": self._sha256_file(
                    self.classification_cache_path
                ),
            })
            self._write_manifest()
            self._manifest_valid = True
            self._parts_compatible = True
            self.classification_cache = safe_tables
            self._gc_embedding_cache()

    def fast_path_valid(
        self,
        global_schema_fingerprint: str,
        scan_tables: set[str],
        refresh_ttl_hours: float,
        now: float | None = None,
    ) -> bool:
        """Check every persisted contract before skipping indexing work."""
        if not (
            self._manifest_valid
            and self._part_valid["schema"]
            and self._part_valid["values"]
            and not self.manifest.get("index_incomplete", False)
            and self.classification_cache is not None
            and self.manifest.get("global_schema_fingerprint") == global_schema_fingerprint
        ):
            return False
        if refresh_ttl_hours <= 0 and scan_tables:
            return False
        timestamp = self._clock() if now is None else float(now)
        last_scans = self.manifest.get("last_value_scan_at", {})
        max_age = float(refresh_ttl_hours) * 3600
        return all(
            table in last_scans
            and timestamp - float(last_scans[table]) < max_age
            for table in scan_tables
        )

    def _ensure_manifest(self) -> None:
        if self._manifest is None:
            self._manifest = self._manifest_template()
            self._write_manifest()

    def _write_manifest(self) -> None:
        self._manifest["build_time"] = self._clock()
        self._atomic_json(self._manifest_path, self._manifest)

    def _gc_embedding_cache(self, batch_size: int = 1000) -> None:
        """Remove unreferenced cache rows in bounded batches above the configured cap."""
        active_hashes = {
            str(item.get("content_hash", ""))
            for item in self.schema_meta
        } | {
            str(item.get("value_hash", ""))
            for item in self.values_meta
        }
        try:
            with sqlite3.connect(self._cache_path) as connection:
                row = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()
                if row is None or int(row[0]) <= self.embed_cache_max_entries:
                    return
                cursor = connection.execute(
                    "SELECT content_hash, model_name FROM embeddings ORDER BY rowid"
                )
                while True:
                    batch = cursor.fetchmany(max(1, int(batch_size)))
                    if not batch:
                        break
                    stale = [
                        (content_hash, model_name)
                        for content_hash, model_name in batch
                        if model_name != self.model_name or content_hash not in active_hashes
                    ]
                    if stale:
                        connection.executemany(
                            "DELETE FROM embeddings WHERE content_hash = ? AND model_name = ?",
                            stale,
                        )
        except sqlite3.DatabaseError as error:
            LOGGER.warning("Embedding cache cleanup failed (%s)", type(error).__name__)

    def _write_part(
        self,
        part: str,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        started = time.perf_counter()
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
        if not self._parts_compatible:
            other = "values" if part == "schema" else "schema"
            self._manifest[f"{other}_index_sha256"] = None
            self._manifest[f"{other}_meta_sha256"] = None
            self._manifest.update({
                "store_format_version": STORE_FORMAT_VERSION,
                "embedding_model_name": self.model_name,
                "vector_dimension": self.dimension,
                "normalization_version": NORMALIZATION_VERSION,
            })
            self._parts_compatible = True
        self._write_manifest()
        if part == "schema":
            self.schema_index, self.schema_meta = index, metadata
        else:
            self.values_index, self.values_meta = index, metadata
        self._part_valid[part] = True
        self._part_metadata_valid[part] = True
        self.save_seconds += time.perf_counter() - started

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
        with sqlite3.connect(self._cache_path) as connection:
            for index, record in enumerate(records):
                content_hash = record[hash_field]
                row = connection.execute(
                    "SELECT dimension, vector FROM embeddings "
                    "WHERE content_hash = ? AND model_name = ?",
                    (content_hash, self.model_name),
                ).fetchone()
                if row is None or row[0] != self.dimension:
                    missing_indices.append(index)
                    missing_hashes.append(content_hash)
                    continue
                vector = np.frombuffer(row[1], dtype=np.float32)
                norm = np.linalg.norm(vector)
                if vector.size != self.dimension or not np.isfinite(vector).all() or norm == 0:
                    missing_indices.append(index)
                    missing_hashes.append(content_hash)
                    continue
                vectors[index] = np.asarray(vector / norm, dtype=np.float32)

            unique_hashes = list(dict.fromkeys(missing_hashes))
            if unique_hashes:
                hash_to_text: dict[str, str] = {}
                for record in records:
                    hash_to_text.setdefault(record[hash_field], record[text_field])
                embed_started = time.perf_counter()
                embedded = self._normalize_vectors(
                    embedder.embed([hash_to_text[value] for value in unique_hashes]),
                    self.dimension,
                )
                self.embedding_seconds += time.perf_counter() - embed_started
                self.embedding_batches += 1
                self.embedded_vectors += len(unique_hashes)
                connection.executemany(
                    "INSERT INTO embeddings(content_hash, model_name, dimension, vector) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(content_hash, model_name) DO UPDATE SET "
                    "dimension = excluded.dimension, vector = excluded.vector",
                    [
                        (content_hash, self.model_name, self.dimension, vector.tobytes())
                        for content_hash, vector in zip(unique_hashes, embedded, strict=True)
                    ],
                )
                cached = {
                    content_hash: vector
                    for content_hash, vector in zip(unique_hashes, embedded, strict=True)
                }
                for index in missing_indices:
                    vectors[index] = cached[records[index][hash_field]]

        return (
            np.ascontiguousarray(np.stack(vectors), dtype=np.float32)
            if vectors
            else np.empty((0, self.dimension), dtype=np.float32)
        )

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
        metadata = prepared if part == "values" else [
            {key: value for key, value in row.items() if key != text_field}
            for row in prepared
        ]
        with self._lock:
            current_metadata = self.schema_meta if part == "schema" else self.values_meta
            if self._part_valid[part] and current_metadata == metadata:
                return True
            try:
                vectors = self._vectors_for(prepared, embedder, text_field, hash_field)
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

    def build_values(
        self,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        current_tables: set[str] | None = None,
    ) -> bool:
        """Build/reconcile VALUE_LOW rows; callers must not pass other value classes."""
        return self.reconcile_values(records, embedder, current_tables)

    def reconcile_values(
        self,
        records: Iterable[dict[str, Any]],
        embedder: Any,
        current_tables: set[str] | None = None,
    ) -> bool:
        """Reconcile value vectors, isolating exceptional embedding failures by table."""
        source_records = [dict(record) for record in records]
        self.failed_value_tables.clear()
        if self._build_part(
            "values",
            source_records,
            embedder,
            "value",
            "value_hash",
            ("table_name", "column_name"),
        ):
            return True

        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in source_records:
            if record.get("classification") != "VALUE_LOW":
                continue
            record.pop("classification", None)
            value = str(record.get("value", ""))
            if not value:
                continue
            record["value"] = value
            record["value_hash"] = record.get("value_hash") or self._content_hash(value)
            if "table_name" not in record or "column_name" not in record:
                return False
            grouped.setdefault(str(record["table_name"]), []).append(record)

        live_tables = set(current_tables) if current_tables is not None else set(grouped)
        live_tables.update(grouped)
        old_by_table: dict[str, list[tuple[dict[str, Any], np.ndarray]]] = {}
        if self._part_valid["values"]:
            for index, metadata in enumerate(self.values_meta):
                old_by_table.setdefault(metadata["table_name"], []).append(
                    (metadata, self.values_index.reconstruct(index))
                )

        merged_metadata: list[dict[str, Any]] = []
        merged_vectors: list[np.ndarray] = []
        successful_tables = 0
        for table_name in sorted(live_tables):
            table_records = grouped.get(table_name, [])
            if not table_records:
                continue
            try:
                vectors = self._vectors_for(
                    table_records, embedder, "value", "value_hash"
                )
            except (OSError, RuntimeError, ValueError, TypeError, sqlite3.DatabaseError) as error:
                self.failed_value_tables.add(table_name)
                LOGGER.warning(
                    "Local value embedding failed for table (%s)",
                    type(error).__name__,
                    extra={"table": table_name, "error_category": type(error).__name__},
                )
                for metadata, vector in old_by_table.get(table_name, []):
                    merged_metadata.append(metadata)
                    merged_vectors.append(vector)
                continue
            merged_metadata.extend(table_records)
            merged_vectors.extend(vectors)
            successful_tables += 1

        if not successful_tables and self.failed_value_tables:
            return False
        matrix = (
            np.ascontiguousarray(np.stack(merged_vectors), dtype=np.float32)
            if merged_vectors
            else np.empty((0, self.dimension), dtype=np.float32)
        )
        try:
            with self._lock:
                self._write_part("values", matrix, merged_metadata)
            return not self.failed_value_tables
        except (OSError, RuntimeError, ValueError, TypeError, sqlite3.DatabaseError) as error:
            LOGGER.warning("Local values index build failed (%s)", type(error).__name__)
            return False

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
            return len(self.schema_meta) if self._part_valid["schema"] else 0

    def count_values(self) -> int:
        with self._lock:
            return len(self.values_meta) if self._part_valid["values"] else 0

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
            self.classification_cache_path.unlink(missing_ok=True)
            self._cache_path.unlink(missing_ok=True)
            self._manifest = None
            self.schema_index = faiss.IndexFlatIP(self.dimension)
            self.schema_meta = []
            self.values_index = faiss.IndexFlatIP(self.dimension)
            self.values_meta = []
            self._part_valid = {"schema": False, "values": False}
            self._part_metadata_valid = {"schema": False, "values": False}
            self.failed_value_tables.clear()
            self._manifest_valid = False
            self._parts_compatible = False
            self._metadata_compatible = False
            self.classification_cache = None
            self._initialize_sqlite(self._cache_path, "embed cache")
            self._ensure_manifest()

    def close(self) -> None:
        """No persistent connection is held; present for lifecycle symmetry."""