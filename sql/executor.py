"""Compatibility SQL execution API delegated to the database adapter."""

from typing import List, Tuple

import sqlalchemy as sa

from db.adapter import DatabaseAdapter, DatabaseUnavailableError


class SQLError(Exception):
    """Backward-compatible execution exception."""


def execute_sql(
    sql: str,
    engine: sa.Engine,
    max_rows: int = 1000,
) -> Tuple[List[dict], List[str]]:
    """Execute a validated SQL statement through the configured dialect.

    Uses a read-only database connection. Executes the query and returns
    the results as a list of dicts with column names.

    Args:
        sql: The validated SQL statement to execute.
        engine: SQLAlchemy engine connected to the database (read-only user).
        max_rows: Maximum number of rows to fetch.

    Returns:
        Tuple of (rows as list of dicts, column names list).

    Raises:
        SQLError: If execution fails.
    """
    try:
        result = DatabaseAdapter(engine.url, engine=engine).run_readonly_query(sql, max_rows)
        return result.rows, result.columns
    except DatabaseUnavailableError as error:
        raise SQLError(str(error)) from error