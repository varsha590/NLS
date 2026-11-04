from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import sqlalchemy as sa
import yaml

from config import data_policy
from core.startup import _namespace_policy_hash
from db.adapter import DatabaseAdapter
from retrieval.local_store import LocalVectorStore
from retrieval.value_index import ValueIndex
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo
from validation.validator import ValidationError, validate_sql


class CountingEmbedder:
    model_name = "phase4-test"
    dim = 4

    def __init__(self):
        self.calls = 0
        self.batch_sizes: list[int] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        self.batch_sizes.append(len(texts))
        return np.asarray(
            [[len(text) + 1, sum(text.encode("utf-8")) + 1, 1, 1] for text in texts],
            dtype=np.float32,
        )


class CountingStore:
    def __init__(self):
        self.searches = 0

    def search_values(self, query, top_k, table=None, column=None):
        self.searches += 1
        return [
            {"table_name": "synthetic_records", "column_name": "generic_state", "value": "North", "similarity": 0.9},
            {"table_name": "synthetic_records", "column_name": "generic_state", "value": "South", "similarity": 0.2},
        ][:top_k]


def _high_fixture(tmp_path: Path, values: list[str], cap: int = 20000):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    records = sa.Table(
        "synthetic_records",
        metadata,
        sa.Column("synthetic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String),
        sa.Column("generic_state", sa.String),
        sa.Column("generic_secret", sa.String),
    )
    sa.Table(
        "synthetic_links",
        metadata,
        sa.Column("link_key", sa.Integer, primary_key=True),
        sa.Column("record_key", sa.Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(records.insert(), [
            {
                "synthetic_key": index + 1,
                "generic_label": value,
                "generic_state": "North" if index % 2 == 0 else "South",
                "generic_secret": "blocked-sentinel-value",
            }
            for index, value in enumerate(values)
        ])
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = __import__("catalog.introspect", fromlist=["introspect_catalog"]).introspect_catalog(engine)
    index = ValueIndex(
        adapter,
        catalog,
        high_cache_max_values=cap,
        high_cache_total_values=max(cap, 100),
        high_db_lookup_limit=20,
        index_refresh_ttl_hours=24,
    )
    index.large_columns.add("synthetic_records.generic_label")
    return engine, adapter, catalog, index


def test_many_phrase_spans_use_one_embedding_batch_and_bounded_faiss_searches():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = SchemaMetadata({
        "synthetic_records": TableInfo(
            "synthetic_records", "", [ColumnInfo("generic_state", "VARCHAR")], [], []
        )
    })
    embedder = CountingEmbedder()
    store = CountingStore()
    index = ValueIndex(
        DatabaseAdapter("sqlite:///:memory:", engine=engine),
        metadata,
        embedder=embedder,
        local_store=store,
        phrase_span_limit=40,
        top_k_per_span=5,
    )
    index.values["synthetic_records.generic_state"] = ["North", "South"]

    index.resolve_question("region " + " ".join(f"phrase{number}" for number in range(50)))

    assert len(index._candidate_spans("region " + " ".join(f"phrase{number}" for number in range(50)))) <= 40
    assert embedder.calls == 1
    assert index.call_counts["embedding_calls"] == 1
    assert store.searches <= 40
    assert index.call_counts["faiss_searches"] <= 40
    assert index.call_counts.get("value_lookup_db_calls", 0) == 0


def test_high_value_exact_casefold_fuzzy_ambiguity_and_no_match():
    engine, adapter, catalog, index = _high_fixture(
        Path("."), ["Acme Limited", "Acme Limit", "Other Group"]
    )
    del engine, adapter, catalog
    column = "synthetic_records.generic_label"

    assert index.resolve_high_value(column, "Acme Limited")["value"] == "Acme Limited"
    assert index.resolve_high_value(column, "acme limited")["value"] == "Acme Limited"
    ambiguous = index.resolve_high_value(column, "Acme Limitd")
    assert ambiguous["status"] == "ambiguous"
    assert index.resolve_high_value(column, "unrelated phrase")["status"] == "not_found"
    assert index.call_counts["value_lookup_db_calls"] == 1
    assert index.high_value_cache_count == 3


def test_fifty_thousand_value_fallback_is_bounded_parameterized_and_escaped(tmp_path):
    sentinel = "record-49%_x"
    values = [f"record-{number:05d}" for number in range(49999)] + [sentinel]
    engine, adapter, catalog, index = _high_fixture(tmp_path, values, cap=100)
    statements: list[tuple[str, object]] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, parameters, context, many: statements.append((statement, parameters)),
    )

    result = index.resolve_high_value("synthetic_records.generic_label", sentinel)

    assert result == {"status": "resolved", "value": sentinel, "candidates": []}
    assert index.high_value_cache_count == 0
    assert adapter.call_counts["value_lookup_db_calls"] == 2
    selects = [statement for statement, _ in statements if statement.lstrip().casefold().startswith("select")]
    assert len(selects) == 2
    assert any("LIMIT" in statement.upper() for statement in selects)
    assert all(sentinel not in statement for statement, _ in statements)
    lookup_parameters = [str(parameters) for statement, parameters in statements if "LIKE" in statement.upper()]
    assert any("record-49" in parameters and "\\\\%" in parameters for parameters in lookup_parameters)
    assert index.resolve_high_value("missing_table.generic_label", "x")["status"] == "not_found"
    assert not list(tmp_path.rglob("*"))
    del catalog


def test_high_value_literal_alias_in_subquery_in_join_and_like_behavior():
    engine, adapter, catalog, index = _high_fixture(
        Path("."), ["Canonical Label", "Other Label"]
    )
    del engine, adapter
    index.high_cache_max_values = 10
    index.high_cache_total_values = 20
    index.values["synthetic_records.generic_state"] = ["North", "South"]

    canonical = validate_sql(
        "SELECT r.synthetic_key FROM synthetic_records AS r "
        "JOIN synthetic_links AS l ON r.synthetic_key = l.record_key "
        "WHERE r.generic_label = 'canonical label'",
        catalog,
        "sqlite",
        {"synthetic_records", "synthetic_links"},
        value_index=index,
    )
    assert "'Canonical Label'" in canonical

    in_sql = validate_sql(
        "SELECT r.synthetic_key FROM synthetic_records r "
        "WHERE r.generic_state IN ('north', 'South')",
        catalog,
        "sqlite",
        {"synthetic_records"},
        value_index=index,
    )
    assert "'North'" in in_sql

    subquery = validate_sql(
        "SELECT q.synthetic_key FROM (SELECT r.synthetic_key, r.generic_label "
        "FROM synthetic_records r) AS q WHERE q.generic_label = 'canonical label'",
        catalog,
        "sqlite",
        {"synthetic_records"},
        value_index=index,
    )
    assert "'Canonical Label'" in subquery

    like_sql = "SELECT r.synthetic_key FROM synthetic_records r WHERE r.generic_label LIKE '%label%'"
    unchanged = validate_sql(
        like_sql, catalog, "sqlite", {"synthetic_records"}, value_index=index
    )
    assert "LIKE '%label%'" in unchanged


def test_blocked_literal_is_rejected_with_namespace_policy():
    engine, adapter, catalog, index = _high_fixture(Path("."), ["row"])
    del engine, adapter
    with pytest.raises(ValidationError, match="information isn't available"):
        validate_sql(
            "SELECT synthetic_key FROM synthetic_records WHERE generic_secret = 'blocked-sentinel-value'",
            catalog,
            "sqlite",
            {"synthetic_records"},
            value_index=index,
            policy_overrides={"force_block": ["synthetic_records.generic_secret"]},
        )


def test_namespace_overrides_are_isolated_stale_checked_and_hashed(tmp_path):
    engine, adapter, catalog, _ = _high_fixture(tmp_path, ["row"])
    first = tmp_path / "namespace-one" / "overrides.yaml"
    second = tmp_path / "namespace-two" / "overrides.yaml"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text(yaml.safe_dump({
        "policy": {"force_value_low": ["synthetic_records.generic_label"]},
        "value_resolution": {"synonyms": {"label": ["first-cue"]}},
    }))
    second.write_text(yaml.safe_dump({
        "policy": {"force_value_high": ["synthetic_records.generic_label"]},
        "value_resolution": {"synonyms": {"label": ["second-cue"]}},
    }))

    one, stale_one, warnings_one = data_policy.load_database_overrides(first, catalog)
    two, stale_two, warnings_two = data_policy.load_database_overrides(second, catalog)
    old_hash = _namespace_policy_hash(10, first)
    first.write_text(first.read_text() + "# changed\n")

    assert one["value_resolution"]["synonyms"]["label"] == ["first-cue"]
    assert two["value_resolution"]["synonyms"]["label"] == ["second-cue"]
    assert not stale_one and not stale_two and not warnings_one and not warnings_two
    assert _namespace_policy_hash(10, first) != old_hash

    first.write_text(yaml.safe_dump({
        "policy": {
            "force_block": ["missing_table.missing_column"],
            "force_allow": ["synthetic_records.generic_secret*"],
        }
    }))
    _, stale, warnings = data_policy.load_database_overrides(first, catalog)
    assert stale == ["missing_table.missing_column"]
    assert warnings == ["Rejected credential-name force_allow: synthetic_records.generic_secret*"]
    assert engine is not None


def test_global_yaml_contains_no_database_specific_override_or_column_names():
    root = Path(__file__).resolve().parents[1]
    policy = yaml.safe_load((root / "config/data_policy.yaml").read_text())
    resolution = yaml.safe_load((root / "config/value_resolution.yaml").read_text())

    assert not any("." in str(value) for values in policy.get("overrides", {}).values() for value in values)
    assert set(resolution) <= {"thresholds", "metric_value_names", "cued_metric_terms", "excluded_terms"}
    assert not {"cue_aliases", "value_column_allowlist", "status_filter_column_names", "activity_query_expansion"} & set(resolution)


def test_overrides_change_only_target_table_policy_fingerprint():
    engine, adapter, catalog, index = _high_fixture(Path("."), ["row"])
    del engine, adapter, catalog
    first = index._table_policy_fingerprint("synthetic_records")
    unrelated = index._table_policy_fingerprint("synthetic_links")
    index.policy_overrides["force_value_high"] = ["synthetic_records.generic_label"]
    assert index._table_policy_fingerprint("synthetic_records") != first
    assert index._table_policy_fingerprint("synthetic_links") == unrelated
