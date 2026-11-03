"""Integration test against the real database (skips if unreachable)."""

import os
import sys

import pytest
import sqlalchemy as sa

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _has_laptop_fixture_schema():
    try:
        from dotenv import load_dotenv
        from sqlalchemy import inspect

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(project_root, ".env"))
        from config.settings import Settings
        from db.adapter import DatabaseAdapter

        settings = Settings.from_env()
        adapter = DatabaseAdapter(settings.database_url, settings.query_timeout_seconds)
        tables = {name.rsplit(".", 1)[-1] for name in inspect(adapter.engine).get_table_names()}
        return {"orders", "order_items", "products"}.issubset(tables)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _has_laptop_fixture_schema(),
    reason="Configured database is unreachable or lacks the laptop fixture schema",
)


def test_laptop_resolves_and_returns_real_count():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

    from core.startup import init_app
    runtime = init_app(force=True)
    pipeline = runtime["pipeline"]

    original_generate = pipeline.generator.generate
    pipeline.generator.generate = lambda messages: (
        "SELECT COUNT(DISTINCT o.order_id) AS order_count "
        "FROM orders AS o JOIN order_items AS oi ON o.order_id = oi.order_id "
        "JOIN products AS p ON oi.product_id = p.product_id "
        "WHERE p.product_name = 'Laptop'"
    )
    pipeline.generator.summarize = lambda question, rows: "Found %d record(s)." % len(rows)

    result = pipeline.run("How many orders were placed for Laptop?")

    assert "Laptop Pro" in result.sql, "SQL should contain 'Laptop Pro', got: %s" % result.sql
    assert result.errors == [], "Errors: %s" % result.errors

    with runtime["adapter"].engine.connect() as connection:
        expected = connection.execute(sa.text(
            "SELECT COUNT(DISTINCT oi.order_id) FROM order_items oi JOIN products p "
            "ON p.product_id = oi.product_id WHERE LOWER(p.product_name) = 'laptop pro'"
        )).scalar_one()

    assert result.rows, "Should have rows"
    assert list(result.rows[0].values())[0] == expected, "Expected %s, got %s" % (expected, result.rows)

    assert any(
        rv.get("mention", "").casefold() == "laptop" and rv.get("value") == "Laptop Pro"
        for rv in result.resolved_values
    ), "Should have interpretation, got: %s" % result.resolved_values


def test_laptop_correct_sql_returns_same_count():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

    from core.startup import init_app
    runtime = init_app(force=True)
    pipeline = runtime["pipeline"]

    pipeline.generator.generate = lambda messages: (
        "SELECT COUNT(DISTINCT o.order_id) AS order_count "
        "FROM orders AS o JOIN order_items AS oi ON o.order_id = oi.order_id "
        "JOIN products AS p ON oi.product_id = p.product_id "
        "WHERE p.product_name = 'Laptop Pro'"
    )
    pipeline.generator.summarize = lambda question, rows: "Found %d record(s)." % len(rows)

    result = pipeline.run("How many orders were placed for Laptop?")

    assert "Laptop Pro" in result.sql
    assert result.errors == []

    with runtime["adapter"].engine.connect() as connection:
        expected = connection.execute(sa.text(
            "SELECT COUNT(DISTINCT oi.order_id) FROM order_items oi JOIN products p "
            "ON p.product_id = oi.product_id WHERE LOWER(p.product_name) = 'laptop pro'"
        )).scalar_one()

    assert list(result.rows[0].values())[0] == expected
