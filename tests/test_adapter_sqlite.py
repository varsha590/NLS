"""Focused portability checks for the SQLAlchemy adapter."""

import sqlalchemy as sa
import numpy as np

from db.adapter import DatabaseAdapter
from catalog.introspect import introspect_catalog
from retrieval.local_store import LocalVectorStore
from retrieval.value_index import ValueIndex


def test_adapter_executes_readonly_sqlite_query_with_row_bound():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE records (record_id INTEGER)")
        connection.exec_driver_sql("INSERT INTO records VALUES (1), (2), (3)")

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    result = adapter.run_readonly_query("SELECT record_id FROM records ORDER BY record_id", 2)

    assert adapter.get_dialect() == "sqlite"
    assert result.columns == ["record_id"]
    assert result.rows == [{"record_id": 1}, {"record_id": 2}]


def test_catalog_introspection_reads_sqlite_columns_keys_and_samples():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    parent = sa.Table(
        "parent_record",
        metadata,
        sa.Column("parent_key", sa.Integer, primary_key=True),
        sa.Column("label", sa.String),
    )
    sa.Table(
        "child_record",
        metadata,
        sa.Column("child_key", sa.Integer, primary_key=True),
        sa.Column("parent_key", sa.ForeignKey("parent_record.parent_key")),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(parent.insert(), [{"parent_key": 1, "label": "First"}])

    catalog = introspect_catalog(engine, excluded_tables=("child_record",))

    assert set(catalog.tables) == {"parent_record"}
    label = catalog.tables["parent_record"].columns[1]
    assert label.sample_values == ["First"]
    assert catalog.tables["parent_record"].primary_key_names == ["parent_key"]


def test_value_index_stores_distinct_text_values_locally(tmp_path):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    categories = sa.Table(
        "categories",
        metadata,
        sa.Column("category_name", sa.String, primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(categories.insert(), [{"category_name": "Electronics"}])
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)

    class TinyEmbedder:
        model_name = "tiny-model"
        dim = 2

        def embed(self, texts):
            return np.asarray([[len(text), sum(text.encode())] for text in texts], dtype=float)

    embedder = TinyEmbedder()
    local_store = LocalVectorStore(
        tmp_path, adapter.namespace(), embedder.model_name, embedder.dim, "test-policy"
    )
    value_index = ValueIndex(
        adapter, catalog, embedder=embedder, local_store=local_store
    )

    assert value_index.build() == {"categories.category_name": ["Electronics"]}
    resolved = value_index.resolve("electronics", "categories.category_name")
    assert resolved["resolved"]["value"] == "Electronics"
    stored = local_store.search_values(
        embedder.embed(["electronics"])[0],
        1,
        table="categories",
        column="category_name",
    )
    assert len(stored) == 1


def test_url_display_and_namespace_exclude_credentials():
    adapter = DatabaseAdapter(
        "postgresql+psycopg://reader:password123@localhost/db?password=query-secret&sslmode=require"
    )

    assert "password123" not in adapter.masked_url()
    assert "query-secret" not in adapter.masked_url()
    assert "reader" not in adapter.namespace()
    assert "password123" not in adapter.namespace()