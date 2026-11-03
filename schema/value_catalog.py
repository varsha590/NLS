"""Database-independent helpers for discovering bounded distinct text values."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from db.adapter import DatabaseAdapter
from config.settings import Settings

LOGGER = logging.getLogger(__name__)
SMALL_VALUE_LIMIT = 500
CATALOG_FILE = "value_catalog.json"


def _text_columns(engine: Engine) -> list[tuple[str, str, str | None]]:
    """List reflected textual columns as (table, column, schema) tuples."""
    inspector = sa.inspect(engine)
    columns = []
    schema_names = (None,)
    for schema_name in schema_names:
        for table_name in inspector.get_table_names(schema=schema_name):
            try:
                reflected = sa.Table(table_name, sa.MetaData(), schema=schema_name, autoload_with=engine)
            except sa.exc.SQLAlchemyError:
                continue
            for column in reflected.columns:
                if isinstance(column.type, (sa.String, sa.Text, sa.Unicode, sa.UnicodeText)):
                    columns.append((table_name, column.name, schema_name))
    return columns


def _qualified(table: str, column: str, schema: str | None) -> str:
    """Build a stable catalog key, including non-default schemas when present."""
    table_key = f"{schema}.{table}" if schema else table
    return f"{table_key}.{column}"


def classify_value_tiers(
    engine: Engine, small_value_limit: int = SMALL_VALUE_LIMIT
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split discovered text columns by bounded distinct-value cardinality."""
    small: list[str] = []
    large: list[str] = []
    for table_name, column_name, schema_name in _text_columns(engine):
        table = sa.Table(table_name, sa.MetaData(), schema=schema_name, autoload_with=engine)
        column = table.c[column_name]
        statement = sa.select(sa.func.count()).select_from(
            sa.select(column).where(column.is_not(None)).distinct().subquery()
        )
        try:
            with engine.connect() as connection:
                count = int(connection.execute(statement).scalar_one())
        except sa.exc.SQLAlchemyError:
            LOGGER.warning("Could not classify text column", extra={"table": table_name, "column": column_name})
            continue
        target = small if count <= small_value_limit else large
        target.append(_qualified(table_name, column_name, schema_name))
    return tuple(small), tuple(large)


def load_small_values(engine: Engine, columns: tuple[str, ...] | None = None) -> dict[str, list[str]]:
    """Load distinct values for requested columns, or all bounded text columns."""
    if columns is None:
        columns, _ = classify_value_tiers(engine)
    wanted = set(columns)
    catalog: dict[str, list[str]] = {}
    for table_name, column_name, schema_name in _text_columns(engine):
        key = _qualified(table_name, column_name, schema_name)
        if key not in wanted:
            continue
        table = sa.Table(table_name, sa.MetaData(), schema=schema_name, autoload_with=engine)
        statement = (
            sa.select(table.c[column_name])
            .where(table.c[column_name].is_not(None))
            .distinct()
            .order_by(table.c[column_name])
        )
        with engine.connect() as connection:
            values = connection.execute(statement).scalars().all()
        catalog[key] = [str(value) for value in values]
    return catalog


def ensure_trgm_indexes(engine: Engine, columns: tuple[str, ...] | None = None) -> None:
    """Compatibility no-op; large values use adapter-backed portable LIKE search."""
    del engine, columns


def get_catalog_columns(engine: Engine | None = None) -> list[dict[str, str]]:
    """Return discovered text columns; never relies on an application table list."""
    if engine is None:
        return []
    return [
        {"table": _qualified_table(table, schema), "column": column}
        for table, column, schema in _text_columns(engine)
    ]


def _qualified_table(table: str, schema: str | None) -> str:
    return f"{schema}.{table}" if schema else table


def _catalog_path(engine: Engine) -> Path:
    return (
        Path(Settings.from_env().vector_store_path)
        / DatabaseAdapter(engine.url, engine=engine).namespace()
        / CATALOG_FILE
    )


def build_value_catalog(engine: Engine) -> dict[str, list[str]]:
    """Build a local value catalog from all discovered text columns."""
    return load_small_values(engine)


def store_value_catalog(engine: Engine, catalog: dict[str, list[str]]) -> None:
    """Persist a value catalog in the configured database's local namespace."""
    path = _catalog_path(engine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, ensure_ascii=True), encoding="utf-8")


def load_value_catalog(engine: Engine) -> dict[str, list[str]]:
    """Read a local per-database value catalog when available."""
    try:
        payload: Any = json.loads(_catalog_path(engine).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_value_catalog_from_file() -> dict[str, list[str]]:
    """Legacy unscoped catalog loading is disabled to prevent cross-database reuse."""
    return {}


def save_value_catalog_to_file(catalog: dict[str, list[str]]) -> None:
    """Reject unscoped persistence because catalogs must be database-namespaced."""
    del catalog
    raise ValueError("Pass an engine to store_value_catalog so values are namespaced per database.")


def get_value_catalog(engine: Engine | None = None) -> dict[str, list[str]]:
    """Get a namespaced catalog, or an empty mapping without a database engine."""
    return load_value_catalog(engine) if engine is not None else {}


def rebuild_value_catalog(engine: Engine) -> dict[str, list[str]]:
    """Refresh and persist the configured database's local text-value catalog."""
    catalog = build_value_catalog(engine)
    store_value_catalog(engine, catalog)
    return catalog
