"""Fake-only tests for Step 4 query preparation; no Streamlit or Groq calls."""

from __future__ import annotations

from typing import Any

import pytest

import pipeline.query_workflow as workflow
from pipeline.query_workflow import (
    QueryNeedsNarrowerQuestion,
    QueryNeedsTableClarification,
    QueryReady,
    QueryRetrievalFailed,
    prepare_query,
)
from retrieval.qdrant_retriever import RetrievalResult
from retrieval.qdrant_store import QdrantStorageError
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo


class FakeEmbedder:
    model_name = "fake-model-384"
    dim = 384

    def __init__(self):
        self.questions = []

    def embed_single(self, text: str) -> list[float]:
        self.questions.append(text)
        return [0.25] + [0.0] * 383


class FakeStore:
    def __init__(self, *, failure: Exception | None = None, typed_hits=None):
        self.failure = failure
        self.typed_hits = typed_hits or {
            "table": [{"table_name": "records", "similarity": 0.9}],
            "column": [],
            "relationship": [],
            "master_value": [{
                "table_name": "categories",
                "column_name": "name",
                "value": "Qdrant-only value",
                "content": "Qdrant-only value",
                "similarity": 0.99,
            }],
        }
        self.calls = []

    def _search(self, document_type, vector, *args):
        self.calls.append((document_type, list(vector)))
        if self.failure:
            raise self.failure
        return self.typed_hits.get(document_type, [])

    def search_table(self, vector, *args):
        return self._search("table", vector, *args)

    def search_column(self, vector, *args):
        return self._search("column", vector, *args)

    def search_relationship(self, vector, *args):
        return self._search("relationship", vector, *args)

    def search_master_value(self, vector, *args):
        return self._search("master_value", vector, *args)


def _schema() -> SchemaMetadata:
    return SchemaMetadata({
        "records": TableInfo(
            "records",
            "Private table description",
            [
                ColumnInfo("record_id", "INTEGER", is_primary_key=True),
                ColumnInfo("status", "TEXT", comment="Private status comment"),
            ],
            ["record_id"],
            [],
        ),
        "categories": TableInfo(
            "categories",
            "Category description",
            [ColumnInfo("name", "TEXT", comment="Category comment")],
            [],
            [],
        ),
    }, dialect="sqlite")


def _value_documents() -> list[dict[str, Any]]:
    return [
        {
            "table_name": "categories",
            "column_name": "name",
            "value": "Electronics",
            "content": "categories name Electronics",
        },
        {
            "table_name": "categories",
            "column_name": "name",
            "value": "Electrical",
            "content": "categories name Electrical",
        },
    ]


def _prepare(question: str, **overrides):
    embedder = FakeEmbedder()
    store = FakeStore()
    arguments = {
        "question": question,
        "metadata": _schema(),
        "value_documents": _value_documents(),
        "embedder": embedder,
        "qdrant_store": store,
        "tenant_id": "tenant",
        "dataset_id": "dataset",
        "dataset_metadata_path": "dataset.json",
    }
    arguments.update(overrides)
    return prepare_query(**arguments), embedder, arguments["qdrant_store"]


def test_prepare_query_prefers_case_insensitive_exact_value():
    store = FakeStore(typed_hits={
        "table": [{"table_name": "records", "similarity": 0.9}],
        "column": [],
        "relationship": [],
        "master_value": [{
            "table_name": "categories",
            "column_name": "name",
            "value": "Qdrant-only value",
            "content": "Qdrant-only value",
            "similarity": 0.1,
        }],
    })
    outcome, embedder, _ = _prepare(
        "ELECTRONICS", qdrant_store=store, selected_k=1
    )

    assert isinstance(outcome, QueryReady)
    assert embedder.questions == ["ELECTRONICS"]
    assert [call[0] for call in store.calls] == [
        "table", "column", "relationship", "master_value"
    ]
    assert [match["value"] for match in outcome.value_matches] == ["Electronics"]
    assert all(match["match_type"] == "exact" for match in outcome.value_matches)
    assert "Electronics" in outcome.context
    assert "Qdrant-only value" not in outcome.context
    assert outcome.retrieval.tables[0] == "categories"


def test_prepare_query_labels_fuzzy_match_without_forcing_a_table():
    outcome, _, _ = _prepare("Electroncis")
    control_outcome, _, _ = _prepare("Electroncis", value_documents=[])

    assert isinstance(outcome, QueryReady)
    assert outcome.value_matches
    assert all(match["match_type"] == "fuzzy_text" for match in outcome.value_matches)
    assert all(match["label"] == "possible match, unconfirmed" for match in outcome.value_matches)
    assert all(match["forced_table"] is False for match in outcome.value_matches)
    assert "possible match, unconfirmed" in outcome.context
    assert outcome.retrieval.tables == control_outcome.retrieval.tables


def test_context_filters_blocked_masked_and_omits_descriptions_and_comments():
    metadata = SchemaMetadata({
        "records": TableInfo(
            "records",
            "Secret table description",
            [
                ColumnInfo("status", "TEXT", comment="Secret column comment"),
                ColumnInfo("created_at", "TIMESTAMP"),
                ColumnInfo("category_id", "INTEGER", is_foreign_key=True),
                ColumnInfo("email", "TEXT"),
                ColumnInfo("internal_label", "TEXT"),
            ],
            [],
            [{
                "local_cols": ["category_id"],
                "remote_table": "categories",
                "remote_cols": ["id"],
            }],
        ),
        "categories": TableInfo(
            "categories",
            "Category description",
            [ColumnInfo("id", "INTEGER"), ColumnInfo("name", "TEXT")],
            [],
            [],
        ),
    })
    outcome = prepare_query(
        question="active",
        metadata=metadata,
        value_documents=[],
        embedder=FakeEmbedder(),
        qdrant_store=FakeStore(),
        tenant_id="tenant",
        dataset_id="dataset",
        dataset_metadata_path="dataset.json",
        sensitive_filter={"force_mask": ["records.internal_label"]},
    )

    assert isinstance(outcome, QueryReady)
    assert "status: TEXT" in outcome.context
    assert "created_at: TIMESTAMP" in outcome.context
    assert "category_id: INTEGER" in outcome.context
    assert "records.category_id -> categories.id" in outcome.context
    assert "email" not in outcome.context
    assert "internal_label" not in outcome.context
    assert "Secret table description" not in outcome.context
    assert "Secret column comment" not in outcome.context


@pytest.mark.parametrize(
    ("retrieval_result", "outcome_type", "expected_status"),
    [
        (RetrievalResult(tables=["records"], used_qdrant=True, truncated=True), QueryNeedsNarrowerQuestion, "truncated"),
        (RetrievalResult(tables=["records", "categories"], used_qdrant=True, ambiguity_flag=True), QueryNeedsTableClarification, "ambiguity"),
    ],
)
def test_truncated_and_ambiguous_results_stop_before_context_builder(
    monkeypatch, retrieval_result, outcome_type, expected_status
):
    monkeypatch.setattr(workflow, "retrieve", lambda *args, **kwargs: retrieval_result)
    monkeypatch.setattr(
        workflow,
        "build_query_context",
        lambda *args, **kwargs: pytest.fail("context builder must not run"),
    )
    embedder = FakeEmbedder()

    outcome = prepare_query(
        question="active",
        metadata=_schema(),
        value_documents=_value_documents(),
        embedder=embedder,
        qdrant_store=FakeStore(),
        tenant_id="tenant",
        dataset_id="dataset",
        dataset_metadata_path="dataset.json",
    )

    assert isinstance(outcome, outcome_type)
    assert outcome.status == expected_status
    assert embedder.questions == ["active"]


def test_qdrant_fallback_returns_retrieval_failed_outcome():
    outcome, _, store = _prepare(
        "active",
        qdrant_store=FakeStore(failure=QdrantStorageError("offline")),
    )

    assert isinstance(outcome, QueryRetrievalFailed)
    assert outcome.status == "retrieval_failed"
    assert [call[0] for call in store.calls] == ["table"]
