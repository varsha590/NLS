"""Behavioral tests for dialect-aware SQL validation."""

import pytest

from config.data_policy import SENSITIVE_COLUMN_PATTERNS, is_blocked
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from validation.validator import ValidationError, validate_sql


@pytest.fixture
def catalog():
    return SchemaMetadata({
        "orders": TableInfo(
            "orders",
            "Customer orders",
            [
                ColumnInfo("order_id", "INTEGER", is_primary_key=True),
                ColumnInfo("status", "VARCHAR"),
                ColumnInfo("password_hash", "VARCHAR"),
                ColumnInfo("customerToken", "VARCHAR"),
                ColumnInfo("pan_number", "VARCHAR"),
                ColumnInfo("cardNumber", "VARCHAR"),
                ColumnInfo("company", "VARCHAR"),
                ColumnInfo("discard", "VARCHAR"),
                ColumnInfo("postcard_status", "VARCHAR"),
            ],
            ["order_id"],
            [],
        ),
        "users": TableInfo(
            "users",
            "Users",
            [
                ColumnInfo("user_id", "INTEGER", is_primary_key=True),
                ColumnInfo("secret_token", "VARCHAR"),
            ],
            ["user_id"],
            [],
        ),
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


def test_qualified_column_is_not_skipped_when_it_matches_projection_alias(catalog):
    with pytest.raises(ValidationError):
        validate_sql(
            "SELECT o.order_id AS id, o.id FROM orders AS o",
            catalog,
            "sqlite",
            {"orders"},
        )


def test_aliases_are_allowed_only_in_their_select_order_group_and_having(catalog):
    sql = validate_sql(
        "SELECT status AS state, COUNT(*) AS quantity FROM orders "
        "GROUP BY state HAVING quantity > 0 ORDER BY state",
        catalog,
        "sqlite",
        {"orders"},
    )
    assert "ORDER BY state" in sql
    with pytest.raises(ValidationError):
        validate_sql(
            "SELECT status AS state FROM orders WHERE state = 'open'",
            catalog,
            "sqlite",
            {"orders"},
        )


def test_cte_and_subquery_columns_resolve_against_their_source_scope(catalog):
    cte_sql = validate_sql(
        "WITH selected AS (SELECT order_id FROM orders) "
        "SELECT selected.order_id FROM selected",
        catalog,
        "sqlite",
        {"orders"},
    )
    subquery_sql = validate_sql(
        "SELECT derived.order_id FROM "
        "(SELECT o.order_id FROM orders AS o) AS derived",
        catalog,
        "sqlite",
        {"orders"},
    )
    shadowed_alias_sql = validate_sql(
        "SELECT o.order_id FROM orders AS o WHERE EXISTS "
        "(SELECT o.user_id FROM users AS o WHERE o.user_id = 1)",
        catalog,
        "sqlite",
        {"orders", "users"},
    )
    assert "selected" in cte_sql
    assert "derived" in subquery_sql
    assert "EXISTS" in shadowed_alias_sql


@pytest.mark.parametrize(
    ("sql", "dialect"),
    [
        ("WITH changed AS (DELETE FROM orders RETURNING order_id) SELECT order_id FROM changed", "postgres"),
        ("WITH changed AS (UPDATE orders SET status = 'x' RETURNING order_id) SELECT order_id FROM changed", "postgres"),
        ("WITH changed AS (INSERT INTO orders (order_id) VALUES (1) RETURNING order_id) SELECT order_id FROM changed", "postgres"),
        ("SELECT order_id INTO copied_orders FROM orders", "postgres"),
        ("SELECT order_id FROM orders FOR UPDATE", "postgres"),
        ("SELECT order_id FROM orders FOR SHARE", "postgres"),
        ("EXPLAIN SELECT order_id FROM orders", "sqlite"),
    ],
)
def test_non_select_constructs_are_rejected_anywhere_in_the_query(catalog, sql, dialect):
    with pytest.raises(ValidationError):
        validate_sql(sql, catalog, dialect, {"orders"})


def test_pg_sleep_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT pg_sleep(1) FROM orders", catalog, "postgres", {"orders"})


def test_pg_read_file_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT pg_read_file('secret.txt') FROM orders", catalog, "postgres", {"orders"})


def test_load_extension_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT load_extension('extension.so') FROM orders", catalog, "sqlite", {"orders"})


def test_dblink_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT dblink('connection') FROM orders", catalog, "postgres", {"orders"})


def test_sleep_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT sleep(1) FROM orders", catalog, "mysql", {"orders"})


def test_benchmark_function_is_rejected(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql("SELECT benchmark(1, 'expression') FROM orders", catalog, "mysql", {"orders"})


def test_restricted_function_is_rejected_inside_a_cte(catalog):
    with pytest.raises(ValidationError, match="restricted SQL function"):
        validate_sql(
            "WITH delayed AS (SELECT pg_sleep(1) AS result FROM orders) "
            "SELECT result FROM delayed",
            catalog,
            "postgres",
            {"orders"},
        )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT o.password_hash FROM orders AS o",
        "SELECT o.order_id FROM orders AS o WHERE o.customerToken = 'x'",
        "SELECT o.order_id FROM orders AS o JOIN users AS u ON u.secret_token = o.status",
        "SELECT o.order_id FROM orders AS o GROUP BY o.customerToken, o.order_id",
        "SELECT o.order_id FROM orders AS o ORDER BY o.customerToken",
        "SELECT * FROM orders",
        "SELECT o.* FROM orders AS o",
    ],
)
def test_sensitive_columns_are_blocked_in_all_clauses(catalog, sql):
    with pytest.raises(ValidationError, match="information isn't available"):
        validate_sql(sql, catalog, "sqlite", {"orders", "users"})


def test_postgres_quoted_sensitive_column_is_blocked(catalog):
    with pytest.raises(ValidationError, match="information isn't available"):
        validate_sql(
            'SELECT o."pan_number" FROM orders AS o',
            catalog,
            "postgres",
            {"orders"},
        )


def test_mysql_backticked_sensitive_column_is_blocked(catalog):
    with pytest.raises(ValidationError, match="information isn't available"):
        validate_sql(
            "SELECT o.`cardNumber` FROM orders AS o",
            catalog,
            "mysql",
            {"orders"},
        )


def test_sensitive_token_boundaries_allow_company_and_discard(catalog):
    sql = validate_sql(
        "SELECT company, discard FROM orders",
        catalog,
        "mysql",
        {"orders"},
    )
    assert "company" in sql and "discard" in sql


def test_sensitive_patterns_use_whole_identifier_tokens():
    assert "password" in SENSITIVE_COLUMN_PATTERNS
    assert is_blocked("orders.customerToken")
    assert is_blocked("orders.pan_number")
    assert is_blocked("orders.cardNumber")
    assert not is_blocked("orders.company")
    assert not is_blocked("orders.discard")
    assert is_blocked("orders.card_number")
    assert not is_blocked("orders.postcard_status")


def test_limit_is_enforced_on_set_operation_ast(catalog):
    sql = validate_sql(
        "SELECT order_id FROM orders UNION SELECT user_id FROM users LIMIT 500",
        catalog,
        "sqlite",
        {"orders", "users"},
        max_rows=7,
    )
    assert "LIMIT 7" in sql.upper()
