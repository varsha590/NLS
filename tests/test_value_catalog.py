"""Tests for generic, read-only distinct-value catalog discovery."""

import sqlalchemy as sa

from schema.value_catalog import (
    build_value_catalog,
    classify_value_tiers,
    ensure_trgm_indexes,
    get_catalog_columns,
)


def test_catalog_discovers_arbitrary_low_cardinality_text_columns():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    labels = sa.Table(
        "labels",
        metadata,
        sa.Column("label_key", sa.Integer, primary_key=True),
        sa.Column("label_text", sa.String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(labels.insert(), [
            {"label_key": 1, "label_text": "Alpha"},
            {"label_key": 2, "label_text": "Beta"},
            {"label_key": 3, "label_text": "Alpha"},
        ])

    small_columns, large_columns = classify_value_tiers(engine, small_value_limit=2)

    assert small_columns == ("labels.label_text",)
    assert large_columns == ()
    assert build_value_catalog(engine) == {"labels.label_text": ["Alpha", "Beta"]}
    assert get_catalog_columns(engine) == [{"table": "labels", "column": "label_text"}]


def test_legacy_index_helper_does_not_change_target_schema():
    engine = sa.create_engine("sqlite:///:memory:")
    ensure_trgm_indexes(engine)
    assert sa.inspect(engine).get_table_names() == []
