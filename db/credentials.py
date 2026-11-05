"""Step 4.4 logic: database credentials, read-only connectors, validated execution, and query log.

No Streamlit imports. All DB interaction is via SQLAlchemy read-only boundary.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import make_url, Engine

PG_DIALECT = "postgresql"
MY_DIALECT = "mysql"
SG_DIALECT = "sqlite"


@dataclass(frozen=True)
class DbCredentials:
    """Database connection credentials with password masking.

    The ``password`` field is never stored in logs or session state.
    ``str()`` and ``repr()`` scrub the password so it never leaks.
    """

    dialect: str
    host: str
    port: int | None
    username: str
    password: str
    database: str

    def _mask(self) -> DbCredentials:
        return DbCredentials(
            dialect=self.dialect,
            host=self.host,
            port=self.port,
            username=self.username,
            password="",
            database=self.database,
        )

    def __str__(self) -> str:
        return (
            f"{self.dialect}+psycopg://{self.username}:{self.password}"
            f"@{self.host}:{self.port or ''}/{self.database}"
            if self.dialect == PG_DIALECT
            else (
                f"{self.dialect}+pymysql://{self.username}:{self.password}"
                f"@{self.host}:{self.port or ''}/{self.database}"
                if self.dialect == MY_DIALECT
                else (
                    f"{self.dialect}:///{self.database}"
                    if self.dialect == SG_DIALECT
                    else f"{self.dialect}://..."
                )
            )
        ).replace(f":{self.password}@", "***@")

    def __repr__(self) -> str:
        return (
            f"DbCredentials(dialect={self.dialect!r}, host={self.host!r}, "
            f"port={self.port!r}, username={self.username!r}, "
            f"password='***', database={self.database!r})"
        )

    def masked_url(self) -> str:
        """Return a display-safe URL with password replaced by ***."""
        return self.__str__()


def _postgresql_set_read_only(connection: sa.engine.Connection) -> None:
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    connection.exec_driver_sql(
        f"SET LOCAL statement_timeout = '{(15) * 1000}ms'"
    )


def _mysql_set_read_only(connection: sa.engine.Connection) -> None:
    connection.exec_driver_sql("SET SESSION MAX_EXECUTION_TIME={}").format(
        15 * 1000
    )
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")


def _sqlite_set_read_only(connection: sa.engine.Connection) -> None:
    connection.exec_driver_sql("PRAGMA query_only=ON")


def _connect_with_credentials(credentials: DbCredentials) -> sa.engine.Connection:
    """Build a SQLAlchemy engine and return a read-only connection."""

    if credentials.dialect == PG_DIALECT:
        url = make_url(
            f"{credentials.dialect}://{credentials.username}:{credentials.password}"
            f"@{credentials.host}:{credentials.port or ''}/{credentials.database}"
        )
        engine: Engine = sa.create_engine(url, pool_pre_ping=True)
    elif credentials.dialect == MY_DIALECT:
        url = make_url(
            f"{credentials.dialect}://{credentials.username}:{credentials.password}"
            f"@{credentials.host}:{credentials.port or ''}/{credentials.database}"
        )
        engine: Engine = sa.create_engine(url, pool_pre_ping=True)
    elif credentials.dialect == SG_DIALECT:
        url = sa.URL.create(
            drivername=SG_DIALECT,
            database=credentials.database,
        )
        engine: Engine = sa.create_engine(url, pool_pre_ping=True)
    else:
        raise ValueError(f"Unsupported dialect: {credentials.dialect}")

    connection = engine.connect()

    if credentials.dialect == PG_DIALECT:
        _postgresql_set_read_only(connection)
    elif credentials.dialect == MY_DIALECT:
        _mysql_set_read_only(connection)
    elif credentials.dialect == SG_DIALECT:
        _sqlite_set_read_only(connection)

    return connection


def execute_validated(
    sql: str,
    credentials: DbCredentials,
) -> dict[str, Any]:
    """Execute a validated SQL query against the credentials' database.

    Fetches ALL rows once (no limit). Returns a dict with:
    - ``columns``: list of column names
    - ``rows``: list of row dicts
    - ``row_count``: total number of rows returned
    - ``duration_ms``: query execution duration in milliseconds

    If ``rows`` is empty, the caller should display "No matching records found".
    The SQL connection is closed after execution.

    The SQL literals are NOT replaced in the returned result – the caller may
    log the SQL with literals masked via the AST if desired.
    """

    started = time.monotonic()
    connection = _connect_with_credentials(credentials)
    try:
        result = connection.execute(sa.text(sql))
        columns = list(result.keys())
        rows = [dict(row) for row in result.mappings().fetchall()]
        row_count = len(rows)
        duration_ms = int((time.monotonic() - started) * 1000)
    finally:
        try:
            connection.close()
        except Exception:
            pass

    return {
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "duration_ms": duration_ms,
    }


def page_rows(
    rows: list[dict[str, Any]],
    page: int,
    page_size: int = 50,
) -> list[dict[str, Any]]:
    """Return the slice of ``rows`` for the given ``page`` (1-indexed).

    ``page_size`` defaults to 50 with a hard maximum of 500 very large results
    keep memory usage bounded in the UI.
    """

    effective_size = min(max(page_size, 1), 500)
    start = (page - 1) * effective_size
    end = start + effective_size
    return rows[start:end]