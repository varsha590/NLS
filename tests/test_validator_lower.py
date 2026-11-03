"""Tests for case-insensitive SQL literal rewriting."""

from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from schema.context import build_schema_context
from sql.validator import rewrite_case_insensitive_comparisons


def _metadata():
    return SchemaMetadata({
        "categories": TableInfo(
            "categories",
            "Categories",
            [ColumnInfo("category_name", "VARCHAR")],
            [],
            [],
        )
    })


def test_rewrites_literal_equality_with_table_qualifier():
    rewritten = rewrite_case_insensitive_comparisons(
        "SELECT category_name FROM categories WHERE category_name = 'x'",
        _metadata(),
        {"categories"},
    )
    assert "LOWER(category_name) = LOWER('x')" in rewritten


def test_rewrites_literal_equality_through_table_alias():
    rewritten = rewrite_case_insensitive_comparisons(
        "SELECT c.category_name FROM categories AS c WHERE c.category_name = 'x'",
        _metadata(),
        {"categories"},
    )
    assert "LOWER(c.category_name) = LOWER('x')" in rewritten


def test_schema_context_includes_only_current_value_hints():
    context = build_schema_context(
        _metadata(),
        [],
        value_hints=[{
            "mention": "electronics",
            "column": "categories.category_name",
            "value": "Electronics",
            "score": 1.0,
        }],
    )
    assert "=== VALUE HINTS ===" in context
    assert "electronics" in context
    assert "Electronics" in context
    assert "Clothing" not in context