"""Regression coverage for namespace-local FAISS and SQLite persistence."""

from __future__ import annotations

import hashlib
import itertools
import sqlite3

import numpy as np
import pytest
import sqlalchemy as sa

from catalog.introspect import introspect_catalog
from core.startup import _schema_records
from db.adapter import DatabaseAdapter
from llm.prompt_builder import build_prompt
from retrieval.local_store import LocalVectorStore
from retrieval.value_index import ValueIndex
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo


class CountingEmbedder:
    model_name = "synthetic-model"
    dim = 4

    def __init__(self) -> None:
        self.batches: list[int] = []

    def vector(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return np.asarray([digest[index] + 1 for index in range(self.dim)], dtype=np.float32)

    def embed(self, texts: list[str]) -> np.ndarray:
        self.batches.append(len(texts))
        if any(text.endswith("invalid-vector") for text in texts):
            return np.zeros((len(texts), self.dim), dtype=np.float32)
        return np.stack([self.vector(text) for text in texts])


def _records() -> tuple[list[dict], list[dict]]:
    schema = [{
        "table_name": "schema_one.generic_table",
        "column_name": None,
        "metadata_type": "table_ddl",
        "content": "generic table description",
    }]
    values = [{
        "table_name": "schema_one.generic_table",
        "column_name": "generic_field",
        "classification": "VALUE_LOW",
        "value_hash": hashlib.sha256(b"synthetic-low-value").hexdigest(),
        "value": "synthetic-low-value",
    }]
    return schema, values


def _store(path, embedder=None, *, model_name=None, dimension=None, policy_hash="policy"):
    embedder = embedder or CountingEmbedder()
    return LocalVectorStore(
        path,
        "generic-namespace",
        model_name or embedder.model_name,
        dimension or embedder.dim,
        policy_hash,
    )


def test_local_store_round_trip_and_incremental_embed_cache(tmp_path):
    embedder = CountingEmbedder()
    schema, values = _records()
    store = _store(tmp_path, embedder)
    assert store.build_schema(schema, embedder)
    assert store.build_values(values, embedder)
    query = embedder.vector(schema[0]["content"])
    initial = store.search_schema(query, 1, metadata_type="table_ddl")
    initial_values = store.search_values(
        embedder.vector(values[0]["value"]),
        1,
        table="schema_one.generic_table",
        column="generic_field",
    )

    reloaded = _store(tmp_path, embedder)
    assert reloaded.search_schema(query, 1, metadata_type="table_ddl") == initial
    assert reloaded.search_values(
        embedder.vector(values[0]["value"]),
        1,
        table="schema_one.generic_table",
        column="generic_field",
    ) == initial_values

    calls_before = list(embedder.batches)
    assert reloaded.build_schema(schema, embedder)
    assert reloaded.build_values(values, embedder)
    assert embedder.batches == calls_before

    changed = [dict(schema[0], content="changed generic table description")]
    assert reloaded.build_schema(changed, embedder)
    assert embedder.batches[-1] == 1


def test_unchanged_valid_parts_are_not_rewritten(tmp_path):
    embedder = CountingEmbedder()
    schema, values = _records()
    store = _store(tmp_path, embedder)
    assert store.build_schema(schema, embedder)
    assert store.build_values(values, embedder)

    reloaded = _store(tmp_path, embedder)
    original_save_seconds = reloaded.save_seconds
    assert reloaded.build_schema(schema, embedder)
    assert reloaded.build_values(values, embedder)

    assert reloaded.save_seconds == original_save_seconds


@pytest.mark.parametrize(
    "damaged_file,expected_schema,expected_values",
    [
        ("schema.faiss", 0, 1),
        ("schema_meta.json", 0, 1),
        ("values.faiss", 1, 0),
        ("values_meta.json", 1, 0),
        ("manifest.json", 0, 0),
        ("embed_cache.sqlite", 1, 1),
    ],
)
def test_local_store_recovers_missing_or_corrupt_parts(
    tmp_path, damaged_file, expected_schema, expected_values
):
    embedder = CountingEmbedder()
    schema, values = _records()
    store = _store(tmp_path, embedder)
    assert store.build_schema(schema, embedder)
    assert store.build_values(values, embedder)
    path = store.path / damaged_file
    if damaged_file.endswith(".faiss") or damaged_file.endswith(".sqlite") or damaged_file == "manifest.json":
        path.write_bytes(b"")
    else:
        path.unlink()

    recovered = _store(tmp_path, embedder)
    assert recovered.count_schema() == expected_schema
    assert recovered.count_values() == expected_values
    assert recovered.build_schema(schema, embedder)
    assert recovered.build_values(values, embedder)
    assert recovered.count_schema() == 1
    assert recovered.count_values() == 1


@pytest.mark.parametrize(
    "model_name,dimension",
    [("replacement-model", 4), ("synthetic-model", 6)],
)
def test_manifest_model_or_dimension_change_rebuilds_vectors(tmp_path, model_name, dimension):
    original_embedder = CountingEmbedder()
    schema, _ = _records()
    original = _store(tmp_path, original_embedder)
    assert original.build_schema(schema, original_embedder)

    changed_embedder = CountingEmbedder()
    changed_embedder.model_name = model_name
    changed_embedder.dim = dimension
    rebuilt = _store(
        tmp_path,
        changed_embedder,
        model_name=model_name,
        dimension=dimension,
    )
    assert rebuilt.count_schema() == 0
    assert rebuilt.build_schema(schema, changed_embedder)
    assert changed_embedder.batches == [1]


def test_zero_vector_build_does_not_replace_existing_index(tmp_path):
    embedder = CountingEmbedder()
    schema, _ = _records()
    store = _store(tmp_path, embedder)
    assert store.build_schema(schema, embedder)
    original_hash = store.schema_meta[0]["content_hash"]

    assert not store.build_schema(
        [dict(schema[0], content="changed invalid-vector")], embedder
    )
    assert store.count_schema() == 1
    assert store.schema_meta[0]["content_hash"] == original_hash


def test_local_store_persists_phase3_fingerprints_and_classification_counts(tmp_path):
    store = _store(tmp_path)
    classification_cache = {
        "generic_table": {
            "fingerprint": "table-fingerprint",
            "columns": {
                "generic_field": {
                    "class": "VALUE_LOW",
                    "reason": "text column with distinct count 2 <= threshold 10",
                    "distinct_count": 2,
                    "non_null_count": 3,
                    "avg_text_length": 4.0,
                }
            },
        }
    }

    store.save_index_state(
        global_schema_fingerprint="global-fingerprint",
        table_fingerprints={"generic_table": "table-fingerprint"},
        last_value_scan_at={"generic_table": 1234.5},
        classification_cache=classification_cache,
    )

    reloaded = _store(tmp_path)
    assert reloaded.manifest["global_schema_fingerprint"] == "global-fingerprint"
    assert reloaded.manifest["table_fingerprints"] == {
        "generic_table": "table-fingerprint"
    }
    assert reloaded.manifest["last_value_scan_at"] == {"generic_table": 1234.5}
    assert reloaded.load_classification_cache() == classification_cache
    cache_text = reloaded.classification_cache_path.read_text(encoding="utf-8")
    assert '"value"' not in cache_text


def test_embedding_cache_collects_unreferenced_rows_in_batches(tmp_path):
    embedder = CountingEmbedder()
    schema, values = _records()
    store = LocalVectorStore(
        tmp_path,
        "cache-gc-namespace",
        embedder.model_name,
        embedder.dim,
        "policy",
        embed_cache_max_entries=2,
    )
    assert store.build_schema(schema, embedder)
    assert store.build_values(values, embedder)
    old_schema_hash = store.schema_meta[0]["content_hash"]
    assert store.build_schema(
        [dict(schema[0], content="replacement generic table")], embedder
    )
    store.save_index_state(
        global_schema_fingerprint="global",
        table_fingerprints={"generic_table": "table"},
        last_value_scan_at={},
        classification_cache={},
    )

    with sqlite3.connect(store.path / "embed_cache.sqlite") as connection:
        cache_count = connection.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        old_hash_count = connection.execute(
            "SELECT COUNT(*) FROM embeddings WHERE content_hash = ?",
            (old_schema_hash,),
        ).fetchone()[0]

    assert cache_count == 2
    assert old_hash_count == 0


def test_value_embedding_failure_preserves_failed_table_and_updates_others(tmp_path):
    class SelectiveFailEmbedder(CountingEmbedder):
        def embed(self, texts: list[str]) -> np.ndarray:
            if "new-primary" in texts:
                raise RuntimeError("synthetic embedding failure")
            return super().embed(texts)

    embedder = CountingEmbedder()
    store = _store(tmp_path, embedder)
    initial_values = [
        {
            "table_name": "generic_primary",
            "column_name": "generic_label",
            "classification": "VALUE_LOW",
            "value_hash": hashlib.sha256(b"old-primary").hexdigest(),
            "value": "old-primary",
        },
        {
            "table_name": "generic_secondary",
            "column_name": "generic_label",
            "classification": "VALUE_LOW",
            "value_hash": hashlib.sha256(b"old-secondary").hexdigest(),
            "value": "old-secondary",
        },
    ]
    assert store.build_values(initial_values, embedder)

    replacement_values = [
        dict(
            initial_values[0],
            value_hash=hashlib.sha256(b"new-primary").hexdigest(),
            value="new-primary",
        ),
        dict(
            initial_values[1],
            value_hash=hashlib.sha256(b"new-secondary").hexdigest(),
            value="new-secondary",
        ),
    ]
    result = store.build_values(
        replacement_values,
        SelectiveFailEmbedder(),
        current_tables={"generic_primary", "generic_secondary"},
    )

    values_by_table = {
        record["table_name"]: record["value"] for record in store.values_meta
    }
    assert not result
    assert store.failed_value_tables == {"generic_primary"}
    assert values_by_table == {
        "generic_primary": "old-primary",
        "generic_secondary": "new-secondary",
    }


def test_value_search_keeps_schema_qualified_names_and_filters(tmp_path):
    embedder = CountingEmbedder()
    store = _store(tmp_path, embedder)
    records = [
        {
            "table_name": "schema_one.generic_table",
            "column_name": "generic_field",
            "classification": "VALUE_LOW",
            "value_hash": hashlib.sha256(b"value-one").hexdigest(),
            "value": "value-one",
        },
        {
            "table_name": "schema_two.generic_table",
            "column_name": "generic_field",
            "classification": "VALUE_LOW",
            "value_hash": hashlib.sha256(b"value-two").hexdigest(),
            "value": "value-two",
        },
    ]
    assert store.build_values(records, embedder)
    matches = store.search_values(
        embedder.vector("value-one"),
        2,
        table="schema_two.generic_table",
        column="generic_field",
    )
    assert len(matches) == 1
    assert matches[0]["table_name"] == "schema_two.generic_table"


def test_examples_are_bounded_and_save_failure_returns_false(tmp_path, monkeypatch):
    import retrieval.local_store as local_store_module

    store = _store(tmp_path)
    store.example_candidate_limit = 2
    ticks = itertools.count(1)
    monkeypatch.setattr(local_store_module.time, "time", lambda: float(next(ticks)))
    assert store.save_example("synthetic question one", "SELECT 1")
    assert store.save_example("synthetic question two", "SELECT 2")
    assert store.save_example("synthetic question three", "SELECT 3")
    examples = store.get_examples()
    assert len(examples) == 2
    assert examples[0]["question"] == "synthetic question three"

    monkeypatch.setattr(
        local_store_module.sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.DatabaseError()),
    )
    assert not store.save_example("synthetic failure", "SELECT 1")


def test_value_index_persists_only_allowed_low_values(tmp_path, monkeypatch):
    import config.data_policy as data_policy
    import retrieval.value_index as value_index_module
    import schema.documents as documents_module

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table(
        "synthetic_records",
        metadata,
        sa.Column("allowed_field", sa.String),
        sa.Column("blocked_field", sa.String),
        sa.Column("masked_field", sa.String),
        sa.Column("wide_field", sa.String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [
            {
                "allowed_field": "allowed-sentinel-a",
                "blocked_field": "blocked-sentinel-value",
                "masked_field": "masked-sentinel-value",
                "wide_field": "high-sentinel-value-a",
            },
            {
                "allowed_field": "allowed-sentinel-b",
                "blocked_field": "blocked-sentinel-value",
                "masked_field": "masked-sentinel-value",
                "wide_field": "high-sentinel-value-b",
            },
            {
                "allowed_field": "allowed-sentinel-a",
                "blocked_field": "blocked-sentinel-value",
                "masked_field": "masked-sentinel-value",
                "wide_field": "high-sentinel-value-c",
            },
        ])

    policy = {
        "force_block": ["synthetic_records.blocked_field"],
        "force_mask": ["synthetic_records.masked_field"],
    }
    monkeypatch.setattr(value_index_module, "get_policy_overrides", lambda: policy)
    monkeypatch.setattr(data_policy, "is_blocked", lambda key: key.endswith(".blocked_field"))
    monkeypatch.setattr(data_policy, "is_masked", lambda key: key.endswith(".masked_field"))
    monkeypatch.setattr(documents_module, "is_blocked", data_policy.is_blocked)
    monkeypatch.setattr(documents_module, "is_masked", data_policy.is_masked)

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)
    embedder = CountingEmbedder()
    store = _store(tmp_path, embedder)
    index = ValueIndex(adapter, catalog, cardinality_threshold=2, embedder=embedder, local_store=store)
    assert index.build() == {"synthetic_records.allowed_field": ["allowed-sentinel-a", "allowed-sentinel-b"]}
    assert store.count_values() == 2
    assert store.build_schema(_schema_records(catalog), embedder)

    persisted = b"".join(path.read_bytes() for path in store.path.iterdir() if path.is_file())
    for forbidden in (
        b"blocked_field",
        b"masked_field",
        b"blocked-sentinel-value",
        b"masked-sentinel-value",
        b"high-sentinel-value-a",
        b"high-sentinel-value-b",
        b"high-sentinel-value-c",
    ):
        assert forbidden not in persisted


def test_local_hints_override_global_and_fall_back_when_missing(tmp_path):
    local_hints = tmp_path / "namespace" / "hints.md"
    local_hints.parent.mkdir()
    local_hints.write_text("local synthetic guidance", encoding="utf-8")
    global_hints = tmp_path / "hints.md"
    global_hints.write_text("global synthetic guidance", encoding="utf-8")

    local_messages = build_prompt(
        "generic question",
        "sqlite",
        "TABLE generic_table ()",
        hints_path=local_hints,
        fallback_hints_path=global_hints,
    )
    fallback_messages = build_prompt(
        "generic question",
        "sqlite",
        "TABLE generic_table ()",
        hints_path=tmp_path / "missing.md",
        fallback_hints_path=global_hints,
    )

    assert "local synthetic guidance" in local_messages[1]["content"]
    assert "global synthetic guidance" not in local_messages[1]["content"]
    assert "global synthetic guidance" in fallback_messages[1]["content"]


def test_local_store_rejects_non_value_low_value_records(tmp_path):
    embedder = CountingEmbedder()
    store = _store(tmp_path, embedder)
    records = [{
        "table_name": "schema_one.generic_table",
        "column_name": "generic_field",
        "classification": "VALUE_HIGH",
        "value_hash": hashlib.sha256(b"high-value").hexdigest(),
        "value": "synthetic-high-value",
    }]
    assert store.build_values(records, embedder)
    assert store.count_values() == 0
    assert not any(b"synthetic-high-value" in path.read_bytes() for path in store.path.iterdir() if path.is_file())


@pytest.mark.parametrize("sql_type", [sa.Enum("alpha", "beta"), sa.Enum("0", "1")])
def test_enum_options_are_indexed_from_type_metadata_without_target_scan(
    tmp_path, sql_type
):
    adapter = type("Adapter", (), {"engine": object()})()
    metadata = SchemaMetadata({
        "generic_table": TableInfo(
            name="generic_table",
            description="generic table",
            columns=[
                ColumnInfo(
                    "generic_field",
                    str(sql_type),
                    enum_options=list(sql_type.enums),
                )
            ],
            primary_key_names=[],
            foreign_keys=[],
        )
    })
    embedder = CountingEmbedder()
    store = _store(tmp_path, embedder)
    index = ValueIndex(adapter, metadata, cardinality_threshold=5, embedder=embedder, local_store=store)

    indexed = index.build()

    assert indexed["generic_table.generic_field"] == list(sql_type.enums)
    assert store.count_values() == len(sql_type.enums)
