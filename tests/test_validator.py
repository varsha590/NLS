"""Behavioral tests for dialect-aware SQL validation."""

import pytest

from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from validation.validator import ValidationError, validate_sql


@pytest.fixture
def catalog():
    return SchemaMetadata({
        "orders": TableInfo(
            "orders",
            "Customer orders",
            [ColumnInfo("order_id", "INTEGER", is_primary_key=True), ColumnInfo("status", "VARCHAR")],
            ["order_id"],
            [],
        )
    })


def test_valid_select_gets_maximum_limit(catalog):
    sql = validate_sql(
        "SELECT order_id FROM orders", catalog, "sqlite", {"orders"}, max_rows=25
    )
    assert "LIMIT 25" in sql.upper()


def test_limit_expression_is_replaced_with_configured_cap(catalog):
    sql = validate_sql(
        "SELECT order_id FROM orders LIMIT 100 + 50",
        catalog,
        "sqlite",
        {"orders"},
        max_rows=25,
    )
    assert "LIMIT 25" in sql.upper()


@pytest.mark.parametrize("sql", [
    "INSERT INTO orders (order_id) VALUES (1)",
    "UPDATE orders SET status = 'x'",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "ALTER TABLE orders ADD COLUMN other TEXT",
    "CREATE TABLE other (id INTEGER)",
    "TRUNCATE TABLE orders",
    "GRANT SELECT ON orders TO user_a",
])
def test_mutating_and_privilege_statements_are_rejected(catalog, sql):
    with pytest.raises(ValidationError):
        validate_sql(sql, catalog, "sqlite")


def test_multi_statement_is_rejected(catalog):
    with pytest.raises(ValidationError, match="Multiple SQL statements"):
        validate_sql("SELECT order_id FROM orders; SELECT status FROM orders", catalog, "sqlite")


def test_unknown_aliased_column_has_catalog_suggestion(catalog):
    with pytest.raises(ValidationError, match=r"column o.id does not exist; did you mean orders.order_id"):
        validate_sql("SELECT o.id FROM orders AS o", catalog, "sqlite", {"orders"})


def test_comments_are_rejected(catalog):
    with pytest.raises(ValidationError, match="comments are not allowed"):
        validate_sql("SELECT order_id FROM orders /* hidden statement */", catalog, "sqlite")
