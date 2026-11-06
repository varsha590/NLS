"""Regression tests for the Phase 0 safety guarantees after Qdrant migration."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sqlalchemy as sa
from qdrant_client import QdrantClient

from config.settings import Settings
from core import startup
from db.adapter import DatabaseAdapter, DatabaseUnavailableError
from pipeline.orchestrator import TextToSQLPipeline
from retrieval import qdrant_store as qdrant_store_module
from retrieval.examples import ExampleStore
from retrieval.qdrant_store import QdrantVectorStore
from retrieval.schema_retriever import HybridSchemaRetriever, retrieve_schema
from retrieval.value_index import ValueIndex
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from validation.validator import validate_sql


def _qdrant_store(
    tmp_path,
    dataset: str = "synthetic",
    tenant: str = "synthetic",
    dim: int = 4,
) -> QdrantVectorStore:
    metadata_path = tmp_path / "dataset.json"
    store = QdrantVectorStore(
        settings=Settings.from_env(),
        client=QdrantClient(location=":memory:"),
        vector_size=dim,
        tenant_id=tenant,
        dataset_id=dataset,
        dataset_metadata_path=metadata_path,
    )
    metadata_path.write_text(
        json.dumps(
            {
                "tenant_id": tenant,
                "dataset_id": dataset,
                "indexed": True,
                "embedding_model_name": store.model_name,
                "vector_dimension": dim,
            }
        )
    )
    return store


class FakeEmbedder:
    model_name = "synthetic-model"
    dim = 4

    def __init__(self, model_name: str = "synthetic-model"):
        self.model_name = model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for index, value in enumerate(text.encode("utf-8")):
                vectors[row, index % self.dim] += value + 1
        return vectors


class FakeGenerator:
    def __init__(self, sql: str = "SELECT 1"):
        self.sql = sql

    def generate(self, messages: list[dict]) -> str:
        return self.sql


def test_local_store_reuses_cached_vectors_without_null_overwrite(tmp_path):
    embedder = FakeEmbedder()
    client = QdrantClient(location=":memory:")
    metadata_path = tmp_path / "dataset.json"

    def make_store() -> QdrantVectorStore:
        return QdrantVectorStore(
            settings=Settings.from_env(),
            client=client,
            vector_size=embedder.dim,
            tenant_id="synthetic",
            dataset_id="synthetic",
            dataset_metadata_path=metadata_path,
        )

    store = make_store()
    metadata_path.write_text(
        json.dumps(
            {
                "tenant_id": "synthetic",
                "dataset_id": "synthetic",
                "indexed": True,
                "embedding_model_name": store.model_name,
                "vector_dimension": embedder.dim,
            }
        )
    )
    records = [{
        "table_name": "schema_one.generic_table",
        "column_name": None,
        "metadata_type": "table_ddl",
        "content": "generic table",
    }]
    assert store.build_schema(records, embedder)
    vector_before = store.search_schema(embedder.embed(["generic table"])[0], 1)
    reloaded = make_store()
    assert reloaded.build_schema(records, embedder)
    assert reloaded.search_schema(embedder.embed(["generic table"])[0], 1) == vector_before


def test_value_index_does_not_store_high_cardinality_values(tmp_path):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table("synthetic_records", metadata, sa.Column("generic_field", sa.String))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"generic_field": f"candidate-{index}"} for index in range(3)])
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = __import__("catalog.introspect", fromlist=["introspect_catalog"]).introspect_catalog(
        engine
    )
    embedder = FakeEmbedder()
    store = _qdrant_store(tmp_path, dataset=adapter.namespace(), dim=embedder.dim)
    index = ValueIndex(adapter, catalog, cardinality_threshold=2, embedder=embedder, local_store=store)

    index.build()

    assert index.large_columns == {"synthetic_records.generic_field"}
    assert store.count_values() == 0


def test_schema_retriever_searches_local_vectors_with_schema_qualified_keys(tmp_path):
    metadata = SchemaMetadata(
        tables={
            "schema_one.generic_table": TableInfo(
                name="schema_one.generic_table",
                description="first generic table",
                columns=[ColumnInfo("generic_key", "INTEGER", is_primary_key=True)],
                primary_key_names=["generic_key"],
                foreign_keys=[],
            ),
            "schema_two.generic_table": TableInfo(
                name="schema_two.generic_table",
                description="second generic table",
                columns=[ColumnInfo("generic_key", "INTEGER", is_primary_key=True)],
                primary_key_names=["generic_key"],
                foreign_keys=[],
            ),
        }
    )
    embedder = FakeEmbedder()
    store = _qdrant_store(tmp_path, dim=embedder.dim)
    assert store.build_schema([
        {
            "table_name": table.name,
            "column_name": None,
            "metadata_type": "table_ddl",
            "content": table.description,
        }
        for table in metadata.tables.values()
    ], embedder)
    search = MagicMock(wraps=store.search_schema)
    store.search_schema = search

    result = HybridSchemaRetriever(metadata, embedder, local_store=store).retrieve(
        "first generic table", top_k=2
    )

    search.assert_called_once()
    assert set(result["tables"]) == set(metadata.tables)
    assert "schema_one.generic_table" in result["scores"]
    assert "schema_two.generic_table" in result["scores"]


def test_retrieve_schema_compatibility_wrapper_stays_operational():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE generic_records (generic_key INTEGER PRIMARY KEY)")

    with patch("retrieval.schema_retriever.EmbeddingModel", FakeEmbedder):
        result = retrieve_schema(engine, "find generic records", top_k=1)
    assert "generic_records" in result["tables"]


def test_example_store_save_failure_returns_false(tmp_path):
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    assert not ExampleStore(None, adapter).save("generic question", "SELECT 1")


def test_value_index_failure_does_not_log_value_text(tmp_path, caplog):
    class FailingEmbedder(FakeEmbedder):
        def embed(self, texts: list[str]) -> np.ndarray:
            raise RuntimeError("synthetic embed failure")

    embedder = FailingEmbedder()
    store = _qdrant_store(tmp_path, dim=embedder.dim)
    with caplog.at_level(logging.ERROR):
        assert not store.build_values([{
            "table_name": "synthetic_table",
            "column_name": "generic_field",
            "classification": "VALUE_LOW",
            "value_hash": "synthetic-hash",
            "value": "sensitive-sentinel-value",
        }], embedder)
    assert "sensitive-sentinel-value" not in caplog.text


def test_literal_validation_restricts_column_lookup_to_used_tables():
    metadata = SchemaMetadata(
        tables={
            "synthetic_accounts": TableInfo(
                name="synthetic_accounts",
                description="",
                columns=[ColumnInfo("generic_key", "INTEGER"), ColumnInfo("generic_state", "VARCHAR")],
                primary_key_names=[],
                foreign_keys=[],
            ),
            "synthetic_records": TableInfo(
                name="synthetic_records",
                description="",
                columns=[ColumnInfo("generic_key", "INTEGER"), ColumnInfo("generic_state", "VARCHAR")],
                primary_key_names=[],
                foreign_keys=[],
            ),
        }
    )
    value_index = MagicMock()
    value_index.values = {"synthetic_accounts.generic_state": ["active"]}
    value_index.ambiguous_gap = 0.08
    value_index.max_candidates = 5

    validated = validate_sql(
        "SELECT generic_key FROM synthetic_accounts WHERE generic_state = 'active'",
        metadata=metadata,
        dialect="sqlite",
        allowed_tables={"synthetic_accounts"},
        value_index=value_index,
    )
    assert "synthetic_accounts" in validated


def test_partial_local_index_surfaces_incomplete_state(tmp_path, monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("synthetic_records", metadata, sa.Column("generic_key", sa.Integer, primary_key=True))
    metadata.create_all(engine)
    settings = Settings(
        groq_api_key="",
        llm_model="synthetic-model",
        embedding_model="synthetic-model",
        vector_store_path=str(tmp_path),
        schema_top_k=2,
        value_top_k=2,
        query_timeout_seconds=5,
        max_retries=0,
        allowed_schemas=(),
        excluded_tables=(),
        value_cardinality_threshold=10,
    )
    monkeypatch.setattr(startup.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        startup,
        "DatabaseAdapter",
        lambda url, timeout: DatabaseAdapter(url, timeout, engine=engine),
    )
    monkeypatch.setattr(startup, "EmbeddingModel", FakeEmbedder)
    monkeypatch.setattr(startup, "GroqGenerator", lambda *args: FakeGenerator())
    monkeypatch.setattr(
        qdrant_store_module,
        "create_qdrant_client",
        lambda settings=None: QdrantClient(location=":memory:"),
    )
    startup._runtime.clear()

    with patch.object(QdrantVectorStore, "build_schema", return_value=False):
        runtime = startup.init_app(force=True)
    assert runtime["catalog_status"] == "incomplete"
    assert runtime["index_complete"] is False