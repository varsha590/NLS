"""Step 4.4 logic: database credentials, read-only connectors, validated execution, and query log.

No Streamlit imports. All DB interaction is via SQLAlchemy read-only boundary.
"""

from __future__ import annotations

import logging
import re
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


def _scrub_credentials(message: str) -> str:
    """Remove password, token, and API key values from error messages."""
    # Match common patterns: password=..., :password@, password:..., --password,
    # also mask any bare secrets that look like passwords
    patterns = [
        r"(?i)(password|passwd|pwd|token|secret|api_key|apikey)\s*[=:]\s*\S+",
        r"(?i):(?:password|passwd|pwd|token|secret|api_key|apikey)=[^\s]+",
    ]
    result = message
    for pattern in patterns:
        result = re.sub(pattern, lambda m: m.group(0).split("=")[0] + "=***", result)

    # Scrub raw URL userinfo passwords (e.g. mysql://user:pass@host:3306/db).
    # Mask the password portion while preserving the host/suffix tail.
    url_userinfo = re.compile(r"(?i)([a-z0-9_.\-]+):(.+)@")
    result = url_userinfo.sub(
        lambda m: m.group(1) + ":***@" + m.group(0)[m.end(2) + 1:],
        result,
    )
    return result


class DbConnectionError(RuntimeError):
    """Raised for database connection failures with scrubbed error messages.

    The original exception message is always sanitized to never contain
    credentials (password, API key, token, secret) or connection strings.
    """

    def __init__(self, message: str, original: BaseException | None = None) -> None:
        self._original = original
        # scrub the message of any password-like strings
        safe = _scrub_credentials(message)
        super().__init__(safe)

    def __str__(self) -> str:
        return self.args[0] if self.args else ""

    def __repr__(self) -> str:
        return f"DbConnectionError({self!r})"


def _credentials_url(credentials: DbCredentials) -> sa.URL:
    """Build a dialect-specific SQLAlchemy URL with an explicit driver.

    mysql -> ``mysql+pymysql://`` (PyMySQL, handles MySQL 8 caching_sha2_password
    via the ``cryptography`` package), postgresql -> ``postgresql+psycopg://``
    (psycopg v3), sqlite -> ``sqlite://``. ``URL.create`` handles special
    characters in credentials safely.
    """
    if credentials.dialect == MY_DIALECT:
        return sa.URL.create(
            drivername="mysql+pymysql",
            username=credentials.username,
            password=credentials.password,
            host=credentials.host,
            port=credentials.port,
            database=credentials.database,
        )
    if credentials.dialect == PG_DIALECT:
        return sa.URL.create(
            drivername="postgresql+psycopg",
            username=credentials.username,
            password=credentials.password,
            host=credentials.host,
            port=credentials.port,
            database=credentials.database,
        )
    if credentials.dialect == SG_DIALECT:
        return sa.URL.create(
            drivername=SG_DIALECT,
            database=credentials.database,
        )
    raise ValueError(f"Unsupported dialect: {credentials.dialect}")


def _connect_with_credentials(
    credentials: DbCredentials, timeout_seconds: int = 15
) -> sa.engine.Connection:
    """Build a SQLAlchemy engine and return a read-only connection."""

    if credentials.dialect == SG_DIALECT and credentials.database != ":memory:":
        database = credentials.database
        if not database.startswith("file:"):
            database = f"file:{database}"
        url = sa.URL.create(
            drivername=SG_DIALECT,
            database=database,
            query={"mode": "ro", "uri": "true"},
        )
    else:
        url = _credentials_url(credentials)
    engine: sa.Engine = sa.create_engine(url, pool_pre_ping=True)

    connection = engine.connect()

    if credentials.dialect == PG_DIALECT:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = '{max(1, timeout_seconds) * 1000}ms'"
        )
    elif credentials.dialect == MY_DIALECT:
        connection.exec_driver_sql(
            f"SET SESSION MAX_EXECUTION_TIME={max(1, timeout_seconds) * 1000}"
        )
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    elif credentials.dialect == SG_DIALECT:
        connection.exec_driver_sql("PRAGMA query_only=ON")
        raw_connection = connection.connection.driver_connection
        deadline = time.monotonic() + max(1, timeout_seconds)
        raw_connection.set_progress_handler(
            lambda: int(time.monotonic() >= deadline), 1000
        )

    return connection


def test_connection(
    credentials: DbCredentials, timeout_seconds: int = 15
) -> None:
    """Verify a read-only database connection without retaining its resources."""
    connection: sa.engine.Connection | None = None
    try:
        connection = _connect_with_credentials(credentials, timeout_seconds)
        connection.exec_driver_sql("SELECT 1")
    except Exception as error:
        raise DbConnectionError(
            "The connection could not be verified. Check the connection details."
        ) from error
    finally:
        if connection is not None:
            connection.close()


def execute_validated(
    sql: str,
    credentials: DbCredentials,
    stored_dialect: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Execute a validated SQL query against the credentials' database.

    If ``stored_dialect`` is provided, the credentials' dialect must match,
    otherwise a DbConnectionError is raised that never contains the password.

    Fetches ALL rows once (no limit). Returns a dict with:
    - ``columns``: list of column names
    - ``rows``: list of row dicts
    - ``row_count``: total number of rows returned
    - ``duration_ms``: query execution duration in milliseconds

    If ``rows`` is empty, the caller should display "No matching records found".
    The SQL connection is closed after execution.
    """

    if stored_dialect is not None and credentials.dialect != stored_dialect:
        raise DbConnectionError(
            f"Credentials dialect '{credentials.dialect}' does not match "
            f"stored dataset dialect '{stored_dialect}'. "
            "Please provide credentials matching the dataset's dialect."
        )

    started = time.monotonic()
    connection = _connect_with_credentials(credentials, timeout_seconds)
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


def log_query(
    tenant_id: str,
    dataset_id: str,
    sql: str,
    row_count: int,
    duration_ms: int,
    logger: logging.Logger | None = None,
) -> None:
    """Log a executed query with masked literals and no credentials.

    The SQL is processed via sqlglot to replace ALL literals (strings, numbers,
    booleans, dates, IN-lists) with "?" placeholders. Credentials or row data
    are never included.

    Args:
        tenant_id: The tenant identifier.
        dataset_id: The dataset identifier.
        sql: The SQL that was executed.
        row_count: Number of rows returned.
        duration_ms: Execution duration in milliseconds.
        logger: Optional logger; defaults to ``logging.getLogger(__name__)``.
    """
    import sqlglot
    from sqlglot import exp

    log = logger or logging.getLogger(__name__)

    # Replace ALL literals with "?" placeholders using sqlglot AST
    try:
        parsed = sqlglot.parse_one(sql)
        for node in parsed.walk():
            if isinstance(node, exp.Literal):
                node.set("this", "?")
            elif isinstance(node, exp.In):
                for expr in node.expressions:
                    if isinstance(expr, exp.Literal):
                        expr.set("this", "?")
        masked_sql = parsed.sql()
    except Exception:
        masked_sql = "[omitted: unable to safely mask SQL literals]"

    log.info(
        "query_log | tenant=%s | dataset=%s | row_count=%d | duration_ms=%d | sql=%s",
        tenant_id,
        dataset_id,
        row_count,
        duration_ms,
        masked_sql,
    )


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