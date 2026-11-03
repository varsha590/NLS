"""Build normalized schema metadata from SQLAlchemy inspection."""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from catalog.classifier import parse_enum_options
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo, is_internal_table_name

LOGGER = logging.getLogger(__name__)


def _qualified_name(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def _bulk_metadata(inspector: Any, method_name: str, schema: str | None) -> dict[Any, Any] | None:
    method = getattr(inspector, method_name, None)
    if method is None:
        return None
    try:
        result = method(schema=schema)
        return result if isinstance(result, dict) else None
    except (AttributeError, NotImplementedError, sa.exc.SQLAlchemyError):
        return None


def _table_metadata(
    mapping: dict[Any, Any] | None, schema: str | None, table_name: str
) -> Any:
    if mapping is None:
        return None
    for key in ((schema, table_name), (None, table_name), table_name):
        if key in mapping:
            return mapping[key]
    return None


def introspect_catalog(
    engine: Engine,
    allowed_schemas: tuple[str, ...] = (),
    excluded_tables: tuple[str, ...] = (),
) -> SchemaMetadata:
    """Inspect schema metadata in bulk where supported; never read table rows."""
    inspector = inspect(engine)
    schema_names: tuple[str | None, ...] = allowed_schemas or (None,)
    excluded = set(excluded_tables)
    tables: dict[str, TableInfo] = {}

    for schema_name in schema_names:
        try:
            table_names = inspector.get_table_names(schema=schema_name)
        except (sa.exc.SQLAlchemyError, NotImplementedError):
            LOGGER.warning("Schema enumeration skipped", extra={"schema": schema_name})
            continue
        bulk_columns = _bulk_metadata(inspector, "get_multi_columns", schema_name)
        bulk_primary_keys = _bulk_metadata(inspector, "get_multi_pk_constraint", schema_name)
        bulk_foreign_keys = _bulk_metadata(inspector, "get_multi_foreign_keys", schema_name)
        bulk_unique_constraints = _bulk_metadata(
            inspector, "get_multi_unique_constraints", schema_name
        )
        bulk_table_comments = _bulk_metadata(inspector, "get_multi_table_comment", schema_name)
        for raw_table_name in table_names:
            table_name = _qualified_name(schema_name, raw_table_name)
            if (
                is_internal_table_name(table_name)
                or is_internal_table_name(raw_table_name)
                or table_name in excluded
                or raw_table_name in excluded
            ):
                continue
            try:
                columns = _table_metadata(bulk_columns, schema_name, raw_table_name)
                if columns is None:
                    columns = inspector.get_columns(raw_table_name, schema=schema_name)
                primary_keys = _table_metadata(bulk_primary_keys, schema_name, raw_table_name)
                if primary_keys is None:
                    primary_keys = inspector.get_pk_constraint(raw_table_name, schema=schema_name)
                primary_key_names = primary_keys.get("constrained_columns") or []
                foreign_keys = _table_metadata(bulk_foreign_keys, schema_name, raw_table_name)
                if foreign_keys is None:
                    foreign_keys = inspector.get_foreign_keys(raw_table_name, schema=schema_name)
                unique_constraints = _table_metadata(
                    bulk_unique_constraints, schema_name, raw_table_name
                )
                if unique_constraints is None:
                    try:
                        unique_constraints = inspector.get_unique_constraints(
                            raw_table_name, schema=schema_name
                        )
                    except (NotImplementedError, sa.exc.SQLAlchemyError):
                        unique_constraints = []
                table_comment_data = _table_metadata(
                    bulk_table_comments, schema_name, raw_table_name
                )
                if table_comment_data is None:
                    try:
                        table_comment_data = inspector.get_table_comment(
                            raw_table_name, schema=schema_name
                        )
                    except (AttributeError, NotImplementedError, sa.exc.SQLAlchemyError):
                        table_comment_data = {}
                table_comment = (table_comment_data or {}).get("text")
                column_infos = []
                for column_data in columns:
                    column_name = column_data["name"]
                    matching_foreign_key = next(
                        (
                            (foreign_key, index)
                            for foreign_key in foreign_keys
                            for index, local_name in enumerate(foreign_key.get("constrained_columns") or [])
                            if local_name == column_name
                        ),
                        None,
                    )
                    foreign_table = None
                    foreign_column = None
                    if matching_foreign_key:
                        foreign_key, index = matching_foreign_key
                        foreign_table = _qualified_name(
                            foreign_key.get("referred_schema") or schema_name,
                            foreign_key["referred_table"],
                        )
                        foreign_column = foreign_key["referred_columns"][index]
                    column_infos.append(
                        ColumnInfo(
                            name=column_name,
                            data_type=str(column_data.get("type", "unknown")),
                            is_primary_key=column_name in primary_key_names,
                            is_foreign_key=matching_foreign_key is not None,
                            foreign_table=foreign_table,
                            foreign_column=foreign_column,
                            comment=column_data.get("comment"),
                            nullable=column_data.get("nullable", True),
                            enum_options=parse_enum_options(column_data.get("type", "")),
                        )
                    )
                tables[table_name] = TableInfo(
                    name=table_name,
                    description=table_comment or f"Table {table_name}.",
                    columns=column_infos,
                    primary_key_names=primary_key_names,
                    foreign_keys=[
                        {
                            "constrain_name": foreign_key.get("name"),
                            "local_cols": foreign_key.get("constrained_columns") or [],
                            "remote_table": _qualified_name(
                                foreign_key.get("referred_schema") or schema_name,
                                foreign_key.get("referred_table", ""),
                            ),
                            "remote_cols": foreign_key.get("referred_columns") or [],
                        }
                        for foreign_key in foreign_keys
                    ],
                    schema=schema_name,
                    comment=table_comment,
                    unique_constraints=[
                        constraint.get("column_names") or []
                        for constraint in unique_constraints
                        if constraint.get("column_names")
                    ],
                )
            except (sa.exc.SQLAlchemyError, KeyError):
                LOGGER.warning("Table inspection skipped", extra={"table": table_name})
    return SchemaMetadata(tables)