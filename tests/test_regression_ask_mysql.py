"""Regression test: ask_question entry point with mysql-dialect dataset."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ask import ask_question
from ingestion.datasets import DatasetRegistry
from schema.metadata import SchemaMetadata


def test_ask_mysql_dataset_validated():
    """Goes through the same entry point the UI uses for a mysql dataset."""
    dataset_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "datasets",
        "37a8eec1ce19687d132fe290",
        "66793aca-d3cd-5832-bb37-f8449695106a",
    )
    if not os.path.exists(dataset_dir):
        pytest.skip("munibigiri dataset not available")

    schema = DatasetRegistry("datasets").load_schema(
        "default", "66793aca-d3cd-5832-bb37-f8449695106a"
    )
    assert schema.dialect == "mysql"

    value_documents = DatasetRegistry("datasets").load_value_documents(
        "default", "66793aca-d3cd-5832-bb37-f8449695106a"
    )

    # Mock embedder
    embedder = type("obj", (object,), {"model_name": "test", "dim": 384})()

    # Mock qdrant store with client attribute (not None to pass the check)
    class MockQdrant:
        client = object()

    qdrant_store = MockQdrant()

    result = ask_question(
        "Show me all cities",
        schema,
        value_documents,
        embedder,
        qdrant_store,
        "default",
        "66793aca-d3cd-5832-bb37-f8449695106a",
        "datasets",
    )

    assert result.outcome == "validated", f"Expected 'validated', got '{result.outcome}': {result.message}"
    assert "Running queries is not available yet" not in result.message
