"""AppTest + unit tests for the validated-query rerun flow."""

from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import time

import pytest

from ui.state import (
    ASK_VALIDATED,
    ASK_OTHER,
    DATASET_CHANGED,
    NEW_ASK,
    PAGE_NEXT,
    PAGE_PREV,
    SUBMIT_FAIL,
    SUBMIT_OK,
    next_ui_state,
)


# ============================================================
# Unit tests for next_ui_state (pure function, no Streamlit)
# ============================================================

def _initial() -> dict:
    return {"pending": None, "result": None, "error": None}


def test_ask_validated_sets_pending_clears_result_error():
    state = {"pending": None, "result": {"row_count": 1}, "error": "old"}
    new = next_ui_state(state, ASK_VALIDATED, {
        "tenant_id": "t", "dataset_id": "d", "dialect": "sqlite",
        "sql": "SELECT 1", "question": "q",
    })
    assert new["pending"] == {
        "tenant_id": "t", "dataset_id": "d", "dialect": "sqlite",
        "sql": "SELECT 1", "question": "q",
    }
    assert new["result"] is None
    assert new["error"] is None


def test_ask_other_clears_pending():
    state = {"pending": {"sql": "SELECT 1"}, "result": {"row_count": 1}, "error": "e"}
    new = next_ui_state(state, ASK_OTHER)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_submit_ok_stores_result_no_credentials():
    state = {"pending": {"sql": "SELECT 1"}, "result": None, "error": None}
    new = next_ui_state(state, SUBMIT_OK, {
        "columns": ["a", "b"], "rows": [{"a": 1, "b": 2}],
        "row_count": 1, "duration_ms": 42,
    })
    assert new["pending"] == {"sql": "SELECT 1"}
    assert new["error"] is None
    assert new["result"] == {
        "columns": ["a", "b"], "rows": [{"a": 1, "b": 2}],
        "row_count": 1, "duration_ms": 42, "page": 1,
    }
    flat = str(new)
    assert "credential" not in flat.lower()
    assert "password" not in flat.lower()


def test_submit_fail_keeps_pending():
    state = {"pending": {"sql": "SELECT 1"}, "result": None, "error": None}
    new = next_ui_state(state, SUBMIT_FAIL, {"message": "conn failed"})
    assert new["pending"] == {"sql": "SELECT 1"}
    assert new["result"] is None
    assert new["error"] == "conn failed"


def test_page_next_changes_only_page():
    rows = [{"a": i} for i in range(100)]
    state = {"pending": None, "result": {"columns": ["a"], "rows": rows,
        "row_count": 100, "duration_ms": 5, "page": 1}, "error": None}
    new = next_ui_state(state, PAGE_NEXT, {"page_size": 10})
    assert new["result"]["page"] == 2
    assert new["pending"] is None
    assert new["error"] is None
    assert len(new["result"]["rows"]) == 100  # rows unchanged


def test_page_next_capped_at_max_page():
    rows = [{"a": i} for i in range(25)]
    state = {"pending": None, "result": {"columns": ["a"], "rows": rows,
        "row_count": 25, "duration_ms": 5, "page": 2}, "error": None}
    new = next_ui_state(state, PAGE_NEXT, {"page_size": 10})
    assert new["result"]["page"] == 3


def test_page_prev_changes_only_page():
    rows = [{"a": i} for i in range(10)]
    state = {"pending": None, "result": {"columns": ["a"], "rows": rows,
        "row_count": 10, "duration_ms": 5, "page": 3}, "error": None}
    new = next_ui_state(state, PAGE_PREV)
    assert new["result"]["page"] == 2
    assert new["pending"] is None


def test_page_prev_floors_at_one():
    rows = [{"a": i} for i in range(10)]
    state = {"pending": None, "result": {"columns": ["a"], "rows": rows,
        "row_count": 10, "duration_ms": 5, "page": 1}, "error": None}
    new = next_ui_state(state, PAGE_PREV)
    assert new["result"]["page"] == 1


def test_new_ask_clears_everything():
    state = {"pending": {"sql": "SELECT 1"}, "result": {"row_count": 1}, "error": "e"}
    new = next_ui_state(state, NEW_ASK)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_dataset_changed_clears_everything():
    state = {"pending": {"sql": "SELECT 1"}, "result": {"row_count": 1}, "error": "e"}
    new = next_ui_state(state, DATASET_CHANGED)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_no_credentials_in_state_any_event():
    state = _initial()
    events = [
        (ASK_VALIDATED, {"tenant_id": "t", "dataset_id": "d", "dialect": "sqlite",
         "sql": "SELECT 1", "question": "q"}),
        (ASK_OTHER, None),
        (SUBMIT_OK, {"columns": [], "rows": [], "row_count": 0, "duration_ms": 1}),
        (SUBMIT_FAIL, {"message": "boom"}),
        (PAGE_NEXT, {"page_size": 50}),
        (PAGE_PREV, None),
        (NEW_ASK, None),
        (DATASET_CHANGED, None),
    ]
    for event, payload in events:
        new = next_ui_state(state, event, payload)
        flat = str(new)
        assert "password" not in flat.lower()
        assert "credential" not in flat.lower()


def test_state_not_mutated():
    state = _initial()
    state["pending"] = {"sql": "SELECT 1"}
    before = dict(state)
    new = next_ui_state(state, ASK_OTHER)
    assert new is not state
    assert state == before
    assert new["pending"] is None


# ============================================================
# AppTest for the rerun flow
# ============================================================

try:
    from streamlit.testing.v1 import AppTest
    HAS_APPTEST = True
except Exception:  # pragma: no cover
    HAS_APPTEST = False


def test_qdrant_store_cache_retries_failures_and_ignores_api_key(monkeypatch):
    import ui.app as appmod

    for name, value in {
        "LLM_MODEL": "test-llm",
        "EMBEDDING_MODEL": "test-embedder",
        "VECTOR_STORE_PATH": ".test-vector-store",
        "SCHEMA_TOP_K": "4",
        "VALUE_TOP_K": "3",
        "VALUE_CARDINALITY_THRESHOLD": "12",
        "QUERY_TIMEOUT_SECONDS": "6",
        "MAX_RETRIES": "2",
        "QDRANT_URL": "http://qdrant.test:6333",
        "QDRANT_COLLECTION": "cache-test",
        "QDRANT_API_KEY": "first-key",
    }.items():
        monkeypatch.setenv(name, value)

    builds = []

    def fake_store(*, settings):
        builds.append((settings.qdrant_url, settings.qdrant_collection))
        if len(builds) == 1:
            raise RuntimeError("temporary failure")
        return object()

    qdrant_cache = getattr(appmod, "_cached_qdrant_store")
    qdrant_cache.clear()
    monkeypatch.setattr(appmod, "QdrantVectorStore", fake_store)
    try:
        with pytest.raises(RuntimeError, match="temporary failure"):
            appmod.build_qdrant_store()
        cached_store = appmod.build_qdrant_store()

        monkeypatch.setenv("QDRANT_API_KEY", "second-key")
        assert appmod.build_qdrant_store() is cached_store
        assert len(builds) == 2

        monkeypatch.setenv("QDRANT_COLLECTION", "another-collection")
        appmod.build_qdrant_store()
        assert len(builds) == 3
    finally:
        qdrant_cache.clear()


def _find_secret(obj, needles=("pw", "secret", "password")):
    """Recursively search obj for any needle string."""
    if isinstance(obj, str):
        return obj in needles
    if isinstance(obj, dict):
        return any(_find_secret(v, needles) for v in obj.values())
    if isinstance(obj, (list, tuple, set)):
        return any(_find_secret(v, needles) for v in obj)
    return False


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest not available")
def test_unindexed_dataset_shows_reindex_prompt(tmp_path, monkeypatch):
    from ingestion.datasets import DatasetRegistry
    import ui.app as appmod

    dataset_root = tmp_path / "datasets"
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(dataset_root))
    monkeypatch.setenv("TENANT_ID", "default")
    DatasetRegistry(dataset_root).register(
        "pending.sql",
        b"CREATE TABLE pending (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="default",
        embedding_model_name="test-embedding-model",
    )
    repairs = []

    def fail_repair(registry, tenant_id, dataset):
        del registry
        repairs.append((tenant_id, dataset["dataset_id"]))
        raise RuntimeError("indexing failed")

    monkeypatch.setattr(appmod, "_index_dataset", fail_repair)
    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )

    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="tenant_id").set_value("default").run()

    assert any(
        element.value == "This dataset is still being prepared. Click Re-index."
        for element in at.info
    )
    assert any(button.label == "Re-index dataset" for button in at.button)
    assert not any(button.label == "Search" for button in at.form_submit_button)
    [button for button in at.button if button.label == "Re-index dataset"][0].click().run()
    assert len(repairs) == 1
    assert any(element.value == "Indexing failed, please retry" for element in at.warning)


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest not available")
def test_apptest_validated_rerun_flow(monkeypatch):
    """Connect first; validated SQL executes once and results page without re-execution."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    conn.execute("INSERT INTO items (name, price) VALUES ('widget', 9.99)")
    conn.execute("INSERT INTO items (name, price) VALUES ('gadget', 19.99)")
    conn.commit()
    conn.close()

    dataset_root = os.path.join(os.path.dirname(db_path), "datasets")
    monkeypatch.setenv("DATASET_STORAGE_PATH", dataset_root)
    monkeypatch.setenv("PAGE_SIZE", "1")
    from db.credentials import DbCredentials, DbConnectionError
    from ingestion.datasets import DatasetRegistry
    from pipeline.query_workflow import QueryReady, ValidatedQuery
    from retrieval.qdrant_retriever import RetrievalResult

    registry = DatasetRegistry(dataset_root)
    registered = registry.register(
        "items.sql",
        b"CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL);",
        tenant_id="default",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )
    metadata_path = registry.dataset_directory("default", registered["dataset_id"]) / "dataset.json"
    dataset_metadata = json.loads(metadata_path.read_text())
    dataset_metadata.update({
        "indexed": True,
        "embedding_model_name": "test-embedding-model",
        "vector_dimension": 384,
    })
    metadata_path.write_text(json.dumps(dataset_metadata))

    def fake_prepare_query(**kwargs):
        return QueryReady(
            status="ok",
            context="",
            retrieval=RetrievalResult(tables=["items"], used_qdrant=True),
            value_matches=[],
            question=kwargs["question"],
            metadata=kwargs["metadata"],
        )

    monkeypatch.setattr("ui.app.prepare_query", fake_prepare_query)
    monkeypatch.setattr(
        "ui.app.generate_and_validate_query",
        lambda query: ValidatedQuery(sql="SELECT id, name, price FROM items"),
    )

    calls = []
    logged_sql = []

    def fake_verify(credentials, dataset_dialect=None, timeout_seconds=15):
        calls.append(("verify", credentials.database, dataset_dialect))
        if credentials.database == "bad":
            raise DbConnectionError(
                "The connection could not be verified. Check the connection details."
            )

    def fake_execute_validated(
        sql, credentials, stored_dialect=None, timeout_seconds=15
    ):
        calls.append(("execute", sql))
        assert "test-secret" not in repr(credentials)
        c = sqlite3.connect(credentials.database, uri=True)
        try:
            cur = c.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        finally:
            c.close()
        return {"columns": columns, "rows": rows, "row_count": len(rows), "duration_ms": 5}

    import ui.app as appmod

    class FakeQdrantStore:
        client = object()

        def close(self):
            pass

    monkeypatch.setattr(appmod, "verify_connection", fake_verify)
    monkeypatch.setattr(appmod, "execute_validated", fake_execute_validated)
    monkeypatch.setattr(
        appmod, "log_query", lambda *args, **kwargs: logged_sql.append(kwargs["sql"])
    )
    monkeypatch.setattr(appmod, "get_embedding_model", lambda *a, **k: object())
    monkeypatch.setattr(appmod, "build_qdrant_store", lambda *a, **k: FakeQdrantStore())

    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="tenant_id").set_value("default").run()

    assert {"Host", "Username", "Password", "Database"} <= {
        field.label for field in at.text_input
    }
    assert at.text_input(key="question_input").proto.disabled is True
    assert [button for button in at.form_submit_button if button.label == "Connect"]

    [field for field in at.text_input if field.label == "Password"][0].set_value("test-secret")
    [field for field in at.text_input if field.label == "Database"][0].set_value(db_path)
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()

    assert not at.exception
    assert calls == [("verify", db_path, "sqlite")]
    assert any(element.value == f"Connected to {db_path}" for element in at.success)
    assert [button.label for button in at.button if button.label == "Disconnect"] == ["Disconnect"]
    assert not [button for button in at.form_submit_button if button.label == "Connect"]
    assert at.text_input(key="question_input").proto.disabled is False
    assert isinstance(at.session_state["db_creds"], DbCredentials)
    assert at.session_state["db_creds"].database == db_path
    assert "test-secret" not in repr(at.session_state["db_creds"])
    assert "test-secret" not in str(at.session_state["db_creds"])

    at.text_input(key="question_input").set_value("show me items")
    [button for button in at.form_submit_button if button.label == "Search"][0].click().run()

    query = at.session_state["ui_state"]["pending"]["sql"]
    assert calls == [("verify", db_path, "sqlite"), ("execute", query)]
    assert logged_sql == [query]
    assert [code.value for code in at.code] == [query]
    assert at.expander(key="show-query-expander").proto.expanded is False
    assert "widget" in str(at.dataframe[0].value)
    assert not [button for button in at.form_submit_button if button.label == "Connect"]
    [button for button in at.button if button.label == "Next"][0].click().run()
    assert at.session_state["ui_state"]["pending"]["sql"] == query
    assert [code.value for code in at.code] == [query]
    assert len(calls) == 2

    at.run()
    assert len(calls) == 2
    assert "gadget" in str(at.dataframe[0].value)
    assert at.session_state["ui_state"]["result"]["rows"]

    [button for button in at.button if button.label == "Disconnect"][0].click().run()
    assert "db_creds" not in at.session_state
    assert "db_connected_at" not in at.session_state
    assert any(
        info.value == "Disconnected. Connect again to run a query." for info in at.info
    )
    assert [button for button in at.form_submit_button if button.label == "Connect"]
    assert at.text_input(key="question_input").proto.disabled is True
    assert not at.code
    assert not at.dataframe

    [field for field in at.text_input if field.label == "Database"][0].set_value("bad")
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()
    assert "db_creds" not in at.session_state
    assert any("could not be verified" in warning.value for warning in at.warning)
    assert [button for button in at.form_submit_button if button.label == "Connect"]

    [field for field in at.text_input if field.label == "Database"][0].set_value(db_path)
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()
    monkeypatch.setenv("DB_IDLE_TIMEOUT_SECONDS", "60")
    at.session_state["db_connected_at"] = time.time() - 61
    at.run()
    assert "db_creds" not in at.session_state
    assert any("connection expired" in info.value for info in at.info)
    assert [button for button in at.form_submit_button if button.label == "Connect"]


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest not available")
def test_apptest_credentials_cleared_on_tenant_and_dataset_change(monkeypatch, tmp_path):
    """A connected session forgets credentials when tenant or dataset changes."""
    from db.credentials import DbCredentials
    from ingestion.datasets import DatasetRegistry

    dataset_root = tmp_path / "datasets"
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(dataset_root))
    registry = DatasetRegistry(dataset_root)
    dataset_ids: dict[str, list[str]] = {}
    for tenant, filenames in (
        ("tenant-a", ["a.sql"]),
        ("tenant-b", ["b-one.sql", "b-two.sql"]),
    ):
        dataset_ids[tenant] = []
        for name in filenames:
            registered = registry.register(
                name,
                b"CREATE TABLE items (id INTEGER PRIMARY KEY);",
                tenant_id=tenant,
                dialect_override="sqlite",
                embedding_model_name="test-embedding-model",
            )
            dataset_ids[tenant].append(registered["dataset_id"])
            metadata_path = (
                registry.dataset_directory(tenant, registered["dataset_id"]) / "dataset.json"
            )
            metadata = json.loads(metadata_path.read_text())
            metadata["indexed"] = True
            metadata_path.write_text(json.dumps(metadata))

    import ui.app as appmod

    monkeypatch.setattr(appmod, "verify_connection", lambda *args, **kwargs: None)

    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="tenant_id").set_value("tenant-a").run()
    [field for field in at.text_input if field.label == "Database"][0].set_value(":memory:")
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()

    assert isinstance(at.session_state.get("db_creds"), DbCredentials)

    at.text_input(key="tenant_id").set_value("tenant-b").run()
    assert "db_creds" not in at.session_state
    assert "db_connected_at" not in at.session_state
    assert [button for button in at.form_submit_button if button.label == "Connect"]

    [field for field in at.text_input if field.label == "Database"][0].set_value(":memory:")
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()
    assert isinstance(at.session_state.get("db_creds"), DbCredentials)

    active_dataset_id = at.session_state["active_dataset_id"]
    other_dataset_id = next(
        value
        for value in dataset_ids["tenant-b"]
        if value != active_dataset_id
    )
    at.selectbox(key="dataset-select").select(other_dataset_id).run()
    assert "db_creds" not in at.session_state
    assert "db_connected_at" not in at.session_state
    assert [button for button in at.form_submit_button if button.label == "Connect"]


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest not available")
def test_apptest_clarification_buttons_regenerate_sql(monkeypatch, tmp_path):
    """Ambiguity shows table buttons; clicking one reruns the question with that table."""
    from ingestion.datasets import DatasetRegistry
    from pipeline.query_workflow import (
        QueryNeedsTableClarification,
        QueryReady,
        ValidatedQuery,
    )
    from retrieval.qdrant_retriever import RetrievalResult

    dataset_root = tmp_path / "datasets"
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(dataset_root))
    registry = DatasetRegistry(dataset_root)
    registered = registry.register(
        "items.sql",
        b"CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="acme",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )
    metadata_path = registry.dataset_directory("acme", registered["dataset_id"]) / "dataset.json"
    dataset_metadata = json.loads(metadata_path.read_text())
    dataset_metadata["indexed"] = True
    metadata_path.write_text(json.dumps(dataset_metadata))

    candidates = ["alpha", "beta", "gamma", "delta"]
    forced_seen = []
    generation_calls = []

    def fake_prepare_query(**kwargs):
        forced = kwargs.get("forced_table")
        forced_seen.append(forced)
        if forced is None:
            return QueryNeedsTableClarification(options=candidates)
        return QueryReady(
            status="ok",
            context="=== SCHEMA ===",
            retrieval=RetrievalResult(tables=[forced], used_qdrant=True),
            value_matches=[],
            question=kwargs["question"],
            metadata=kwargs["metadata"],
        )

    monkeypatch.setattr("ui.app.prepare_query", fake_prepare_query)
    monkeypatch.setattr(
        "ui.app.generate_and_validate_query",
        lambda query: (
            generation_calls.append(query)
            or ValidatedQuery(sql="SELECT id, name FROM items")
        ),
    )
    import ui.app as appmod

    monkeypatch.setattr(appmod, "verify_connection", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        appmod,
        "execute_validated",
        lambda *args, **kwargs: {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr("ui.app.get_embedding_model", lambda *a, **k: object())
    monkeypatch.setattr("ui.app.build_qdrant_store", lambda *a, **k: object())

    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="tenant_id").set_value("acme").run()
    [field for field in at.text_input if field.label == "Database"][0].set_value(":memory:")
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()
    at.text_input(key="question_input").set_value("show records")
    [button for button in at.form_submit_button if button.label == "Search"][0].click().run()

    assert not at.exception
    assert any(info.value == "Please clarify which table you mean." for info in at.info)
    assert [button.label for button in at.button if button.label in candidates] == candidates
    assert generation_calls == []
    assert at.session_state["pending_question"] == "show records"
    assert at.session_state["forced_table"] is None

    [button for button in at.button if button.label == candidates[1]][0].click().run()

    assert not at.exception
    assert forced_seen == [None, "beta"]
    assert len(generation_calls) == 1
    assert generation_calls[0].question == "show records"
    assert at.session_state["forced_table"] == "beta"
    assert [code.value for code in at.code] == ["SELECT id, name FROM items"]
    assert at.expander(key="show-query-expander").proto.expanded is False


def test_allow_all_policy_includes_sensitive_columns_in_context_and_documents(tmp_path):
    from config.data_policy import allow_all_columns_policy
    from ingestion.datasets import DatasetRegistry
    from retrieval.dataset_indexer import build_embedding_documents
    from schema.context import build_query_context

    registry = DatasetRegistry(tmp_path / "datasets")
    registered = registry.register(
        "customers.sql",
        b"CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT);",
        tenant_id="default",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )
    metadata = registry.load_schema("default", registered["dataset_id"])
    policy = allow_all_columns_policy()

    context = build_query_context(metadata, ["customers"], [], policy_overrides=policy)
    assert "email" in context

    documents = build_embedding_documents(metadata, [], policy)
    assert any(
        item["table_name"] == "customers" and item["column_name"] == "email"
        for item in documents
    )


def test_allow_all_policy_still_rejects_non_select(tmp_path):
    from config.data_policy import allow_all_columns_policy
    from ingestion.datasets import DatasetRegistry
    from validation.validator import ValidationError, validate_sql

    registry = DatasetRegistry(tmp_path / "datasets")
    registered = registry.register(
        "customers.sql",
        b"CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="default",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )
    metadata = registry.load_schema("default", registered["dataset_id"])

    with pytest.raises(ValidationError):
        validate_sql(
            "DELETE FROM customers",
            metadata,
            dialect="sqlite",
            policy_overrides=allow_all_columns_policy(),
        )


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest not available")
def test_apptest_sensitive_column_query_returns_rows(monkeypatch, tmp_path):
    """A connected user can query and see a sensitive-looking column."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"
    )
    conn.execute(
        "INSERT INTO customers (name, email) VALUES ('Ada', 'ada@example.com')"
    )
    conn.commit()
    conn.close()

    dataset_root = tmp_path / "datasets"
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(dataset_root))
    from ingestion.datasets import DatasetRegistry
    from retrieval.qdrant_retriever import VECTOR_SIZE
    import pipeline.query_workflow as query_workflow

    registry = DatasetRegistry(dataset_root)
    registered = registry.register(
        "customers.sql",
        b"CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT);",
        tenant_id="default",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )
    metadata_path = registry.dataset_directory("default", registered["dataset_id"]) / "dataset.json"
    dataset_metadata = json.loads(metadata_path.read_text())
    dataset_metadata.update({
        "indexed": True,
        "embedding_model_name": "test-embedding-model",
        "vector_dimension": VECTOR_SIZE,
    })
    metadata_path.write_text(json.dumps(dataset_metadata))

    generated_sql = iter([
        "SELECT email FROM customers",
        "SELECT name FROM customers",
    ])
    monkeypatch.setattr(
        query_workflow,
        "generate_sql_from_messages",
        lambda messages, validation_error=None: next(generated_sql),
    )

    import ui.app as appmod

    class FakeEmbedder:
        model_name = "test-embedding-model"
        dim = VECTOR_SIZE

        def embed_single(self, text: str):
            return [0.0] * VECTOR_SIZE

    class FakeQdrantStore:
        client = object()

        def search_table(self, *args, **kwargs):
            return []

        def search_column(self, *args, **kwargs):
            return []

        def search_relationship(self, *args, **kwargs):
            return []

        def search_master_value(self, *args, **kwargs):
            return []

        def close(self):
            pass

    monkeypatch.setattr(appmod, "get_embedding_model", lambda *a, **k: FakeEmbedder())
    monkeypatch.setattr(appmod, "build_qdrant_store", lambda *a, **k: FakeQdrantStore())

    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="tenant_id").set_value("default").run()
    [field for field in at.text_input if field.label == "Database"][0].set_value(db_path)
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()

    assert not at.exception
    assert any(element.value == f"Connected to {db_path}" for element in at.success)

    at.text_input(key="question_input").set_value("show email addresses of customers")
    [button for button in at.form_submit_button if button.label == "Search"][0].click().run()

    assert not at.exception
    sensitive_sql = at.session_state["ui_state"]["pending"]["sql"]
    assert "email" in sensitive_sql.casefold()
    assert "from customers" in sensitive_sql.casefold()
    assert "ada@example.com" in str(at.dataframe[0].value)

    at.text_input(key="question_input").set_value("show customer names")
    [button for button in at.form_submit_button if button.label == "Search"][0].click().run()

    assert not at.exception
    ordinary_sql = at.session_state["ui_state"]["pending"]["sql"]
    assert "name" in ordinary_sql.casefold()
    assert "from customers" in ordinary_sql.casefold()
    assert "Ada" in str(at.dataframe[0].value)
