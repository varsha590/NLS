"""Unit tests for Phase 0 bug fixes."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sqlalchemy as sa

from config.settings import Settings
from core import startup
from db.adapter import DatabaseAdapter, DatabaseUnavailableError, EmbeddingStore
from pipeline.orchestrator import PipelineResult, TextToSQLPipeline
from retrieval.examples import ExampleStore
from retrieval.schema_retriever import HybridSchemaRetriever, retrieve_schema
from retrieval.value_index import ValueIndex
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from validation.validator import ValidationError, ValueSafetyError, validate_sql


# ---------------------------------------------------------------------------
# Test Helpers & Fakes
# ---------------------------------------------------------------------------

class FakeEmbedder:
    model_name = "test-embedder"

    def __init__(self, model_name: str = "test-embedder"):
        self.model_name = model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.ones((len(texts), 4), dtype=float)


class FakeGenerator:
    def __init__(self, sql: str = "SELECT 1"):
        self.sql = sql

    def generate(self, messages: list[dict]) -> str:
        return self.sql


# ---------------------------------------------------------------------------
# 0a: Unchanged-vector NULL overwrite & repair NULL vectors
# ---------------------------------------------------------------------------

def test_0a_upsert_schema_and_value_preserve_existing_vectors():
    """Verify that upsert_schema / upsert_value generate COALESCE SQL when embedding is None."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    adapter.get_dialect = MagicMock(return_value="postgresql")

    mock_conn = MagicMock()
    adapter.connect = MagicMock(return_value=mock_conn)
    store = EmbeddingStore(adapter, namespace="test_ns")

    # 1. upsert_schema with embedding=None
    store.upsert_schema("users", "email", "column_description", "doc text", "hash123", None)
    call_args = mock_conn.execute.call_args[0]
    sql_text = str(call_args[0])
    assert "COALESCE" in sql_text
    assert "system_schema_embeddings.embedding" in sql_text

    # 2. upsert_value with embedding=None
    store.upsert_value("users", "status", "active", "hash456", None)
    call_args = mock_conn.execute.call_args[0]
    sql_text = str(call_args[0])
    assert "COALESCE" in sql_text
    assert "system_value_embeddings.embedding" in sql_text


def test_0a_build_schema_embeddings_repairs_missing_vectors():
    """Verify build_schema_embeddings re-embeds rows whose hash matches but vector is missing."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    adapter.get_dialect = MagicMock(return_value="postgresql")

    mock_conn = MagicMock()
    adapter.connect = MagicMock(return_value=mock_conn)
    store = EmbeddingStore(adapter, namespace="test_ns")

    metadata = SchemaMetadata(
        tables={
            "users": TableInfo(
                name="users",
                description="users table",
                columns=[ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True)],
                primary_key_names=["id"],
                foreign_keys=[],
            )
        }
    )

    embedder = FakeEmbedder()
    embed_spy = MagicMock(wraps=embedder.embed)
    embedder.embed = embed_spy

    # Existing row has matching content_hash, but vector_missing is True
    from schema.documents import build_table_document
    table_doc = build_table_document(metadata.tables["users"])
    import hashlib
    content_hash = hashlib.sha256(table_doc.encode("utf-8")).hexdigest()

    existing_rows = [
        {
            "table_name": "users",
            "column_name": None,
            "metadata_type": "table_ddl",
            "content_hash": content_hash,
            "vector_missing": True,  # NULL vector in DB
        }
    ]
    store.get_all_schema_embeddings = MagicMock(return_value=existing_rows)
    store.upsert_schema = MagicMock()
    store.prune_schema = MagicMock()

    success = store.build_schema_embeddings(metadata, embedder=embedder)
    assert success is True
    # Must have called embed because vector was missing even though hash matched
    assert embed_spy.called


# ---------------------------------------------------------------------------
# 0b: ValueIndex high-cardinality calls embedding_store.search_values
# ---------------------------------------------------------------------------

def test_0b_value_index_high_cardinality_calls_embedding_store_without_attribute_error():
    """Verify high-cardinality lookup calls embedding_store.search_values without raising AttributeError."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)

    metadata = SchemaMetadata(
        tables={
            "customers": TableInfo(
                name="customers",
                description="customers",
                columns=[ColumnInfo(name="name", data_type="VARCHAR(255)")],
                primary_key_names=[],
                foreign_keys=[],
            )
        }
    )

    embedder = FakeEmbedder()
    mock_store = MagicMock(spec=EmbeddingStore)
    mock_store.search_values.return_value = [
        {"table_name": "customers", "column_name": "name", "value": "Alice Smith"}
    ]

    vindex = ValueIndex(
        adapter=adapter,
        metadata=metadata,
        cardinality_threshold=10,
        embedder=embedder,
        embedding_store=mock_store,
    )
    # Simulate customers.name classified as large column
    vindex.large_columns.add("customers.name")

    # This previously failed with AttributeError: 'DatabaseAdapter' object has no attribute 'search_values'
    candidates = vindex._score_candidates("Alice", column="customers.name", top_k=5)
    assert len(candidates) > 0
    assert candidates[0]["value"] == "Alice Smith"
    mock_store.search_values.assert_called_once()


# ---------------------------------------------------------------------------
# 0c: Schema retriever associates scores by schema-qualified table key
# ---------------------------------------------------------------------------

def test_0c_schema_retriever_multi_schema_same_table_name():
    """Verify two schemas with the same table name do not cross-assign semantic scores."""
    metadata = SchemaMetadata(
        tables={
            "sales.orders": TableInfo(
                name="sales.orders",
                description="sales orders table",
                columns=[ColumnInfo(name="order_id", data_type="INTEGER", is_primary_key=True)],
                primary_key_names=["order_id"],
                foreign_keys=[],
            ),
            "archive.orders": TableInfo(
                name="archive.orders",
                description="archived historical orders",
                columns=[ColumnInfo(name="order_id", data_type="INTEGER", is_primary_key=True)],
                primary_key_names=["order_id"],
                foreign_keys=[],
            ),
        }
    )

    embedder = FakeEmbedder()
    mock_store = MagicMock(spec=EmbeddingStore)
    # Search returns high similarity ONLY for sales.orders
    mock_store.search_schema.return_value = [
        {"table_name": "sales.orders", "similarity": 0.95}
    ]

    retriever = HybridSchemaRetriever(metadata, embedder, embedding_store=mock_store)
    result = retriever.retrieve("recent sales orders", top_k=2)

    scores = result["scores"]
    assert scores["sales.orders"] > scores["archive.orders"]
    # archive.orders must NOT receive sales.orders's 0.95 score
    # (previously it could via positional indexing or bare name collision)
    assert scores["archive.orders"] < 0.5


# ---------------------------------------------------------------------------
# 0d: Missing EmbeddingModel import in retrieve_schema & duplicate import
# ---------------------------------------------------------------------------

def test_0d_retrieve_schema_imports_embedding_model():
    """Verify retrieve_schema executes without NameError: name 'EmbeddingModel' is not defined."""
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")

    with patch("retrieval.schema_retriever.EmbeddingModel", FakeEmbedder):
        result = retrieve_schema(engine, "find items", top_k=1)
        assert "items" in result["tables"]


# ---------------------------------------------------------------------------
# 0e: Only offer saving example when SQL passed validation AND execution
# ---------------------------------------------------------------------------

def test_0e_validation_error_clears_result_sql():
    """ValidationError must clear result.sql so unverified SQL cannot be saved."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    metadata = SchemaMetadata(tables={})
    retriever = MagicMock()
    retriever.retrieve.return_value = {"tables": ["t"], "ddl": "TABLE t (id INT)"}

    # Generator generates invalid mutating SQL
    generator = FakeGenerator("DROP TABLE t")
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=metadata,
        retriever=retriever,
        generator=generator,
    )

    result = pipeline.run("drop the table")
    assert result.sql == ""
    assert len(result.errors) > 0


def test_0e_execution_failure_clears_result_sql():
    """Database execution error must clear result.sql."""
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer))
    metadata.create_all(engine)

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    meta = SchemaMetadata(
        tables={
            "users": TableInfo(
                name="users",
                description="users",
                columns=[ColumnInfo(name="id", data_type="INTEGER")],
                primary_key_names=[],
                foreign_keys=[],
            )
        }
    )
    retriever = MagicMock()
    retriever.retrieve.return_value = {"tables": ["users"], "ddl": "TABLE users (id INT)"}
    generator = FakeGenerator("SELECT id FROM users")

    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=meta,
        retriever=retriever,
        generator=generator,
    )

    # Force adapter execution failure
    with patch.object(adapter, "run_readonly_query", side_effect=DatabaseUnavailableError("Simulated DB failure")):
        result = pipeline.run("get users")
        assert result.sql == ""


def test_0e_upsert_example_reports_failure_to_caller():
    """upsert_example and ExampleStore.save return False on persistence failure."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    # SQLite dialect does not persist examples to target Postgres
    example_store = ExampleStore(None, adapter)
    saved = example_store.save("question", "SELECT 1")
    assert saved is False


# ---------------------------------------------------------------------------
# 0f: upsert_value must not put raw values in log extras
# ---------------------------------------------------------------------------

def test_0f_upsert_value_does_not_log_raw_value(caplog):
    """Verify that when upsert_value fails, the raw value is never included in log extras or messages."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    adapter.get_dialect = MagicMock(return_value="postgresql")

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sa.exc.SQLAlchemyError("DB error")
    adapter.connect = MagicMock(return_value=mock_conn)
    store = EmbeddingStore(adapter, namespace="test_ns")

    secret_raw_value = "SUPER_SECRET_SSN_12345"
    with caplog.at_level(logging.ERROR):
        store.upsert_value("users", "ssn", secret_raw_value, "hash123", [0.1, 0.2])

    assert secret_raw_value not in caplog.text
    for record in caplog.records:
        extra_dict = getattr(record, "__dict__", {})
        assert secret_raw_value not in str(extra_dict.get("extra", {}))
        assert secret_raw_value not in str(extra_dict.get("value", ""))


# ---------------------------------------------------------------------------
# 0g: Literal validation restricts column search to used tables
# ---------------------------------------------------------------------------

def test_0g_literal_validation_restricts_to_used_tables():
    """Literal validation resolves unqualified columns only against tables in the query."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)

    metadata = SchemaMetadata(
        tables={
            "accounts": TableInfo(
                name="accounts",
                description="accounts table",
                columns=[
                    ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True),
                    ColumnInfo(name="status", data_type="VARCHAR(50)"),
                ],
                primary_key_names=["id"],
                foreign_keys=[],
            ),
            "orders": TableInfo(
                name="orders",
                description="orders table",
                columns=[
                    ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True),
                    ColumnInfo(name="status", data_type="VARCHAR(50)"),
                ],
                primary_key_names=["id"],
                foreign_keys=[],
            ),
        }
    )

    vindex = MagicMock(spec=ValueIndex)
    # accounts.status has 'active'
    # orders.status does NOT have 'active' (has 'pending', 'shipped')
    vindex.values = {
        "accounts.status": ["active", "closed"],
        "orders.status": ["pending", "shipped"],
    }
    vindex.ambiguous_gap = 0.08
    vindex.max_candidates = 5

    # Query uses ONLY accounts. Literal 'active' is valid for accounts.status.
    # If it searched the whole catalog and picked orders.status first, it would fail.
    sql = "SELECT id FROM accounts WHERE status = 'active'"
    validated = validate_sql(
        sql,
        metadata=metadata,
        dialect="sqlite",
        allowed_tables={"accounts"},
        adapter=adapter,
        value_index=vindex,
    )
    assert "accounts" in validated


# ---------------------------------------------------------------------------
# 0h: Index build errors are surfaced as "incomplete"
# ---------------------------------------------------------------------------

def test_0h_partial_index_surfaces_incomplete_state(tmp_path, monkeypatch):
    """When schema or value embedding build fails, catalog_status is 'incomplete'."""
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("items", metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(engine)

    monkeypatch.setattr(
        startup.Settings,
        "from_env",
        lambda: Settings(
            database_url="sqlite:///:memory:",
            groq_api_key="",
            llm_model="mock",
            embedding_model="mock",
            vector_store_path=str(tmp_path),
            schema_top_k=4,
            value_top_k=3,
            max_rows=20,
            query_timeout_seconds=5,
            max_retries=1,
            allowed_schemas=(),
            excluded_tables=(),
            value_cardinality_threshold=10,
        ),
    )
    monkeypatch.setattr(
        startup,
        "DatabaseAdapter",
        lambda db_url, timeout: DatabaseAdapter(db_url, timeout, engine=engine),
    )
    monkeypatch.setattr(startup, "EmbeddingModel", FakeEmbedder)

    # Force build_schema_embeddings to report failure (return False)
    with patch.object(EmbeddingStore, "build_schema_embeddings", return_value=False):
        runtime = startup.init_app(force=True)
        assert runtime["catalog_status"] == "incomplete"
        assert runtime["index_complete"] is False
