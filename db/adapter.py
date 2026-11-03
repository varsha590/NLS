"""SQLAlchemy database boundary for read-only query execution and dialect features."""

from __future__ import annotations

import logging
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.dialects.postgresql import insert

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
        """Ensure pgvector extension and system_schema_embeddings table exist for PostgreSQL.
        
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
        finally:
            connection.close()

    def ensure_pgvalue_vector(self) -> None:
        """Ensure system_value_embeddings table and HNSW index exist for PostgreSQL.
        
        Note: Index creation may fail if the connecting user doesn't have sufficient
        privileges; the table structure will still be created correctly.
        """
        if self.get_dialect() != "postgresql":
            return
        connection = self.connect()
        try:
            connection.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_value_embeddings (
                    id SERIAL PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    column_name VARCHAR(255),
                    value TEXT NOT NULL,
                    embedding VECTOR(384),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_value_emb UNIQUE (namespace, table_name, column_name, value)
                );
                """
            )
            # Attempt HNSW index creation; skip gracefully if user lacks privilege
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
        finally:
            connection.close()

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
            rows = [dict(row) for row in result.mappings().fetchmax(max_rows)]
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
    """Encapsulates all pgvector embedding operations: upsert, search, delete missing."""

    def __init__(self, adapter: DatabaseAdapter, namespace: str | None = None) -> None:
        self.adapter = adapter
        self.namespace = namespace or adapter.namespace()
        if self.adapter.get_dialect() == "postgresql":
            self.adapter.ensure_pgvector()
            self.adapter.ensure_pgvalue_vector()

    def _upsert_schema(
        self,
        table_name: str,
        column_name: str | None,
        metadata_type: str,
        content: str,
        embedding: list[float] | None,
        content_hash: str,
    ) -> None:
        """Upsert a schema embedding row."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            stmt = sa.text("""
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
            """)
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

    def _upsert_value(
        self,
        namespace: str,
        table_name: str,
        column_name: str | None,
        value: str,
        embedding: list[float] | None,
    ) -> None:
        """Upsert a value embedding row."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            stmt = sa.text("""
                INSERT INTO system_value_embeddings
                    (namespace, table_name, column_name, value, embedding)
                VALUES
                    (:namespace, :table_name, :column_name, :value, :embedding)
                ON CONFLICT (namespace, table_name, column_name, value)
                DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP;
            """)
            params = {
                "namespace": namespace,
                "table_name": table_name,
                "column_name": column_name,
                "value": value,
                "embedding": embedding,
            }
            connection.execute(stmt, params)
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to upsert value embedding", extra={"table": table_name, "column": column_name, "value": value})
            connection.rollback()
        finally:
            connection.close()

    def search_schema(
        self, query_embedding: list[float], top_k: int = 10, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Search schema embeddings using cosine similarity."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            stmt = sa.text("""
                SELECT table_name, column_name, metadata_type, content,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM system_schema_embeddings
                WHERE namespace = :namespace
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
            """)
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
                    "metadata_type": row["metadata_type"],
                    "content": row["content"],
                    "similarity": float(row["similarity"]),
                })
            return rows
        finally:
            connection.close()

    def search_values(
        self, query_embedding: list[float], top_k: int = 10, namespace: str | None = None
    ) -> list[dict[str, Any]]:
        """Search value embeddings using cosine similarity."""
        if self.adapter.get_dialect() != "postgresql":
            return []
        ns = namespace or self.namespace
        connection = self.adapter.connect()
        try:
            stmt = sa.text("""
                SELECT table_name, column_name, value,
                       1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity
                FROM system_value_embeddings
                WHERE namespace = :namespace
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :top_k
            """)
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

    def delete_missing(
        self, current_table_names: set[str], current_column_names: set[str]
    ) -> None:
        """Delete embedding rows for tables/columns that no longer exist."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            # Delete schema embeddings for tables no longer present
            if current_table_names:
                placeholders = ", ".join(f"'{t}'" for t in current_table_names)
                connection.exec_driver_sql(
                    f"DELETE FROM system_schema_embeddings WHERE table_name NOT IN ({placeholders});"
                )
            # Delete value embeddings for tables/columns no longer present
            # This is a simple cleanup; full reconciliation would need table-aware deletion
            connection.exec_driver_sql(
                "DELETE FROM system_value_embeddings WHERE table_name NOT IN (SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE');"
            )
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to delete missing embedding rows")
            connection.rollback()
        finally:
            connection.close()

    def build_schema_embeddings(self, metadata: Any) -> None:
        """Build schema embeddings from introspected metadata."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            for table_info in metadata.tables.values():
                table_name = table_info.name.rsplit(".", 1)[-1]
                for column_info in table_info.columns:
                    column_name = column_info.name
                    metadata_type = "column_description"
                    content = f"{column_info.name} {column_info.data_type} {column_info.comment or ''}"
                    # Compute content hash
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    # Check if already up to date
                    existing = connection.exec_driver_sql(
                        "SELECT content_hash FROM system_schema_embeddings WHERE table_name = %s AND column_name = %s AND metadata_type = %s AND namespace = %s;",
                        (table_name, column_name, metadata_type, self.namespace),
                    ).fetchone()
                    if existing and existing[0] == content_hash:
                        continue  # No change, skip
                    # Get embedding
                    embedding = None
                    try:
                        from retrieval.embeddings import EmbeddingModel
                        model = EmbeddingModel("all-MiniLM-L6-v2")
                        embedding = model.embed([content])[0].tolist()
                    except Exception:
                        LOGGER.debug("Embedding generation failed for column", extra={"table": table_name, "column": column_name})
                    self._upsert_schema(
                        table_name=table_name,
                        column_name=column_name,
                        metadata_type=metadata_type,
                        content=content,
                        embedding=embedding,
                        content_hash=content_hash,
                    )
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to build schema embeddings")
            connection.rollback()
        finally:
            connection.close()

    def build_value_embeddings(self, metadata: Any, cardinality_threshold: int = 500) -> None:
        """Build value embeddings from database distinct values."""
        if self.adapter.get_dialect() != "postgresql":
            return
        from retrieval.embeddings import EmbeddingModel
        model = EmbeddingModel("all-MiniLM-L6-v2")
        connection = self.adapter.connect()
        try:
            for table_info in metadata.tables.values():
                table_name = table_info.name.rsplit(".", 1)[-1]
                reflected = sa.Table(
                    table_name,
                    sa.MetaData(),
                    schema=table_info.schema,
                    autoload_with=self.adapter.engine,
                )
                for column_info in table_info.columns:
                    column = reflected.c.get(column_info.name)
                    if column is None:
                        continue
                    key = f"{table_info.name}.{column_info.name}"
                    # Check if value column
                    if not self._is_value_column(reflected, column):
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
                        if len(raw_values) > cardinality_threshold:
                            continue
                        values = [str(v) for v in raw_values if not self._is_schema_value(str(v))]
                        if not values:
                            continue
                        for value in values:
                            value_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                            # Check if already up to date
                            existing = connection.exec_driver_sql(
                                "SELECT content_hash FROM system_value_embeddings WHERE namespace = %s AND table_name = %s AND column_name = %s AND value = %s;",
                                (self.namespace, table_name, column_info.name, value),
                            ).fetchone()
                            if existing and existing[0] == value_hash:
                                continue  # No change, skip
                            embedding = model.embed([value])[0].tolist()
                            self._upsert_value(
                                namespace=self.namespace,
                                table_name=table_name,
                                column_name=column_info.name,
                                value=value,
                                embedding=embedding,
                            )
                    except (sa.exc.SQLAlchemyError, KeyError):
                        LOGGER.debug("Value embedding skipped for column", extra={"table": table_name, "column": column_info.name})
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to build value embeddings")
            connection.rollback()
        finally:
            connection.close()

    def refresh_schema_embeddings(self, metadata: Any) -> None:
        """Refresh schema embeddings - only update changed rows."""
        if self.adapter.get_dialect() != "postgresql":
            return
        connection = self.adapter.connect()
        try:
            for table_info in metadata.tables.values():
                table_name = table_info.name.rsplit(".", 1)[-1]
                for column_info in table_info.columns:
                    column_name = column_info.name
                    metadata_type = "column_description"
                    content = f"{column_info.name} {column_info.data_type} {column_info.comment or ''}"
                    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    existing = connection.exec_driver_sql(
                        "SELECT content_hash FROM system_schema_embeddings WHERE table_name = %s AND column_name = %s AND metadata_type = %s AND namespace = %s;",
                        (table_name, column_name, metadata_type, self.namespace),
                    ).fetchone()
                    if existing and existing[0] == content_hash:
                        continue  # No change, skip
                    embedding = None
                    try:
                        from retrieval.embeddings import EmbeddingModel
                        model = EmbeddingModel("all-MiniLM-L6-v2")
                        embedding = model.embed([content])[0].tolist()
                    except Exception:
                        LOGGER.debug("Embedding generation failed for column during refresh", extra={"table": table_name, "column": column_name})
                    self._upsert_schema(
                        table_name=table_name,
                        column_name=column_name,
                        metadata_type=metadata_type,
                        content=content,
                        embedding=embedding,
                        content_hash=content_hash,
                    )
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to refresh schema embeddings")
            connection.rollback()
        finally:
            connection.close()

    def refresh_value_embeddings(self, metadata: Any, cardinality_threshold: int = 500) -> None:
        """Refresh value embeddings - only update changed rows."""
        if self.adapter.get_dialect() != "postgresql":
            return
        from retrieval.embeddings import EmbeddingModel
        model = EmbeddingModel("all-MiniLM-L6-v2")
        connection = self.adapter.connect()
        try:
            for table_info in metadata.tables.values():
                table_name = table_info.name.rsplit(".", 1)[-1]
                reflected = sa.Table(
                    table_name,
                    sa.MetaData(),
                    schema=table_info.schema,
                    autoload_with=self.adapter.engine,
                )
                for column_info in table_info.columns:
                    column = reflected.c.get(column_info.name)
                    if column is None:
                        continue
                    key = f"{table_info.name}.{column_info.name}"
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
                        if len(raw_values) > cardinality_threshold:
                            continue
                        values = [str(v) for v in raw_values if not self._is_schema_value(str(v))]
                        if not values:
                            continue
                        for value in values:
                            value_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                            existing = connection.exec_driver_sql(
                                "SELECT content_hash FROM system_value_embeddings WHERE namespace = %s AND table_name = %s AND column_name = %s AND value = %s;",
                                (self.namespace, table_name, column_info.name, value),
                            ).fetchone()
                            if existing and existing[0] == value_hash:
                                continue  # No change, skip
                            embedding = model.embed([value])[0].tolist()
                            self._upsert_value(
                                namespace=self.namespace,
                                table_name=table_name,
                                column_name=column_info.name,
                                value=value,
                                embedding=embedding,
                            )
                    except (sa.exc.SQLAlchemyError, KeyError):
                        LOGGER.debug("Value embedding skipped during refresh", extra={"table": table_name, "column": column_info.name})
            connection.commit()
        except sa.exc.SQLAlchemyError:
            LOGGER.error("Failed to refresh value embeddings")
            connection.rollback()
        finally:
            connection.close()

    @staticmethod
    def _is_value_column(column: Any) -> bool:
        """Check if column is a value column based on data type."""
        type_name = str(column.type).lower()
        # Value columns are typically text, string, or character types
        return any(marker in type_name for marker in ("char", "text", "string"))