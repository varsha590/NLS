"""Tests for configurable schema exclusions and compact context generation."""

import sqlalchemy as sa

from catalog.introspect import introspect_catalog
from schema.context import build_schema_context


def test_catalog_respects_explicit_exclusion_names():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("public_data", metadata, sa.Column("public_key", sa.Integer))
    sa.Table("private_data", metadata, sa.Column("private_key", sa.Integer))
    metadata.create_all(engine)

    catalog = introspect_catalog(engine, excluded_tables=("private_data",))

    assert set(catalog.tables) == {"public_data"}


def test_schema_context_contains_only_selected_database_tables():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("public_data", metadata, sa.Column("public_key", sa.Integer))
    sa.Table("private_data", metadata, sa.Column("private_key", sa.Integer))
    metadata.create_all(engine)
    catalog = introspect_catalog(engine)

    context = build_schema_context(catalog, ["public_data"], include_business_rules=False)

    assert "public_data(public_key" in context
    assert "private_data" not in context
