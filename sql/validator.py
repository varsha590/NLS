"""Compatibility wrappers for the database-agnostic SQL validator."""

from __future__ import annotations

from typing import Any

from sqlglot import exp, parse_one

from schema.metadata import SchemaMetadata
from validation.validator import ValidationError, validate_sql as validate_catalog_sql


class ValidationResult:
    """Legacy result shape for callers migrating to ValidationError."""

    def __init__(self, valid: bool, sql: str, error_message: str | None = None):
        self.valid = valid
        self.sql = sql
        self.error_message = error_message
        self.rejected_constructs: list[str] = []

    def is_valid(self) -> bool:
        """Return whether the query passed validation."""
        return self.valid

    def __bool__(self) -> bool:
        return self.valid


def build_sqlglot_schema(metadata: SchemaMetadata, allowed_tables: set[str]) -> dict[str, dict[str, str]]:
    """Return a SQLGlot schema mapping for compatibility callers."""
    return {
        table_name: {column.name: column.data_type for column in metadata.tables[table_name].columns}
        for table_name in allowed_tables
        if table_name in metadata.tables
    }


def is_string_column(metadata: SchemaMetadata, table_name: str, column_name: str) -> bool:
    """Return whether a catalog column has a textual type."""
    table = metadata.tables.get(table_name)
    if table is None:
        return False
    return any(
        column.name == column_name
        and any(kind in column.data_type.casefold() for kind in ("char", "text", "string"))
        for column in table.columns
    )


def rewrite_case_insensitive_comparisons(
    sql: str, metadata: SchemaMetadata, allowed_tables: set[str]
) -> str:
    """Normalize string equality using SQLGlot's generic parser and catalog types."""
    parsed = parse_one(sql)
    aliases = {
        table.alias_or_name.casefold(): table.name
        for table in parsed.find_all(exp.Table)
    }
    for equality in parsed.find_all(exp.EQ):
        left, right = equality.left, equality.right
        column = left if isinstance(left, exp.Column) else right if isinstance(right, exp.Column) else None
        literal = right if column is left else left
        if column is None or not isinstance(literal, exp.Literal) or not literal.is_string:
            continue
        table_name = aliases.get(column.table.casefold(), column.table) if column.table else ""
        if not table_name and len(allowed_tables) == 1:
            table_name = next(iter(allowed_tables))
        if table_name in allowed_tables and is_string_column(metadata, table_name, column.name):
            left_value = exp.func("LOWER", left.copy())
            right_value = exp.func("LOWER", right.copy())
            equality.replace(exp.EQ(this=left_value, expression=right_value))
    return parsed.sql()


def format_column_validation_error(parsed: Any, error: Exception) -> str:
    """Retain the legacy error formatter entry point."""
    return str(error)


def validate_sql(
    sql: str,
    allowed_tables: set[str],
    metadata: SchemaMetadata | None = None,
    allowed_column_pattern=None,
    max_rows: int = 100,
    max_query_cost: int = 100000,
    dialect: str | None = None,
) -> ValidationResult:
    """Validate through the new catalog-aware SQLGlot validator."""
    if metadata is None:
        try:
            parsed = parse_one(sql, read=dialect)
            if not isinstance(parsed, exp.Select):
                raise ValidationError("Only a single SELECT statement is allowed.")
            normalized = parsed.limit(max_rows).sql(dialect=dialect)
            return ValidationResult(True, normalized)
        except Exception as error:
            return ValidationResult(False, sql, str(error))
    try:
        normalized = validate_catalog_sql(
            sql,
            metadata=metadata,
            dialect=dialect,
            allowed_tables=allowed_tables,
            max_rows=max_rows,
        )
        return ValidationResult(True, normalized)
    except ValidationError as error:
        return ValidationResult(False, sql, str(error))
