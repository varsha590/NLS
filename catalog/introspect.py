"""Build normalized schema metadata from SQLAlchemy inspection."""

from __future__ import annotations

import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo

LOGGER = logging.getLogger(__name__)


def _qualified_name(schema: str | None, table: str) -> str:
    return f"{schema}.{table}" if schema else table


def introspect_catalog(
    engine: Engine,
    allowed_schemas: tuple[str, ...] = (),
    excluded_tables: tuple[str, ...] = (),
    sample_limit: int = 5,
) -> SchemaMetadata:
    """Inspect tables, columns, keys, comments, and bounded per-column samples."""
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
        for raw_table_name in table_names:
            table_name = _qualified_name(schema_name, raw_table_name)
            if table_name in excluded or raw_table_name in excluded:
                continue
            try:
                columns = inspector.get_columns(raw_table_name, schema=schema_name)
                primary_keys = inspector.get_pk_constraint(raw_table_name, schema=schema_name)
                primary_key_names = primary_keys.get("constrained_columns") or []
                foreign_keys = inspector.get_foreign_keys(raw_table_name, schema=schema_name)
                table_comment = None
                try:
                    table_comment = inspector.get_table_comment(
                        raw_table_name, schema=schema_name
                    ).get("text")
                except (NotImplementedError, sa.exc.SQLAlchemyError):
                    pass

                reflected = sa.Table(
                    raw_table_name,
                    sa.MetaData(),
                    schema=schema_name,
                    autoload_with=engine,
                )
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
                    samples: list[Any] = []
                    try:
                        reflected_column = reflected.c[column_name]
                        with engine.connect() as connection:
                            values = connection.execute(
                                sa.select(reflected_column)
                                .where(reflected_column.is_not(None))
                                .distinct()
                                .limit(sample_limit)
                            ).scalars().all()
                        samples = [str(value) for value in values]
                    except (sa.exc.SQLAlchemyError, KeyError):
                        LOGGER.debug(
                            "Column samples unavailable",
                            extra={"table": table_name, "column": column_name},
                        )
                    column_infos.append(
                        ColumnInfo(
                            name=column_name,
                            data_type=str(column_data.get("type", "unknown")),
                            is_primary_key=column_name in primary_key_names,
                            is_foreign_key=matching_foreign_key is not None,
                            foreign_table=foreign_table,
                            foreign_column=foreign_column,
                            comment=column_data.get("comment"),
                            sample_values=samples,
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
                )
            except (sa.exc.SQLAlchemyError, KeyError):
                LOGGER.warning("Table inspection skipped", extra={"table": table_name})
    return SchemaMetadata(tables)