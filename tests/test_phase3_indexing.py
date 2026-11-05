"""Phase 3 startup reuse and scale regressions using synthetic catalogs."""

from __future__ import annotations

import time

import numpy as np
import pytest
import sqlalchemy as sa

from config.settings import Settings
from core import startup
from db.adapter import DatabaseAdapter
from retrieval.local_store import LocalVectorStore
from retrieval.value_index import ValueIndex


class CountingEmbeddingModel:
    model_name = "phase3-synthetic-model"
    dim = 4
    batches: list[int] = []

    def __init__(self, model_name: str):
        del model_name
        self.model_name = type(self).model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        type(self).batches.append(len(texts))
        return np.ones((len(texts), self.dim), dtype=np.float32)


def _settings(vector_path, refresh_ttl_hours: float = 24) -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        groq_api_key="",
        llm_model="phase3-test-model",
        embedding_model=CountingEmbeddingModel.model_name,
        vector_store_path=str(vector_path),
        schema_top_k=4,
        value_top_k=3,
        query_timeout_seconds=5,
        max_retries=0,
        allowed_schemas=(),
        excluded_tables=(),
        value_cardinality_threshold=10,
        index_refresh_ttl_hours=refresh_ttl_hours,
    )


def _configure_startup(tmp_path, monkeypatch, engine, refresh_ttl_hours: float = 24):
    monkeypatch.setattr(
        startup.Settings,
        "from_env",
        lambda: _settings(tmp_path, refresh_ttl_hours),
    )
    monkeypatch.setattr(
        startup,
        "DatabaseAdapter",
        lambda database_url, timeout: DatabaseAdapter(database_url, timeout, engine=engine),
    )
    monkeypatch.setattr(startup, "EmbeddingModel", CountingEmbeddingModel)
    CountingEmbeddingModel.batches.clear()


def _data_query_count(statements: list[str], table_names: list[str]) -> int:
    markers = tuple(
        marker
        for name in table_names
        for marker in (f'from "{name.casefold()}"', f"from {name.casefold()}")
    )
    return sum(
        statement.lstrip().casefold().startswith("select")
        and any(marker in statement.casefold() for marker in markers)
        for statement in statements
    )


def _create_catalog(table_count: int) -> tuple[sa.Engine, list[str]]:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table_names = []
    for table_index in range(table_count):
        table_name = f"generic_records_{table_index:03d}"
        table_names.append(table_name)
        sa.Table(
            table_name,
            metadata,
            sa.Column("generic_key", sa.Integer, primary_key=True),
            sa.Column("generic_label", sa.String(32)),
        )
    metadata.create_all(engine)
    return engine, table_names


def _create_value_catalog() -> tuple[sa.Engine, sa.Table]:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table(
        "generic_records",
        metadata,
        sa.Column("generic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String(32)),
        sa.Column("generic_group", sa.String(32)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{
            "generic_key": 1,
            "generic_label": "alpha",
            "generic_group": "stable",
        }])
    return engine, table


def _data_query_counts(statements: list[str], table_names: list[str]) -> dict[str, int]:
    return {
        table_name: _data_query_count(statements, [table_name])
        for table_name in table_names
    }


def test_second_startup_skips_data_scans_and_embedding_calls(tmp_path, monkeypatch):
    engine, table_names = _create_catalog(2)
    _configure_startup(tmp_path, monkeypatch, engine)
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )

    startup.init_app()
    statements.clear()
    CountingEmbeddingModel.batches.clear()

    runtime = startup.init_app()

    assert runtime["catalog_status"] == "cached"
    assert _data_query_count(statements, table_names) == 0
    assert CountingEmbeddingModel.batches == []


def test_stale_value_scan_reembeds_only_new_values_in_changed_column(tmp_path, monkeypatch):
    engine, table = _create_value_catalog()
    _configure_startup(tmp_path, monkeypatch, engine)
    clock = {"now": 1000.0}

    startup.init_app(clock=lambda: clock["now"])
    CountingEmbeddingModel.batches.clear()
    with engine.begin() as connection:
        connection.execute(table.update().values(generic_label="beta"))
    clock["now"] += 25 * 3600

    runtime = startup.init_app(clock=lambda: clock["now"])

    assert runtime["catalog_status"] == "indexed"
    assert CountingEmbeddingModel.batches == [1]


def test_value_refresh_ttl_rescans_only_tables_past_the_window(tmp_path, monkeypatch):
    engine, table_names = _create_catalog(1)
    _configure_startup(tmp_path, monkeypatch, engine)
    clock = {"now": 1000.0}
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )
    startup.init_app(clock=lambda: clock["now"])

    metadata = sa.MetaData()
    sa.Table(
        "generic_records_001",
        metadata,
        sa.Column("generic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String(32)),
    )
    metadata.create_all(engine)
    table_names.append("generic_records_001")
    statements.clear()
    clock["now"] += 23 * 3600
    startup.init_app(clock=lambda: clock["now"])
    assert _data_query_counts(statements, table_names) == {
        "generic_records_000": 0,
        "generic_records_001": 1,
    }

    statements.clear()
    clock["now"] += 2 * 3600
    startup.init_app(clock=lambda: clock["now"])
    assert _data_query_counts(statements, table_names) == {
        "generic_records_000": 1,
        "generic_records_001": 0,
    }


def test_model_change_reembeds_cached_values_without_scanning_tables(tmp_path, monkeypatch):
    engine, table = _create_value_catalog()
    _configure_startup(tmp_path, monkeypatch, engine)
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )
    startup.init_app(clock=lambda: 1000.0)
    statements.clear()
    CountingEmbeddingModel.batches.clear()

    class ReplacementEmbeddingModel(CountingEmbeddingModel):
        model_name = "phase3-replacement-model"

    monkeypatch.setattr(startup, "EmbeddingModel", ReplacementEmbeddingModel)
    runtime = startup.init_app(clock=lambda: 1001.0)

    assert _data_query_count(statements, [table.name]) == 0
    assert CountingEmbeddingModel.batches
    assert runtime["local_store"].manifest["embedding_model_name"] == (
        "phase3-replacement-model"
    )


def test_policy_hash_change_reclassifies_without_reembedding_unchanged_content(
    tmp_path, monkeypatch
):
    engine, _ = _create_value_catalog()
    _configure_startup(tmp_path, monkeypatch, engine)
    policy_hash = {"value": "phase3-policy-a"}
    monkeypatch.setattr(
        startup, "_config_policy_hash", lambda threshold: policy_hash["value"]
    )
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )
    startup.init_app(clock=lambda: 1000.0)
    statements.clear()
    CountingEmbeddingModel.batches.clear()
    policy_hash["value"] = "phase3-policy-b"

    runtime = startup.init_app(clock=lambda: 1001.0)

    assert runtime["index_metrics"]["stages"]["scan"]["queries"] == 2
    assert CountingEmbeddingModel.batches == []


def test_enum_option_changes_prune_removed_values_without_row_scans(tmp_path):
    from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo

    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "generic_table",
        metadata,
        sa.Column("generic_field", sa.String(16)),
    )
    metadata.create_all(engine)
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    embedder = CountingEmbeddingModel("phase3-synthetic-model")
    store = LocalVectorStore(
        tmp_path,
        "enum-namespace",
        embedder.model_name,
        embedder.dim,
        "policy",
    )
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )

    def enum_metadata(options):
        return SchemaMetadata({
            "generic_table": TableInfo(
                name="generic_table",
                description="",
                columns=[ColumnInfo("generic_field", "VARCHAR(16)", enum_options=options)],
                primary_key_names=[],
                foreign_keys=[],
            )
        })

    first = ValueIndex(adapter, enum_metadata(["alpha", "beta"]), embedder=embedder, local_store=store)
    first.build_incremental(
        classification_cache=None,
        table_fingerprints={"generic_table": "enum-a"},
        changed_tables={"generic_table"},
        stale_tables=set(),
        value_part_valid=False,
    )
    assert store.build_values(first.value_records, embedder)

    second = ValueIndex(adapter, enum_metadata(["beta", "gamma"]), embedder=embedder, local_store=store)
    second.build_incremental(
        classification_cache=first.classification_cache,
        table_fingerprints={"generic_table": "enum-b"},
        changed_tables={"generic_table"},
        stale_tables=set(),
        value_part_valid=True,
        reuse_value_metadata=True,
    )
    assert store.build_values(second.value_records, embedder)

    indexed_values = {record["value"] for record in store.values_meta}
    assert indexed_values == {"beta", "gamma"}
    assert not any(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def test_zero_refresh_ttl_rescans_on_every_startup(tmp_path, monkeypatch):
    engine, table_names = _create_catalog(1)
    _configure_startup(tmp_path, monkeypatch, engine, refresh_ttl_hours=0)
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )

    startup.init_app(clock=lambda: 1000.0)
    statements.clear()
    startup.init_app(clock=lambda: 1001.0)

    assert _data_query_count(statements, table_names) == 1


def test_schema_add_rename_drop_prunes_local_index_metadata(tmp_path, monkeypatch):
    engine, _ = _create_value_catalog()
    metadata = sa.MetaData()
    auxiliary = sa.Table(
        "generic_auxiliary",
        metadata,
        sa.Column("generic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String(32)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(auxiliary.insert(), [{"generic_key": 1, "generic_label": "auxiliary"}])
    _configure_startup(tmp_path, monkeypatch, engine)
    startup.init_app()

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE generic_records ADD COLUMN generic_extra VARCHAR(32)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE generic_records RENAME COLUMN generic_group TO generic_segment"
        )
        connection.exec_driver_sql("DROP TABLE generic_auxiliary")
        connection.exec_driver_sql(
            "CREATE TABLE generic_added (generic_key INTEGER PRIMARY KEY, generic_label VARCHAR(32))"
        )
        connection.exec_driver_sql(
            "INSERT INTO generic_added (generic_key, generic_label) VALUES (1, 'added')"
        )

    runtime = startup.init_app()

    schema_pairs = {
        (record.get("table_name"), record.get("column_name"))
        for record in runtime["local_store"].schema_meta
    }
    value_pairs = {
        (record.get("table_name"), record.get("column_name"))
        for record in runtime["local_store"].values_meta
    }
    assert ("generic_records", "generic_extra") in schema_pairs
    assert ("generic_records", "generic_segment") in schema_pairs
    assert ("generic_records", "generic_group") not in schema_pairs
    assert not any(table_name == "generic_auxiliary" for table_name, _ in schema_pairs)
    assert not any(table_name == "generic_auxiliary" for table_name, _ in value_pairs)
    assert any(table_name == "generic_added" for table_name, _ in schema_pairs)
    assert ("generic_records", "generic_segment") in value_pairs


def test_failed_table_scan_keeps_prior_index_and_updates_other_tables(
    tmp_path, monkeypatch
):
    engine, first_table = _create_value_catalog()
    metadata = sa.MetaData()
    second_table = sa.Table(
        "generic_secondary",
        metadata,
        sa.Column("generic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String(32)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            second_table.insert(),
            [{"generic_key": 1, "generic_label": "secondary-old"}],
        )
    _configure_startup(tmp_path, monkeypatch, engine, refresh_ttl_hours=0)
    first_runtime = startup.init_app(clock=lambda: 1000.0)
    old_first_hashes = {
        record["value_hash"]
        for record in first_runtime["local_store"].values_meta
        if record["table_name"] == first_table.name
    }

    with engine.begin() as connection:
        connection.execute(first_table.update().values(generic_label="primary-new"))
        connection.execute(second_table.update().values(generic_label="secondary-new"))
    original_scan = getattr(ValueIndex, "_scan_column")

    def fail_first_table(self, connection, table, column_name):
        if table.name == first_table.name:
            raise RuntimeError("synthetic scan failure")
        return original_scan(self, connection, table, column_name)

    monkeypatch.setattr(ValueIndex, "_scan_column", fail_first_table)
    runtime = startup.init_app(clock=lambda: 2000.0)

    first_table_hashes = {
        record["value_hash"]
        for record in runtime["local_store"].values_meta
        if record["table_name"] == first_table.name
    }
    second_table_hashes = {
        record["value_hash"]
        for record in runtime["local_store"].values_meta
        if record["table_name"] == second_table.name
    }
    assert runtime["catalog_status"] == "incomplete"
    assert runtime["incomplete_tables"] == {
        first_table.name: "unexpected_error"
    }
    assert old_first_hashes.issubset(first_table_hashes)
    assert second_table_hashes != {
        record["value_hash"]
        for record in first_runtime["local_store"].values_meta
        if record["table_name"] == second_table.name
    }


def test_failed_value_embedding_surfaces_incomplete_and_preserves_resolver_values(
    tmp_path, monkeypatch
):
    engine, first_table = _create_value_catalog()
    metadata = sa.MetaData()
    second_table = sa.Table(
        "generic_secondary",
        metadata,
        sa.Column("generic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String(32)),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            second_table.insert(),
            [{"generic_key": 1, "generic_label": "secondary-old"}],
        )
    _configure_startup(tmp_path, monkeypatch, engine, refresh_ttl_hours=0)
    startup.init_app(clock=lambda: 1000.0)

    with engine.begin() as connection:
        connection.execute(first_table.update().values(generic_label="primary-new"))
        connection.execute(second_table.update().values(generic_label="secondary-new"))

    class SelectiveFailModel(CountingEmbeddingModel):
        def embed(self, texts: list[str]) -> np.ndarray:
            if "primary-new" in texts:
                raise RuntimeError("synthetic embedding failure")
            return super().embed(texts)

    monkeypatch.setattr(startup, "EmbeddingModel", SelectiveFailModel)
    runtime = startup.init_app(clock=lambda: 2000.0)

    values_by_table = {
        record["table_name"]: record["value"]
        for record in runtime["local_store"].values_meta
    }
    assert runtime["catalog_status"] == "incomplete"
    assert runtime["incomplete_tables"] == {
        first_table.name: "embedding_error"
    }
    assert runtime["local_store"].manifest["index_incomplete"]
    assert runtime["value_index"].values[f"{first_table.name}.generic_label"] == [
        "alpha"
    ]
    assert values_by_table[first_table.name] == "alpha"
    assert values_by_table[second_table.name] == "secondary-new"


def test_store_report_shows_counts_without_value_text(tmp_path):
    store = LocalVectorStore(
        tmp_path,
        "generic-namespace",
        CountingEmbeddingModel.model_name,
        CountingEmbeddingModel.dim,
        "policy",
    )
    value_text = "report-private-sentinel"
    value_record = {
        "table_name": "generic_table",
        "column_name": "generic_field",
        "classification": "VALUE_LOW",
        "value_hash": "safe-hash",
        "value": value_text,
    }
    assert store.build_values([value_record], CountingEmbeddingModel("test"))
    store.save_index_state(
        global_schema_fingerprint="global",
        table_fingerprints={"generic_table": "table"},
        last_value_scan_at={"generic_table": 1000.0},
        classification_cache={
            "generic_table": {
                "fingerprint": "table",
                "columns": {
                    "generic_field": {
                        "class": "VALUE_LOW",
                        "reason": "text column with distinct count 1 <= threshold 10",
                        "distinct_count": 1,
                        "non_null_count": 1,
                        "avg_text_length": 1.0,
                    }
                },
            }
        },
    )

    from scripts.store_report import format_store_report

    report = format_store_report(tmp_path, "generic-namespace")

    assert "generic_table.generic_field" in report
    assert "VALUE_LOW" in report
    assert "stored values: 1" in report
    assert "vectors: 1" in report
    assert value_text not in report


def test_reindex_dry_run_prints_counts_and_no_fixture_values(
    tmp_path, monkeypatch, capsys
):
    engine, _ = _create_value_catalog()
    settings = _settings(tmp_path)
    adapter = DatabaseAdapter(settings.database_url, settings.query_timeout_seconds, engine=engine)

    import reindex

    monkeypatch.setattr(reindex.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(
        reindex,
        "DatabaseAdapter",
        lambda database_url, timeout: adapter,
    )

    assert reindex.main(["--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "Tables: 1" in output
    assert "Tables changed: 1" in output
    assert "Columns changed: 3" in output
    assert "Columns to scan: 2" in output
    assert "Estimated values to embed:" in output
    assert "Estimated seconds:" in output
    assert "alpha" not in output
    assert "stable" not in output


@pytest.mark.parametrize("table_count", [120, 300])
def test_large_catalog_second_startup_has_zero_data_table_statements(
    tmp_path, monkeypatch, table_count, capsys
):
    engine, table_names = _create_catalog(table_count)
    _configure_startup(tmp_path, monkeypatch, engine)
    statements: list[str] = []
    sa.event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: statements.append(statement),
    )

    first_started = time.perf_counter()
    first = startup.init_app()
    assert first["catalog_status"] == "indexed"
    first_seconds = time.perf_counter() - first_started
    first_data_queries = _data_query_count(statements, table_names)

    statements.clear()
    CountingEmbeddingModel.batches.clear()
    second_started = time.perf_counter()
    second = startup.init_app()
    second_seconds = time.perf_counter() - second_started
    second_data_queries = _data_query_count(statements, table_names)

    with capsys.disabled():
        print(
            "phase3-scale",
            {
                "tables": table_count,
                "first_seconds": round(first_seconds, 3),
                "first_data_queries": first_data_queries,
                "first_stages": first.get("index_metrics", {}).get("stages", {}),
                "second_seconds": round(second_seconds, 3),
                "second_data_queries": second_data_queries,
                "second_stages": second.get("index_metrics", {}).get("stages", {}),
            },
        )
    assert first_data_queries == table_count
    assert second_data_queries == 0
    assert CountingEmbeddingModel.batches == []