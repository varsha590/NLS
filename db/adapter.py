"""SQLAlchemy database boundary for read-only query execution and dialect features."""

from __future__ import annotations

import logging
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from schema.metadata import EXCLUDED_SCHEMA_OBJECTS
from schema.documents import build_table_document, build_column_document, build_relationship_document
from sqlalchemy.engine import Engine, URL, make_url

LOGGER = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when a database connection or operation fails."""

    pass


@dataclass(frozen=True)
class QueryResult:
    """Rows and column names returned by a read-only query."""

    rows: list[dict[str, Any]]
    columns: list[str]


class DatabaseAdapter:
    """Encapsulate database connections, dialect information, and safe execution."""

    def __init__(
        self,
        database_url: str | URL,
        timeout_seconds: int = 15,
        engine: Engine | None = None,
    ) -> None:
        self.url = make_url(database_url) if isinstance(database_url, str) else database_url
        self.engine = engine or sa.create_engine(self.url, pool_pre_ping=True)
        self.timeout_seconds = max(1, timeout_seconds)

    def connect(self) -> Any:
        """Open a SQLAlchemy connection, wrapping errors without exposing credentials."""
        try:
            return self.engine.connect()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Database connection failed", extra={"dialect": self.get_dialect()})
            raise DatabaseUnavailableError(
                f"Could not connect to the configured {self.get_dialect()} database."
            ) from None

    def get_dialect(self) -> str:
        """Return the active SQLAlchemy dialect name."""
        return self.engine.dialect.name

    def get_sqlglot_dialect(self) -> str:
        """Return the matching sqlglot dialect name, using SQLAlchemy's dialect."""
        return {"mssql": "tsql", "postgresql": "postgres"}.get(self.get_dialect(), self.get_dialect())

    def masked_url(self) -> str:
        """Return a display-safe URL with all credentials hidden."""
        return self._credential_free_url().render_as_string(hide_password=True)

    def _credential_free_url(self) -> URL:
        """Remove userinfo and credential-like URL query parameters."""
        safe_query = {
            key: value
            for key, value in self.url.query.items()
            if not any(
                marker in key.casefold()
                for marker in ("password", "passwd", "token", "secret", "api_key", "apikey")
            )
        }
        return self.url.set(username=None, password=None, query=safe_query)

    def ensure_pgvector(self) -> None:
        """Ensure pgvector extension and all embedding tables exist for PostgreSQL.

        Note: Index creation may fail if the connecting user doesn't have sufficient
        privileges; the table structure will still be created correctly.
        """
        if self.get_dialect() != "postgresql":
            return
        connection = self.connect()
        try:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector;")
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_schema_embeddings (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255),
                    metadata_type VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT,
                    embedding VECTOR(384),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    namespace TEXT,
                    CONSTRAINT uq_schema_meta UNIQUE (table_name, column_name, metadata_type, namespace)
                );
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_value_embeddings (
                    id SERIAL PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255),
                    value TEXT NOT NULL,
                    content_hash TEXT,
                    embedding VECTOR(384),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_value_emb UNIQUE (namespace, table_name, column_name, value)
                );
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_examples (
                    id SERIAL PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_example UNIQUE (namespace, question)
                );
                """
            )
            # Attempt HNSW index creation; skip gracefully if user lacks privilege
            try:
                connection.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS idx_system_schema_embeddings_embedding_hnsw
                        ON system_schema_embeddings
                        USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16);
                    """
                )
            except sa.exc.SQLAlchemyError:
                LOGGER.info("HNSW index creation skipped - may need schema privileges")
            try:
                connection.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS idx_system_value_embeddings_embedding_hnsw
                        ON system_value_embeddings
                        USING hnsw (embedding vector_cosine_ops)
                        WITH (m = 16);
                    """
                )
            except sa.exc.SQLAlchemyError:
                LOGGER.info("HNSW index creation skipped - may need schema privileges")
            connection.commit()
        finally:
            connection.close()

    def ensure_pgvalue_vector(self) -> None:
        """Alias for ensure_pgvector (backwards compatibility)."""
        self.ensure_pgvector()

    def namespace(self) -> str:
        """Build a stable local index namespace without retaining URL credentials."""
        import hashlib

        safe_url = self._credential_free_url()
        return hashlib.sha256(safe_url.render_as_string(hide_password=True).encode()).hexdigest()[:20]

    def _set_read_only(self, connection: Any) -> None:
        """Enable available read-only and timeout controls for the active dialect."""
        dialect = self.get_dialect()
        if dialect == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = '{self.timeout_seconds * 1000}ms'"
            )
        elif dialect == "mysql":
            try:
                connection.exec_driver_sql(
                    f"SET SESSION MAX_EXECUTION_TIME={self.timeout_seconds * 1000}"
                )
            except sa.exc.SQLAlchemyError:
                LOGGER.info("MySQL statement timeout unavailable")
        elif dialect == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only=ON")
        elif dialect == "mssql":
            connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")

        raw_connection = getattr(connection.connection, "driver_connection", None)
        if raw_connection is not None and hasattr(raw_connection, "timeout"):
            raw_connection.timeout = self.timeout_seconds

    def run_readonly_query(self, sql: str, max_rows: int = 100) -> QueryResult:
        """Execute a pre-validated query in read-only mode with timeout and fetch bounds."""
        connection = self.connect()
        started = time.monotonic()
        sqlite_raw = None
        try:
            dialect = self.get_dialect()
            if dialect == "mysql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                try:
                    connection.exec_driver_sql(
                        f"SET SESSION MAX_EXECUTION_TIME={self.timeout_seconds * 1000}"
                    )
                except sa.exc.SQLAlchemyError:
                    LOGGER.info("MySQL statement timeout unavailable")
                transaction = connection.get_transaction()
            elif dialect == "sqlite":
                self._set_read_only(connection)
                transaction = connection.get_transaction()
            else:
                transaction = connection.begin()
                self._set_read_only(connection)
            if transaction is None:
                transaction = connection.begin()
            if self.get_dialect() == "sqlite":
                sqlite_raw = connection.connection.driver_connection
                deadline = started + self.timeout_seconds
                sqlite_raw.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            result = connection.execute(sa.text(sql))
            columns = list(result.keys())
            rows = [dict(row) for row in result.mappings().fetchmany(max(0, max_rows))]
            transaction.rollback()
            return QueryResult(rows=rows, columns=columns)
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Read-only query failed", extra={"dialect": self.get_dialect()})
            raise DatabaseUnavailableError(
                f"The {self.get_dialect()} database could not run the query."
            ) from None
        finally:
            if sqlite_raw is not None:
                sqlite_raw.set_progress_handler(None, 0)
                sqlite_raw.execute("PRAGMA query_only=OFF")
            connection.close()

    def explain(self, sql: str) -> str | None:
        """Return an execution plan where the dialect has a safe EXPLAIN form."""
        dialect = self.get_dialect()
        if dialect not in {"postgresql", "mysql", "sqlite", "mariadb"}:
            return None
        connection = self.connect()
        try:
            if dialect == "mysql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                self._set_read_only(connection)
                transaction = connection.get_transaction()
                if transaction is None:
                    transaction = connection.begin()
            else:
                transaction = connection.begin()
                self._set_read_only(connection)
            plan = connection.execute(sa.text(f"EXPLAIN {sql}")).fetchall()
            transaction.rollback()
            return "\n".join(" | ".join(str(value) for value in row) for row in plan)
        except sa.exc.SQLAlchemyError:
            LOGGER.info("EXPLAIN unavailable", extra={"dialect": dialect})
            return None
        finally:
            connection.close()


class EmbeddingStore:
    """Encapsulates all pgvector embedding operations: upsert, search, delete, build."""

    def __init__(self, adapter: DatabaseAdapter, namespace: str | None = None) -> None:
        self.adapter = adapter
        self.namespace = namespace or adapter.namespace()
        if self.adapter.get_dialect() == "postgresql":
            self.adapter.ensure_pgvector()

    def upsert_schema(
        self,
        table_name: str,
        column_name: str | None,
        metadata_type: str,
        content: str,
        content_hash: str,
        embedding: list[float] | None,
    ) -> None:
        """Upsert a schema embedding row.

        When *embedding* is None (unchanged row), the stored vector is preserved
        via a conditional DO UPDATE that only writes the embedding column when
        EXCLUDED.embedding IS NOT NULL.  If the stored vector is already NULL
        (corrupted / missing) and the incoming embedding is also None, this
        method is a no-op for that row — callers must detect and repair such
        rows separately.
        """
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            if embedding is not None:
                # New or changed content: write full row including new embedding.
                stmt = sa.text(
                    """
                    INSERT INTO system_schema_embeddings
                        (table_name, column_name, metadata_type, content, content_hash, embedding, namespace)
                    VALUES
                        (:table_name, :column_name, :metadata_type, :content, :content_hash, :embedding, :namespace)
                    ON CONFLICT (table_name, column_name, metadata_type, namespace)
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP;
                    """
                )
            else:
                # Unchanged content: preserve any existing vector, only refresh
                # the text fields so the row stays current.
                stmt = sa.text(
                    """
                    INSERT INTO system_schema_embeddings
                        (table_name, column_name, metadata_type, content, content_hash, embedding, namespace)
                    VALUES
                        (:table_name, :column_name, :metadata_type, :content, :content_hash, :embedding, :namespace)
                    ON CONFLICT (table_name, column_name, metadata_type, namespace)
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        embedding = COALESCE(system_schema_embeddings.embedding, EXCLUDED.embedding),
                        updated_at = CURRENT_TIMESTAMP;
                    """
                )
            params = {
                "table_name": table_name,
                "column_name": column_name,
                "metadata_type": metadata_type,
                "content": content,
                "content_hash": content_hash,
                "embedding": embedding,
                "namespace": self.namespace,
            }
            connection.execute(stmt, params)
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to upsert schema embedding", extra={"table": table_name, "column": column_name})
            connection.rollback()
        finally:
            connection.close()

    def upsert_value(
        self,
        table_name: str,
        column_name: str | None,
        value: str,
        content_hash: str,
        embedding: list[float] | None,
    ) -> None:
        """Upsert a value embedding row.

        When *embedding* is None (unchanged row), the stored vector is preserved
        via COALESCE so it is never overwritten with NULL.  Raw value text is
        never written to log extras (0f fix).
        """
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            if embedding is not None:
                # New or changed value: write full row including new embedding.
                stmt = sa.text(
                    """
                    INSERT INTO system_value_embeddings
                        (namespace, table_name, column_name, value, content_hash, embedding)
                    VALUES
                        (:namespace, :table_name, :column_name, :value, :content_hash, :embedding)
                    ON CONFLICT (namespace, table_name, column_name, value)
                    DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP;
                    """
                )
            else:
                # Unchanged value: preserve existing vector.
                stmt = sa.text(
                    """
                    INSERT INTO system_value_embeddings
                        (namespace, table_name, column_name, value, content_hash, embedding)
                    VALUES
                        (:namespace, :table_name, :column_name, :value, :content_hash, :embedding)
                    ON CONFLICT (namespace, table_name, column_name, value)
                    DO UPDATE SET
                        content_hash = EXCLUDED.content_hash,
                        embedding = COALESCE(system_value_embeddings.embedding, EXCLUDED.embedding),
                        updated_at = CURRENT_TIMESTAMP;
                    """
                )
            params = {
                "namespace": self.namespace,
                "table_name": table_name,
                "column_name": column_name,
                "value": value,
                "content_hash": content_hash,
                "embedding": embedding,
            }
            connection.execute(stmt, params)
            connection.commit()
        except sa.exc.SQLAlchemyError:
            # Log table/column only — never log the raw value (0f).
            LOGGER.error(
                "Failed to upsert value embedding",
                extra={"table": table_name, "column": column_name},
            )
            connection.rollback()
        finally:
            connection.close()

    def upsert_example(self, question: str, sql: str) -> bool:
        """Upsert a verified example.

        Returns True when the row was persisted successfully, False otherwise.
        Callers must check the return value and not report success to users when
        this returns False (0e fix).
        """
        if self.adapter.get_dialect() != "postgresql":
            return False
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                """
                INSERT INTO system_examples
                    (namespace, question, sql)
                VALUES
                    (:namespace, :question, :sql)
                ON CONFLICT (namespace, question)
                DO UPDATE SET
                    sql = EXCLUDED.sql,
                    updated_at = CURRENT_TIMESTAMP;
                """
            )
            params = {
                "namespace": self.namespace,
                "question": question.strip(),
                "sql": sql.strip(),
            }
            connection.execute(stmt, params)
            connection.commit()
            return True
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to upsert example", extra={"question_len": len(question)})
            connection.rollback()
            return False
        finally:
            connection.close()

    def get_examples(self) -> list[dict[str, str]]:
        """Retrieve all stored examples."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                "SELECT question, sql FROM system_examples WHERE namespace = :namespace;"
            )
            result = connection.execute(stmt, {"namespace": self.namespace})
            return [{"question": row["question"], "sql": row["sql"]} for row in result.mappings()]
        finally:
            connection.close()

    def search_schema(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        metadata_type: str | None = None,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search schema embeddings using cosine similarity."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            where = "WHERE namespace = :namespace AND embedding IS NOT NULL"
            if metadata_type:
                where += " AND metadata_type = :metadata_type"
            stmt = sa.text(
                f"""
                SELECT table_name, column_name, metadata_type, content,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM system_schema_embeddings
                {where}
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
                """
            )
            params = {
                "query_embedding": query_embedding,
                "namespace": ns,
                "top_k": top_k,
            }
            if metadata_type:
                params["metadata_type"] = metadata_type
            result = connection.execute(stmt, params)
            rows = []
            for row in result.mappings():
                rows.append({
                    "table_name": row["table_name"],
                    "column_name": row["column_name"],
                    "metadata_type": row["metadata_type"],
                    "content": row["content"],
                    "similarity": float(row["similarity"]),
                })
            return rows
        finally:
            connection.close()

    def search_values(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search value embeddings using cosine similarity."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                """
                SELECT table_name, column_name, value,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM system_value_embeddings
                WHERE namespace = :namespace
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
                """
            )
            params = {
                "query_embedding": query_embedding,
                "namespace": ns,
                "top_k": top_k,
            }
            result = connection.execute(stmt, params)
            rows = []
            for row in result.mappings():
                rows.append({
                    "table_name": row["table_name"],
                    "column_name": row["column_name"],
                    "value": row["value"],
                    "similarity": float(row["similarity"]),
                })
            return rows
        finally:
            connection.close()

    def get_value_embeddings(self, table_name: str, column_name: str | None) -> dict[str, list[float]]:
        """Retrieve all value embeddings for a given table/column."""
        if self.adapter.get_dialect() != "postgresql":
            return {}
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                """
                SELECT value, embedding
                FROM system_value_embeddings
                WHERE namespace = :namespace
                  AND table_name = :table_name
                  AND (column_name = :column_name OR (:column_name IS NULL AND column_name IS NULL))
                  AND embedding IS NOT NULL
                """
            )
            params = {
                "namespace": self.namespace,
                "table_name": table_name,
                "column_name": column_name,
            }
            result = connection.execute(stmt, params)
            return {row["value"]: row["embedding"] for row in result.mappings()}
        finally:
            connection.close()

    def get_all_value_embeddings(self) -> list[dict[str, Any]]:
        """Retrieve all value embeddings for pruning and null-vector detection."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                """
                SELECT table_name, column_name, value, content_hash,
                       (embedding IS NULL) AS vector_missing
                FROM system_value_embeddings
                WHERE namespace = :namespace
                """
            )
            result = connection.execute(stmt, {"namespace": self.namespace})
            return [
                {
                    "table_name": row["table_name"],
                    "column_name": row["column_name"],
                    "value": row["value"],
                    "content_hash": row["content_hash"],
                    "vector_missing": bool(row["vector_missing"]),
                }
                for row in result.mappings()
            ]
        finally:
            connection.close()

    def get_all_schema_embeddings(self) -> list[dict[str, Any]]:
        """Retrieve all schema embeddings for pruning and null-vector detection."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        connection = self.adapter.connect()
        try:
            stmt = sa.text(
                """
                SELECT table_name, column_name, metadata_type, content_hash,
                       (embedding IS NULL) AS vector_missing
                FROM system_schema_embeddings
                WHERE namespace = :namespace
                """
            )
            result = connection.execute(stmt, {"namespace": self.namespace})
            return [
                {
                    "table_name": row["table_name"],
                    "column_name": row["column_name"],
                    "metadata_type": row["metadata_type"],
                    "content_hash": row["content_hash"],
                    "vector_missing": bool(row["vector_missing"]),
                }
                for row in result.mappings()
            ]
        finally:
            connection.close()

    def prune_schema(self, keep_keys: set[tuple[str, str | None, str]]) -> None:
        """Delete schema embeddings not in the keep set."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            all_rows = self.get_all_schema_embeddings()
            to_delete = [
                (r["table_name"], r["column_name"], r["metadata_type"])
                for r in all_rows
                if (r["table_name"], r["column_name"], r["metadata_type"]) not in keep_keys
            ]
            if not to_delete:
                return
            for table_name, column_name, metadata_type in to_delete:
                stmt = sa.text(
                    """
                    DELETE FROM system_schema_embeddings
                    WHERE namespace = :namespace
                      AND table_name = :table_name
                      AND (column_name = :column_name OR (:column_name IS NULL AND column_name IS NULL))
                      AND metadata_type = :metadata_type
                    """
                )
                connection.execute(
                    stmt,
                    {
                        "namespace": self.namespace,
                        "table_name": table_name,
                        "column_name": column_name,
                        "metadata_type": metadata_type,
                    },
                )
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to prune schema embeddings")
            connection.rollback()
        finally:
            connection.close()

    def prune_values(self, keep_keys: set[tuple[str, str | None, str]]) -> None:
        """Delete value embeddings not in the keep set."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            all_rows = self.get_all_value_embeddings()
            to_delete = [
                (r["table_name"], r["column_name"], r["value"])
                for r in all_rows
                if (r["table_name"], r["column_name"], r["value"]) not in keep_keys
            ]
            if not to_delete:
                return
            for table_name, column_name, value in to_delete:
                stmt = sa.text(
                    """
                    DELETE FROM system_value_embeddings
                    WHERE namespace = :namespace
                      AND table_name = :table_name
                      AND (column_name = :column_name OR (:column_name IS NULL AND column_name IS NULL))
                      AND value = :value
                    """
                )
                connection.execute(
                    stmt,
                    {
                        "namespace": self.namespace,
                        "table_name": table_name,
                        "column_name": column_name,
                        "value": value,
                    },
                )
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to prune value embeddings")
            connection.rollback()
        finally:
            connection.close()

    def count_schema(self, namespace: str | None = None) -> int:
        """Count schema embeddings for a namespace."""
        if self.adapter.get_dialect() != "postgresql":
            return 0
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            result = connection.execute(
                sa.text("SELECT COUNT(*) FROM system_schema_embeddings WHERE namespace = :namespace;"),
                {"namespace": ns},
            )
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            connection.close()

    def count_values(self, namespace: str | None = None) -> int:
        """Count value embeddings for a namespace."""
        if self.adapter.get_dialect() != "postgresql":
            return 0
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            result = connection.execute(
                sa.text("SELECT COUNT(*) FROM system_value_embeddings WHERE namespace = :namespace;"),
                {"namespace": ns},
            )
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            connection.close()

    def build_schema_embeddings(self, metadata: Any, embedder: Any | None = None) -> bool:
        """Build schema embeddings from introspected metadata: table_ddl, column_description, relationship.

        Returns True when indexing completed without errors, False when any error
        occurred (partial index).  Unchanged rows whose vector is intact are
        skipped; rows whose hash matches but whose stored vector is NULL are
        repaired by re-embedding.
        """
        if self.adapter.get_dialect() != "postgresql":
            return True
        if embedder is None:
            from retrieval.embeddings import EmbeddingModel

            embedder = EmbeddingModel("all-MiniLM-L6-v2")

        connection = self.adapter.connect()
        try:
            # Build list of rows to upsert
            rows_to_upsert = []
            for table_info in metadata.tables.values():
                bare_name = table_info.name.rsplit(".", 1)[-1]
                if bare_name.startswith("system_"):
                    continue
                if bare_name in EXCLUDED_SCHEMA_OBJECTS or table_info.name in EXCLUDED_SCHEMA_OBJECTS:
                    continue
                # Keep schema-qualified name for persisted schema key (0c fix)
                table_name = table_info.name

                # table_ddl row
                table_doc = build_table_document(table_info)
                content_hash = hashlib.sha256(table_doc.encode("utf-8")).hexdigest()
                rows_to_upsert.append(
                    {
                        "table_name": table_name,
                        "column_name": None,
                        "metadata_type": "table_ddl",
                        "content": table_doc,
                        "content_hash": content_hash,
                    }
                )

                # column_description rows
                for column_info in table_info.columns:
                    col_doc = build_column_document(table_info, column_info)
                    content_hash = hashlib.sha256(col_doc.encode("utf-8")).hexdigest()
                    rows_to_upsert.append(
                        {
                            "table_name": table_name,
                            "column_name": column_info.name,
                            "metadata_type": "column_description",
                            "content": col_doc,
                            "content_hash": content_hash,
                        }
                    )

                # relationship rows
                for i, relation in enumerate(table_info.foreign_keys):
                    rel_doc = build_relationship_document(table_info, relation)
                    content_hash = hashlib.sha256(rel_doc.encode("utf-8")).hexdigest()
                    # Use FK column as column_name to keep unique
                    fk_col = relation.get("column") or relation.get("local_column") or f"fk_{i}"
                    rows_to_upsert.append(
                        {
                            "table_name": table_name,
                            "column_name": fk_col,
                            "metadata_type": "relationship",
                            "content": rel_doc,
                            "content_hash": content_hash,
                        }
                    )

            # Fetch existing rows: hash and whether their vector is NULL (0a repair).
            existing = self.get_all_schema_embeddings()
            existing_hashes: dict[tuple, str] = {}
            null_vector_keys: set[tuple] = set()
            for r in existing:
                key = (r["table_name"], r["column_name"], r["metadata_type"])
                existing_hashes[key] = r["content_hash"]
                if r.get("vector_missing"):
                    null_vector_keys.add(key)

            # Determine which need embedding:
            # - content changed (hash mismatch), OR
            # - content unchanged but stored vector is NULL (repair path, 0a).
            to_embed = []
            for row in rows_to_upsert:
                key = (row["table_name"], row["column_name"], row["metadata_type"])
                hash_changed = existing_hashes.get(key) != row["content_hash"]
                vector_missing = key in null_vector_keys
                if hash_changed or vector_missing:
                    to_embed.append(row)

            # Batch embed new/changed/repaired rows
            embeddings = []
            if to_embed:
                embeddings = embedder.embed([r["content"] for r in to_embed])

            # Create mapping from key to embedding for rows that need (re-)embedding
            embed_map = {
                (r["table_name"], r["column_name"], r["metadata_type"]): embeddings[i].tolist()
                for i, r in enumerate(to_embed)
            }

            # Upsert all rows; unchanged rows with intact vectors pass embedding=None
            # and upsert_schema uses COALESCE to preserve the stored vector (0a).
            for row in rows_to_upsert:
                key = (row["table_name"], row["column_name"], row["metadata_type"])
                embedding = embed_map.get(key)  # None if unchanged and vector intact
                self.upsert_schema(
                    table_name=row["table_name"],
                    column_name=row["column_name"],
                    metadata_type=row["metadata_type"],
                    content=row["content"],
                    content_hash=row["content_hash"],
                    embedding=embedding,
                )

            # Prune deleted
            keep_keys = {(r["table_name"], r["column_name"], r["metadata_type"]) for r in rows_to_upsert}
            self.prune_schema(keep_keys)

            connection.commit()
            return True
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to build schema embeddings")
            connection.rollback()
            return False
        finally:
            connection.close()

    def build_value_embeddings(self, metadata: Any, embedder: Any | None = None, cardinality_threshold: int = 500) -> bool:
        """Build value embeddings from database distinct values.

        Returns True when indexing completed without errors, False when any error
        occurred (partial index).  Unchanged rows whose vector is intact are
        skipped; rows whose hash matches but whose stored vector is NULL are
        repaired by re-embedding (0a fix).
        """
        if self.adapter.get_dialect() != "postgresql":
            return True
        if embedder is None:
            from retrieval.embeddings import EmbeddingModel

            embedder = EmbeddingModel("all-MiniLM-L6-v2")

        connection = self.adapter.connect()
        try:
            # Gather all values to embed
            rows_to_upsert = []
            for table_info in metadata.tables.values():
                bare_name = table_info.name.rsplit(".", 1)[-1]
                if bare_name.startswith("system_"):
                    continue
                if bare_name in EXCLUDED_SCHEMA_OBJECTS or table_info.name in EXCLUDED_SCHEMA_OBJECTS:
                    continue
                reflected = sa.Table(
                    bare_name,
                    sa.MetaData(),
                    schema=table_info.schema,
                    autoload_with=self.adapter.engine,
                )
                table_key = table_info.name
                for column_info in table_info.columns:
                    column = reflected.c.get(column_info.name)
                    if column is None:
                        continue
                    if not self._is_value_column(column):
                        continue
                    try:
                        with self.adapter.engine.connect() as conn:
                            query = (
                                sa.select(column)
                                .where(column.is_not(None))
                                .distinct()
                                .limit(cardinality_threshold + 1)
                            )
                            raw_values = conn.execute(query).scalars().all()
                    except sa.exc.SQLAlchemyError:
                        continue
                    if len(raw_values) > cardinality_threshold:
                        continue
                    values = [str(v) for v in raw_values if not self._is_schema_value(str(v))]
                    if not values:
                        continue
                    for value in values:
                        content_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                        rows_to_upsert.append(
                            {
                                "table_name": table_key,
                                "column_name": column_info.name,
                                "value": value,
                                "content_hash": content_hash,
                            }
                        )

            # Fetch existing rows: hash and whether their vector is NULL (0a repair).
            existing = self.get_all_value_embeddings()
            existing_hashes: dict[tuple, str] = {}
            null_vector_keys: set[tuple] = set()
            for r in existing:
                key = (r["table_name"], r["column_name"], r["value"])
                existing_hashes[key] = r["content_hash"]
                if r.get("vector_missing"):
                    null_vector_keys.add(key)

            # Determine which need embedding:
            # - content changed (hash mismatch), OR
            # - content unchanged but stored vector is NULL (repair path, 0a).
            to_embed = []
            for row in rows_to_upsert:
                key = (row["table_name"], row["column_name"], row["value"])
                hash_changed = existing_hashes.get(key) != row["content_hash"]
                vector_missing = key in null_vector_keys
                if hash_changed or vector_missing:
                    to_embed.append(row)

            # Batch embed
            embeddings = []
            if to_embed:
                embeddings = embedder.embed([r["value"] for r in to_embed])

            # Create mapping from key to embedding for rows that need (re-)embedding
            embed_map = {
                (r["table_name"], r["column_name"], r["value"]): embeddings[i].tolist()
                for i, r in enumerate(to_embed)
            }

            # Upsert all rows; unchanged rows with intact vectors pass embedding=None
            # and upsert_value uses COALESCE to preserve the stored vector (0a).
            for row in rows_to_upsert:
                key = (row["table_name"], row["column_name"], row["value"])
                embedding = embed_map.get(key)  # None if unchanged and vector intact
                self.upsert_value(
                    table_name=row["table_name"],
                    column_name=row["column_name"],
                    value=row["value"],
                    content_hash=row["content_hash"],
                    embedding=embedding,
                )

            # Prune deleted
            keep_keys = {(r["table_name"], r["column_name"], r["value"]) for r in rows_to_upsert}
            self.prune_values(keep_keys)

            connection.commit()
            return True
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to build value embeddings")
            connection.rollback()
            return False
        finally:
            connection.close()

    @staticmethod
    def _is_value_column(column: Any) -> bool:
        """Check if column is a value column based on data type."""
        type_name = str(column.type).lower()
        return any(marker in type_name for marker in ("char", "text", "string"))

    @staticmethod
    def _is_schema_value(value: str) -> bool:
        """Check if a value is schema vocabulary (table/column names, etc.)."""
        normalized = " ".join(re.findall(r"[\w'-]+", value.casefold()))
        if not normalized:
            return True
        # We don't have schema context here; keep simple filter
        return False