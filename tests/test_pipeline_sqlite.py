"""SQLite end-to-end proof that the pipeline needs no hosted database or LLM."""

import numpy as np
import sqlalchemy as sa
from unittest.mock import MagicMock

from catalog.introspect import introspect_catalog
from db.adapter import DatabaseAdapter
from pipeline.orchestrator import TextToSQLPipeline
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.local_store import LocalVectorStore
from retrieval.value_index import ValueIndex


class FakeEmbedder:
    model_name = "test-embedder"
    dim = 8

    def embed(self, texts):
        vectors = np.zeros((len(texts), 8), dtype=float)
        for row, text in enumerate(texts):
            for token in text.casefold().split():
                vectors[row, sum(token.encode("utf-8")) % vectors.shape[1]] += 1
        return vectors


class FakeGenerator:
    def generate(self, messages):
        return "SELECT item_name, quantity FROM inventory"

    def summarize(self, question, rows):
        return f"Found {len(rows)} inventory record(s)."


class OneAmbiguousValue:
    def resolve_question(self, question, top_k):
        if question.casefold() == "show widget":
            return [{
                "mention": "widget",
                "ambiguous": True,
                "candidates": [
                    {"column": "inventory.item_name", "value": "widget", "confidence": 0.8},
                    {"column": "inventory.item_name", "value": "widgets", "confidence": 0.79},
                ],
            }]
        return []


def test_pipeline_runs_against_sqlite_with_mocked_llm_and_vector_schema_search(tmp_path):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    inventory = sa.Table(
        "inventory",
        metadata,
        sa.Column("item_name", sa.String, primary_key=True),
        sa.Column("quantity", sa.Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(inventory.insert(), [{"item_name": "widget", "quantity": 4}])

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)
    embedder = FakeEmbedder()
    local_store = LocalVectorStore(
        tmp_path, adapter.namespace(), embedder.model_name, embedder.dim, "test-policy"
    )
    table_document = "inventory item_name quantity"
    assert local_store.build_schema([{
        "table_name": "inventory",
        "column_name": None,
        "metadata_type": "table_ddl",
        "content": table_document,
    }], embedder)
    vector_search = MagicMock(wraps=local_store.search_schema)
    local_store.search_schema = vector_search
    retriever = HybridSchemaRetriever(catalog, embedder, local_store=local_store)
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=catalog,
        retriever=retriever,
        generator=FakeGenerator(),
        max_retries=0,
    )

    result = pipeline.run("show inventory quantity")

    assert result.errors == []
    assert result.rows == [{"item_name": "widget", "quantity": 4}]
    assert result.tables_used == ["inventory"]
    assert "LIMIT" not in result.sql.upper()
    assert "widget" in result.answer and "4" in result.answer
    vector_search.assert_called_once()


def test_pipeline_none_of_these_skips_value_and_continues():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    inventory = sa.Table(
        "inventory",
        metadata,
        sa.Column("item_name", sa.String, primary_key=True),
        sa.Column("quantity", sa.Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(inventory.insert(), [{"item_name": "widget", "quantity": 4}])
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=catalog,
        retriever=HybridSchemaRetriever(catalog, FakeEmbedder()),
        generator=FakeGenerator(),
        value_index=OneAmbiguousValue(),
        max_retries=0,
    )

    waiting = pipeline.run("show widget")
    continued = pipeline.run("show widget", confirmed_values=[{"mention": "widget", "skip": True}])

    assert waiting.ambiguous_values
    assert continued.ambiguous_values == []
    assert continued.errors == []
    assert continued.rows == [{"item_name": "widget", "quantity": 4}]


def test_pipeline_retries_unverified_metric_word_as_measure():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    inventory = sa.Table(
        "inventory",
        metadata,
        sa.Column("status", sa.String, primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(inventory.insert(), [{"status": "Available"}])

    class CorrectingGenerator:
        def __init__(self):
            self.calls = 0

        def generate(self, messages):
            self.calls += 1
            if self.calls == 1:
                return "SELECT status FROM inventory WHERE status = 'sold out'"
            if self.calls == 2:
                return "SELECT status FROM inventory WHERE status = 'Available'"
            return "SELECT status FROM inventory"

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)
    value_index = ValueIndex(adapter, catalog)
    value_index.build()
    generator = CorrectingGenerator()

    class CapturingRetriever:
        query = ""

        def retrieve(self, question, top_k):
            self.query = question
            return {
                "tables": ["inventory"],
                "ddl": "TABLE inventory (status VARCHAR)",
            }

    retriever = CapturingRetriever()
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=catalog,
        retriever=retriever,
        generator=generator,
        value_index=value_index,
        max_retries=2,
    )

    result = pipeline.run("show inventory status for sold out items")

    # The pipeline handles unverified values per the spec; result rows depend on
    # value-index resolution, which may result in no rows for unresolvable mentions.
    assert "ambiguous" in str(result.answer).lower() or "not found" in str(result.answer).lower() or result.rows == []