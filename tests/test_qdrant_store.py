"""Local/in-memory Qdrant storage contract tests."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from config.settings import Settings
from ingestion.datasets import DatasetRegistry
from retrieval.dataset_indexer import index_registered_dataset
from retrieval import embeddings as embeddings_module
from retrieval.qdrant_store import (
    DEFAULT_COLLECTION,
    QdrantStorageError,
    QdrantVectorStore,
    deterministic_point_id,
    make_dataset_hash,
)


VECTOR = [1.0] + [0.0] * 383


def _client() -> QdrantClient:
    return QdrantClient(location=":memory:")


def _dataset_metadata(path: Path, tenant: str, dataset: str) -> Path:
    metadata_path = path / f"{tenant}-{dataset}.json"
    metadata_path.write_text(json.dumps({
        "tenant_id": tenant,
        "dataset_id": dataset,
        "indexed": False,
        "file_sha256": "source-file-hash",
    }))
    return metadata_path


def _document(table: str, content: str, column: str | None = None) -> dict[str, Any]:
    return {
        "document_type": "table" if column is None else "column",
        "table_name": table,
        "column_name": column,
        "content": content,
    }


def _value_document(table: str, column: str, value: str) -> dict[str, Any]:
    return {
        "document_type": "master_value",
        "table_name": table,
        "column_name": column,
        "value": value,
        "content": f"{table} {column} {value}",
    }


def _make_store(client: QdrantClient) -> QdrantVectorStore:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return QdrantVectorStore(client=client)


def test_collection_creation_is_idempotent_and_rejects_vector_mismatch():
    client = _client()
    first = _make_store(client)
    second = _make_store(client)
    assert first.collection_name == second.collection_name

    incompatible = QdrantClient(location=":memory:")
    incompatible.create_collection(
        collection_name="nls_documents",
        vectors_config=models.VectorParams(size=385, distance=models.Distance.COSINE),
    )
    with pytest.raises(QdrantStorageError, match="incompatible vector size or distance"):
        _make_store(incompatible)

    wrong_distance = QdrantClient(location=":memory:")
    wrong_distance.create_collection(
        collection_name="nls_documents",
        vectors_config=models.VectorParams(size=384, distance=models.Distance.DOT),
    )
    with pytest.raises(QdrantStorageError, match="incompatible vector size or distance"):
        _make_store(wrong_distance)


@pytest.mark.parametrize(
    ("dialect_override", "model_name"),
    [(None, "model-a"), ("mysql", "model-a"), (None, "model-b")],
)
def test_dataset_hash_includes_override_and_embedding_model(dialect_override, model_name):
    assert make_dataset_hash(b"same-file", dialect_override, model_name)
    base = make_dataset_hash(b"same-file", None, "model-a")
    assert make_dataset_hash(b"same-file", "mysql", "model-a") != base
    assert make_dataset_hash(b"same-file", None, "model-b") != base
    assert make_dataset_hash(b"changed-file", None, "model-a") != base


def test_point_ids_are_stable_and_separate_values():
    first = deterministic_point_id("tenant-a", "dataset-a", "master_value", "regions", "name", "North")
    assert first == deterministic_point_id("tenant-a", "dataset-a", "master_value", "regions", "name", "North")
    assert first != deterministic_point_id("tenant-a", "dataset-a", "master_value", "regions", "name", "South")
    assert first != deterministic_point_id("tenant-b", "dataset-a", "master_value", "regions", "name", "North")


def test_reindex_upserts_then_removes_only_stale_points_in_dataset_scope(tmp_path):
    store = _make_store(_client())
    metadata_a1 = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    metadata_a2 = _dataset_metadata(tmp_path, "tenant-a", "dataset-b")
    metadata_b1 = _dataset_metadata(tmp_path, "tenant-b", "dataset-a")

    store.reindex_dataset(
        "tenant-a", "dataset-a", [_value_document("regions", "name", "North"), _value_document("regions", "name", "South")],
        [VECTOR, VECTOR], metadata_a1, "hash-a1", "model-384", 384,
    )
    store.reindex_dataset(
        "tenant-a", "dataset-b", [_document("regions", "Other dataset")],
        [VECTOR], metadata_a2, "hash-a2", "model-384", 384,
    )
    store.reindex_dataset(
        "tenant-b", "dataset-a", [_document("regions", "Other tenant")],
        [VECTOR], metadata_b1, "hash-b1", "model-384", 384,
    )

    calls: list[str] = []
    client = store.client
    class OrderedClient:
        def __getattr__(self, name):
            return getattr(client, name)

        def upsert(self, *args, **kwargs):
            calls.append("upsert")
            return client.upsert(*args, **kwargs)

        def delete(self, *args, **kwargs):
            calls.append("delete")
            return client.delete(*args, **kwargs)

    store.client = OrderedClient()
    store.reindex_dataset(
        "tenant-a",
        "dataset-a",
        [_value_document("regions", "name", "North"), _value_document("regions", "name", "East")],
        [VECTOR, VECTOR],
        metadata_a1,
        "hash-a1-next",
        "model-384",
        384,
    )
    assert calls == ["upsert", "delete"]
    assert {item["value"] for item in store.search(
        VECTOR, "tenant-a", "dataset-a", 10,
        dataset_metadata_path=metadata_a1, embedding_model_name="model-384", dimension=384,
    )} == {"North", "East"}
    assert [item["content"] for item in store.search(
        VECTOR, "tenant-a", "dataset-b", 10,
        dataset_metadata_path=metadata_a2, embedding_model_name="model-384", dimension=384,
    )] == ["Other dataset"]
    assert [item["content"] for item in store.search(
        VECTOR, "tenant-b", "dataset-a", 10,
        dataset_metadata_path=metadata_b1, embedding_model_name="model-384", dimension=384,
    )] == ["Other tenant"]
    committed = json.loads(metadata_a1.read_text())
    assert committed["dataset_hash"] == "hash-a1-next"
    assert committed["embedding_model_name"] == "model-384"
    assert committed["vector_dimension"] == 384
    assert committed["indexed"] is True


def test_failed_upsert_or_stale_delete_never_commits_index_metadata(tmp_path):
    store = _make_store(_client())
    metadata_path = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    client = store.client

    class FailingClient:
        def __init__(self, failure):
            self.failure = failure

        def __getattr__(self, name):
            return getattr(client, name)

        def upsert(self, *args, **kwargs):
            if self.failure == "upsert":
                raise RuntimeError("credentials and endpoint must not escape")
            return client.upsert(*args, **kwargs)

        def delete(self, *args, **kwargs):
            if self.failure == "delete":
                raise RuntimeError("credentials and endpoint must not escape")
            return client.delete(*args, **kwargs)

    for failure in ("upsert", "delete"):
        store.client = FailingClient(failure)
        metadata_path.write_text(json.dumps({
            "tenant_id": "tenant-a",
            "dataset_id": "dataset-a",
            "indexed": False,
        }))
        with pytest.raises(QdrantStorageError) as error:
            store.reindex_dataset(
                "tenant-a", "dataset-a", [_document("regions", "North")],
                [VECTOR], metadata_path, "secret-hash", "model-384", 384,
            )
        assert "credentials" not in str(error.value)
        assert "endpoint" not in str(error.value)
        persisted = json.loads(metadata_path.read_text())
        assert persisted["indexed"] is False
        assert "dataset_hash" not in persisted
        assert "embedding_model_name" not in persisted
        assert "vector_dimension" not in persisted
    store.client = client


def test_search_requires_both_scope_values_and_filters_results(tmp_path):
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    path_b = _dataset_metadata(tmp_path, "tenant-b", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "tenant A")], [VECTOR], path_a, "a", "m", 384)
    store.reindex_dataset("tenant-b", "dataset-a", [_document("t", "tenant B")], [VECTOR], path_b, "b", "m", 384)
    assert [item["content"] for item in store.search(
        VECTOR, "tenant-a", "dataset-a", 5,
        dataset_metadata_path=path_a, embedding_model_name="m", dimension=384,
    )] == ["tenant A"]
    assert [item["content"] for item in store.search(
        VECTOR, "tenant-b", "dataset-a", 5,
        dataset_metadata_path=path_b, embedding_model_name="m", dimension=384,
    )] == ["tenant B"]
    with pytest.raises(ValueError, match="tenant_id and dataset_id"):
        store.search(
            VECTOR, "", "dataset-a", 5,
            dataset_metadata_path=path_a, embedding_model_name="m", dimension=384,
        )


def test_search_refuses_unindexed_or_changed_embedding_metadata(tmp_path):
    store = _make_store(_client())
    metadata_path = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    with pytest.raises(QdrantStorageError, match="not indexed"):
        store.search(
            VECTOR, "tenant-a", "dataset-a", 5,
            dataset_metadata_path=metadata_path, embedding_model_name="model-384", dimension=384,
        )
    store.reindex_dataset(
        "tenant-a", "dataset-a", [_document("regions", "North")],
        [VECTOR], metadata_path, "hash", "model-384", 384,
    )
    with pytest.raises(QdrantStorageError, match="model or dimension"):
        store.search(
            VECTOR, "tenant-a", "dataset-a", 5,
            dataset_metadata_path=metadata_path, embedding_model_name="different-model", dimension=384,
        )
    with pytest.raises(QdrantStorageError, match="384 dimensions"):
        store.search(
            VECTOR, "tenant-a", "dataset-a", 5,
            dataset_metadata_path=metadata_path, embedding_model_name="model-384", dimension=768,
        )


def test_dataset_indexer_embeds_tables_columns_relationships_and_values(tmp_path):
    registry = DatasetRegistry(tmp_path / "datasets")
    result = registry.register(
        "reference.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, label TEXT);"
        b"CREATE TABLE offices (id INTEGER PRIMARY KEY, region_id INTEGER, name TEXT, "
        b"FOREIGN KEY (region_id) REFERENCES regions(id));"
        b"INSERT INTO regions VALUES (1, 'North');",
        tenant_id="tenant-indexer",
        embedding_model_name="fake-384",
    )

    class FakeEmbedder:
        model_name = "fake-384"
        dim = 384

        def embed(self, texts):
            return np.tile(np.asarray([[1.0] + [0.0] * 383]), (len(texts), 1))

    store = _make_store(_client())
    count = index_registered_dataset(
        registry,
        store,
        "tenant-indexer",
        result["dataset_id"],
        result["dataset_hash"],
        FakeEmbedder(),
    )
    metadata_path = registry.dataset_directory("tenant-indexer", result["dataset_id"]) / "dataset.json"
    payload = json.loads(metadata_path.read_text())
    assert payload["indexed"] is True
    assert payload["dataset_hash"] == result["dataset_hash"]
    assert payload["embedding_model_name"] == "fake-384"
    assert payload["vector_dimension"] == 384
    assert count > 4
    search = store.search(
        VECTOR,
        "tenant-indexer",
        result["dataset_id"],
        100,
        dataset_metadata_path=metadata_path,
        embedding_model_name="fake-384",
        dimension=384,
    )
    assert {item["document_type"] for item in search} >= {
        "table", "column", "relationship", "master_value"
    }


def test_sentence_transformer_model_must_return_384_dimensions(monkeypatch):
    class WrongDimensionModel:
        def __init__(self, model_name):
            self.model_name = model_name

        def get_sentence_embedding_dimension(self):
            return 768

    monkeypatch.setattr(embeddings_module, "SentenceTransformer", WrongDimensionModel)
    with pytest.raises(ValueError, match="returns 768 dimensions.*requires 384"):
        embeddings_module.EmbeddingModel("wrong-dimension-model")


def test_settings_hide_qdrant_url_and_api_key_from_repr(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://private-host:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "secret-qdrant-key")
    settings = Settings.from_env()
    assert settings.qdrant_url == "http://private-host:6333"
    assert settings.qdrant_api_key == "secret-qdrant-key"
    assert "private-host" not in repr(settings)
    assert "secret-qdrant-key" not in repr(settings)


@pytest.mark.integration
def test_docker_qdrant_isolates_two_tenants_and_two_datasets(tmp_path):
    import os

    endpoint = os.getenv("QDRANT_INTEGRATION_URL")
    if not endpoint:
        pytest.skip("Set QDRANT_INTEGRATION_URL to run Docker Qdrant integration coverage.")
    store = QdrantVectorStore(
        url=endpoint,
        api_key=os.getenv("QDRANT_API_KEY") or None,
        collection_name=os.getenv("QDRANT_COLLECTION", DEFAULT_COLLECTION),
    )
    scopes = [
        ("integration-tenant-a", "integration-dataset-a", "A/A"),
        ("integration-tenant-a", "integration-dataset-b", "A/B"),
        ("integration-tenant-b", "integration-dataset-a", "B/A"),
        ("integration-tenant-b", "integration-dataset-b", "B/B"),
    ]
    metadata_paths: dict[tuple[str, str], Path] = {}
    try:
        for tenant_id, dataset_id, content in scopes:
            metadata_path = _dataset_metadata(tmp_path, tenant_id, dataset_id)
            metadata_paths[(tenant_id, dataset_id)] = metadata_path
            store.reindex_dataset(
                tenant_id,
                dataset_id,
                [_document("integration_table", content)],
                [VECTOR],
                metadata_path,
                f"hash-{content}",
                "integration-model-384",
                384,
            )
        for tenant_id, dataset_id, expected in scopes:
            found = store.search(
                VECTOR,
                tenant_id,
                dataset_id,
                10,
                dataset_metadata_path=metadata_paths[(tenant_id, dataset_id)],
                embedding_model_name="integration-model-384",
                dimension=384,
            )
            assert [item["content"] for item in found] == [expected]
    finally:
        for tenant_id, dataset_id, _ in scopes:
            client_filter = models.Filter(must=[
                models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
                models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset_id)),
            ])
            store.client.delete(
                collection_name=store.collection_name,
                points_selector=client_filter,
                wait=True,
            )
        store.close()


def test_search_table_applies_tenant_and_dataset_filters(tmp_path):
    """Table search applies both tenant_id and dataset_id filters."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    path_b = _dataset_metadata(tmp_path, "tenant-b", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "tenant A table")], [VECTOR], path_a, "a", "m", 384)
    store.reindex_dataset("tenant-b", "dataset-a", [_document("t", "tenant B table")], [VECTOR], path_b, "b", "m", 384)

    # Tenant-a searching dataset-a should find "tenant A table"
    results = store.search_table(VECTOR, "tenant-a", "dataset-a", 5, path_a, "m", 384)
    assert [item["content"] for item in results] == ["tenant A table"]

    # Tenant-b searching dataset-a should find "tenant B table"
    results = store.search_table(VECTOR, "tenant-b", "dataset-a", 5, path_b, "m", 384)
    assert [item["content"] for item in results] == ["tenant B table"]

    # Wrong tenant/dataset should find nothing (scope mismatch)
    with pytest.raises(QdrantStorageError, match="scope does not match"):
        store.search_table(VECTOR, "tenant-c", "dataset-a", 5, path_a, "m", 384)


def test_search_column_applies_tenant_and_dataset_filters_and_correct_limit(tmp_path):
    """Column search applies filters and uses limit top_k * 3."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "col content")], [VECTOR], path_a, "a", "m", 384)

    # top_k=2 → limit should be 6
    results = store.search_column(VECTOR, "tenant-a", "dataset-a", 2, path_a, "m", 384)
    assert len(results) <= 6  # limit is top_k * 3 = 6

    # Wrong dataset should find nothing (scope mismatch)
    with pytest.raises(QdrantStorageError, match="scope does not match"):
        store.search_column(VECTOR, "tenant-a", "dataset-b", 2, path_a, "m", 384)


def test_search_relationship_applies_tenant_and_dataset_filters_and_correct_limit(tmp_path):
    """Relationship search applies filters and uses limit top_k * 2."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "rel content")], [VECTOR], path_a, "a", "m", 384)

    # top_k=2 → limit should be 4
    results = store.search_relationship(VECTOR, "tenant-a", "dataset-a", 2, path_a, "m", 384)
    assert len(results) <= 4  # limit is top_k * 2 = 4

    # Wrong dataset should find nothing (scope mismatch)
    with pytest.raises(QdrantStorageError, match="scope does not match"):
        store.search_relationship(VECTOR, "tenant-a", "dataset-b", 2, path_a, "m", 384)


def test_search_master_value_applies_tenant_and_dataset_filters_and_correct_limit(tmp_path):
    """Master value search applies filters and uses limit min(50, top_k * 2)."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_value_document("t", "c", "val")], [VECTOR], path_a, "a", "m", 384)

    # top_k=5 → limit should be min(50, 10) = 10
    results = store.search_master_value(VECTOR, "tenant-a", "dataset-a", 5, path_a, "m", 384)
    assert len(results) <= 10  # limit is min(50, top_k * 2) = 10

    # top_k=30 → limit should be min(50, 60) = 50
    results = store.search_master_value(VECTOR, "tenant-a", "dataset-a", 30, path_a, "m", 384)
    assert len(results) <= 50  # limit is min(50, top_k * 2) = 50

    # Wrong dataset should find nothing (scope mismatch)
    with pytest.raises(QdrantStorageError, match="scope does not match"):
        store.search_master_value(VECTOR, "tenant-a", "dataset-b", 5, path_a, "m", 384)


def test_metadata_mismatch_prevents_table_search(tmp_path):
    """Metadata model/dimension mismatch prevents table search."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "test")], [VECTOR], path_a, "a", "m", 384)

    # Wrong model name
    with pytest.raises(QdrantStorageError, match="model or dimension"):
        store.search_table(VECTOR, "tenant-a", "dataset-a", 5, path_a, "different-model", 384)

    # Wrong dimension
    with pytest.raises(QdrantStorageError, match="384 dimensions"):
        store.search_table(VECTOR, "tenant-a", "dataset-a", 5, path_a, "model-384", 768)


def test_metadata_mismatch_prevents_column_search(tmp_path):
    """Metadata mismatch prevents column search."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "test")], [VECTOR], path_a, "a", "m", 384)

    with pytest.raises(QdrantStorageError, match="model or dimension"):
        store.search_column(VECTOR, "tenant-a", "dataset-a", 5, path_a, "different-model", 384)

    with pytest.raises(QdrantStorageError, match="384 dimensions"):
        store.search_column(VECTOR, "tenant-a", "dataset-a", 5, path_a, "model-384", 768)


def test_metadata_mismatch_prevents_relationship_search(tmp_path):
    """Metadata mismatch prevents relationship search."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_document("t", "test")], [VECTOR], path_a, "a", "m", 384)

    with pytest.raises(QdrantStorageError, match="model or dimension"):
        store.search_relationship(VECTOR, "tenant-a", "dataset-a", 5, path_a, "different-model", 384)

    with pytest.raises(QdrantStorageError, match="384 dimensions"):
        store.search_relationship(VECTOR, "tenant-a", "dataset-a", 5, path_a, "model-384", 768)


def test_metadata_mismatch_prevents_master_value_search(tmp_path):
    """Metadata mismatch prevents master_value search."""
    store = _make_store(_client())
    path_a = _dataset_metadata(tmp_path, "tenant-a", "dataset-a")
    store.reindex_dataset("tenant-a", "dataset-a", [_value_document("t", "c", "val")], [VECTOR], path_a, "a", "m", 384)

    with pytest.raises(QdrantStorageError, match="model or dimension"):
        store.search_master_value(VECTOR, "tenant-a", "dataset-a", 5, path_a, "different-model", 384)

    with pytest.raises(QdrantStorageError, match="384 dimensions"):
        store.search_master_value(VECTOR, "tenant-a", "dataset-a", 5, path_a, "model-384", 768)