"""SQLAlchemy database boundary for read-only query execution and dialect helpers."""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import sqlalchemy as sa
from sqlalchemy.engine import Engine, URL, make_url

LOGGER = logging.getLogger(__name__)


class DatabaseUnavailableError(RuntimeError):
    """Raised when a database connection or operation fails."""


@dataclass(frozen=True)
class QueryResult:
    """Rows and column names returned by a read-only query."""

    rows: list[dict[str, Any]]
    columns: list[str]


class DatabaseAdapter:
    """Connect to the target database without creating or mutating database objects."""

    def __init__(
        self,
        database_url: str | URL,
        timeout_seconds: int = 15,
        engine: Engine | None = None,
    ) -> None:
        self.url = make_url(database_url) if isinstance(database_url, str) else database_url
        self.engine = engine or sa.create_engine(self.url, pool_pre_ping=True)
        self.timeout_seconds = max(1, timeout_seconds)
        self.call_counts = {
            "value_lookup_db_calls": 0,
            "explain_db_calls": 0,
            "execution_db_calls": 0,
        }

    def reset_call_counts(self) -> None:
        """Reset per-question target database operation counters."""
        for key in self.call_counts:
            self.call_counts[key] = 0

    def connect(self) -> Any:
        """Open a connection, wrapping errors without exposing credentials."""
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
        """Return the matching SQLGlot dialect name."""
        return {"mssql": "tsql", "postgresql": "postgres"}.get(
            self.get_dialect(), self.get_dialect()
        )

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

    def masked_url(self) -> str:
        """Return a display-safe URL with all credentials hidden."""
        return self._credential_free_url().render_as_string(hide_password=True)

    def namespace(self) -> str:
        """Build a stable local index namespace from a credential-free URL."""
        safe_url = self._credential_free_url().render_as_string(hide_password=True)
        return hashlib.sha256(safe_url.encode("utf-8")).hexdigest()[:20]

    def _set_read_only(self, connection: Any) -> None:
        """Enable supported read-only and timeout session controls."""
        dialect = self.get_dialect()
        if dialect == "postgresql":
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET LOCAL statement_timeout = '{self.timeout_seconds * 1000}ms'"
            )
        elif dialect == "mysql":
            connection.exec_driver_sql(
                f"SET SESSION MAX_EXECUTION_TIME={self.timeout_seconds * 1000}"
            )
        elif dialect == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only=ON")

        raw_connection = getattr(connection.connection, "driver_connection", None)
        if raw_connection is not None and hasattr(raw_connection, "timeout"):
            raw_connection.timeout = self.timeout_seconds

    @contextmanager
    def readonly_connection(self) -> Iterator[Any]:
        """Yield a read-only transaction with dialect session controls applied."""
        connection = self.connect()
        transaction = None
        sqlite_raw = None
        try:
            dialect = self.get_dialect()
            if dialect == "mysql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                self._set_read_only(connection)
                transaction = connection.get_transaction() or connection.begin()
            elif dialect == "sqlite":
                self._set_read_only(connection)
                transaction = connection.get_transaction() or connection.begin()
                sqlite_raw = connection.connection.driver_connection
            else:
                transaction = connection.begin()
                self._set_read_only(connection)
            yield connection
        finally:
            if transaction is not None and transaction.is_active:
                transaction.rollback()
            if sqlite_raw is not None:
                sqlite_raw.execute("PRAGMA query_only=OFF")
            connection.close()

    def run_readonly_query(self, sql: str) -> QueryResult:
        """Execute pre-validated SQL using supported read-only settings and no row bound."""
        self.call_counts["execution_db_calls"] += 1
        connection = self.connect()
        started = time.monotonic()
        sqlite_raw = None
        try:
            dialect = self.get_dialect()
            if dialect == "mysql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                try:
                    self._set_read_only(connection)
                except sa.exc.SQLAlchemyError:
                    LOGGER.info("MySQL timeout setting unavailable")
                transaction = connection.get_transaction()
            elif dialect == "sqlite":
                self._set_read_only(connection)
                transaction = connection.get_transaction()
            else:
                transaction = connection.begin()
                self._set_read_only(connection)
            if transaction is None:
                transaction = connection.begin()
            if dialect == "sqlite":
                sqlite_raw = connection.connection.driver_connection
                deadline = started + self.timeout_seconds
                sqlite_raw.set_progress_handler(
                    lambda: int(time.monotonic() > deadline), 1000
                )
            result = connection.execute(sa.text(sql))
            columns = list(result.keys())
            rows = [dict(row) for row in result.mappings().fetchmany()]
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
        """Return an execution plan using a read-only transaction where supported."""
        self.call_counts["explain_db_calls"] += 1
        dialect = self.get_dialect()
        if dialect not in {"postgresql", "mysql", "sqlite", "mariadb"}:
            return None
        connection = self.connect()
        try:
            if dialect == "mysql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                try:
                    self._set_read_only(connection)
                except sa.exc.SQLAlchemyError:
                    LOGGER.info("MySQL timeout setting unavailable")
                transaction = connection.get_transaction()
                if transaction is None:
                    transaction = connection.begin()
            elif dialect == "sqlite":
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

    def distinct_text_values(self, table_info: Any, column_name: str, limit: int) -> list[str]:
        """Fetch at most ``limit`` distinct non-null strings under read-only controls."""
        columns = {column.name for column in table_info.columns}
        if column_name not in columns:
            return []
        table_name = table_info.name.rsplit(".", 1)[-1]
        table = sa.table(
            table_name,
            *(sa.column(column.name, sa.String()) for column in table_info.columns),
            schema=table_info.schema,
        )
        column = table.c[column_name]
        statement = (
            sa.select(column)
            .where(column.is_not(None))
            .distinct()
            .limit(max(1, int(limit)))
        )
        self.call_counts["value_lookup_db_calls"] += 1
        try:
            with self.readonly_connection() as connection:
                return [str(row[0]) for row in connection.execute(statement).fetchall()]
        except sa.exc.SQLAlchemyError:
            raise DatabaseUnavailableError(
                "A bounded value lookup could not be completed."
            ) from None

    def lookup_text_candidates(
        self,
        table_info: Any,
        column_name: str,
        text: str,
        limit: int,
    ) -> list[str]:
        """Use a parameterized, escaped case-insensitive LIKE lookup with a hard row cap."""
        columns = {column.name for column in table_info.columns}
        if column_name not in columns:
            return []
        table_name = table_info.name.rsplit(".", 1)[-1]
        table = sa.table(
            table_name,
            *(sa.column(column.name, sa.String()) for column in table_info.columns),
            schema=table_info.schema,
        )
        column = table.c[column_name]
        escaped_text = text.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_text}%"
        exact_order = sa.case(
            (sa.func.lower(column) == sa.func.lower(sa.bindparam("exact_text")), 0),
            else_=1,
        )
        statement = (
            sa.select(column)
            .where(sa.func.lower(column).like(sa.bindparam("pattern"), escape="\\"))
            .group_by(column)
            .order_by(exact_order)
            .limit(max(1, int(limit)))
        )
        self.call_counts["value_lookup_db_calls"] += 1
        try:
            with self.readonly_connection() as connection:
                rows = connection.execute(
                    statement,
                    {"pattern": pattern, "exact_text": text},
                ).fetchall()
                return [str(row[0]) for row in rows]
        except sa.exc.SQLAlchemyError:
            raise DatabaseUnavailableError(
                "A bounded value lookup could not be completed."
            ) from None