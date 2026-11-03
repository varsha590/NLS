"""Regression tests for conservative value matching and local catalog contents."""

import sqlalchemy as sa

from catalog.introspect import introspect_catalog
from db.adapter import DatabaseAdapter
from retrieval.value_index import ValueIndex


def _value_index():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    categories = sa.Table(
        "categories",
        metadata,
        sa.Column("category_id", sa.Integer, primary_key=True),
        sa.Column("category_name", sa.String),
        sa.Column("description", sa.String),
    )
    customers = sa.Table(
        "customers",
        metadata,
        sa.Column("customer_id", sa.Integer, primary_key=True),
        sa.Column("city", sa.String),
        sa.Column("email", sa.String),
    )
    orders = sa.Table(
        "orders",
        metadata,
        sa.Column("order_id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String),
    )
    sa.Table(
        "schema_embeddings",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("table_name", sa.String),
        sa.Column("relationships", sa.String),
        sa.Column("business_relevance", sa.String),
        sa.Column("embedding", sa.String),
    )
    sa.Table(
        "value_catalog",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("table_name", sa.String),
        sa.Column("column_name", sa.String),
        sa.Column("values_text", sa.String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(categories.insert(), [
            {"category_id": 1, "category_name": "Electronics", "description": "Electronics category"},
            {"category_id": 2, "category_name": "Electronix", "description": "Alternate"},
        ])
        connection.execute(customers.insert(), [
            {"customer_id": 1, "city": "Seattle", "email": "person@example.com"},
        ])
        connection.execute(orders.insert(), [{"order_id": 1, "status": "completed"}])
        connection.execute(sa.Table("schema_embeddings", metadata).insert(), [{
            "id": "table:orders",
            "table_name": "orders",
            "relationships": "[]",
            "business_relevance": "Revenue orders sum",
            "embedding": "[0.0]",
        }])
        connection.execute(sa.Table("value_catalog", metadata).insert(), [{
            "id": 1,
            "table_name": "orders",
            "column_name": "category_name",
            "values_text": "orders",
        }])
    catalog = introspect_catalog(engine)
    return ValueIndex(DatabaseAdapter("sqlite:///:memory:", engine=engine), catalog)


def test_index_contains_only_semantic_data_values_not_schema_metadata():
    index = _value_index()

    values = index.build()

    assert set(values) == {
        "categories.category_name",
        "customers.city",
        "orders.status",
    }
    assert values["categories.category_name"] == ["Electronics", "Electronix"]
    assert values["customers.city"] == ["Seattle"]
    assert "orders" not in {value.casefold() for column_values in values.values() for value in column_values}
    assert "category_name" not in {value.casefold() for column_values in values.values() for value in column_values}
    assert all("@" not in value for column_values in values.values() for value in column_values)


def test_orders_question_resolves_only_seattle_without_confirmation_noise():
    index = _value_index()
    index.build()

    matches = index.resolve_question("how many orders are there from Seattle")

    assert len(matches) == 1
    assert matches[0]["mention"] == "Seattle"
    assert matches[0]["column"] == "customers.city"
    assert matches[0]["value"] == "Seattle"
    assert not matches[0].get("ambiguous")


def test_cue_followed_by_unknown_value_reports_one_not_found():
    index = _value_index()
    index.build()

    matches = index.resolve_question("category gadgets")

    assert matches == [{
        "mention": "gadgets",
        "not_found": True,
        "column": "categories.category_name",
        "candidates": [],
        "confidence": 0.0,
    }]


def test_close_candidate_pair_is_ambiguous_but_single_weak_match_is_ignored():
    index = _value_index()
    index.build()

    matches = index.resolve_question("Electroni")

    assert len(matches) == 1
    assert matches[0].get("ambiguous")
    assert {candidate["value"] for candidate in matches[0]["candidates"]} == {
        "Electronics", "Electronix"
    }


def test_overlapping_value_mentions_keep_best_shortest_span():
    index = _value_index()
    index.build()
    index.values["customers.city"] = ["New York"]

    matches = index.resolve_question("from New York")

    assert len(matches) == 1
    assert matches[0]["mention"] == "New York"
    assert matches[0]["value"] == "New York"


def test_york_vs_new_york_overlap_prefers_exact_value_match():
    """With values ['York', 'New York'], 'orders from New York' resolves to 'New York'."""
    index = _value_index()
    index.build()
    index.values["customers.city"] = ["York", "New York"]

    matches = index.resolve_question("orders from New York")

    assert len(matches) == 1
    assert matches[0]["mention"] == "New York"
    assert matches[0]["value"] == "New York"
    assert matches[0]["column"] == "customers.city"