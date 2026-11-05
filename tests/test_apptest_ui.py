"""AppTest + unit tests for the validated-query rerun flow."""

from __future__ import annotations

import os
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
    assert new["pending"] is None
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
def test_apptest_validated_rerun_flow(monkeypatch):
    """Validated SQL precedes connection; rows persist and page without re-execution."""
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
    from ingestion.datasets import DatasetRegistry
    from pipeline.query_workflow import QueryReady, ValidatedQuery
    from retrieval.qdrant_retriever import RetrievalResult

    registry = DatasetRegistry(dataset_root)
    registry.register(
        "items.sql",
        b"CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL);",
        tenant_id="default",
        dialect_override="sqlite",
        embedding_model_name="test-embedding-model",
    )

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

    def fake_test_connection(credentials, timeout_seconds):
        calls.append(("connect", credentials.database))
        if credentials.database == "bad":
            from db.credentials import DbConnectionError

            raise DbConnectionError("connection rejected")

    def fake_execute_validated(
        sql, credentials, stored_dialect=None, timeout_seconds=15
    ):
        calls.append(("execute", sql))
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

    monkeypatch.setattr(appmod, "test_connection", fake_test_connection)
    monkeypatch.setattr(appmod, "execute_validated", fake_execute_validated)
    monkeypatch.setattr(appmod, "log_query", lambda *a, **k: None)
    monkeypatch.setattr(appmod, "get_embedding_model", lambda *a, **k: object())
    monkeypatch.setattr(appmod, "build_qdrant_store", lambda *a, **k: FakeQdrantStore())

    entrypoint = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
    )
    at = AppTest.from_file(entrypoint).run()
    at.text_input(key="question_input").set_value("show me items")
    [button for button in at.form_submit_button if button.label == "Search"][0].click().run()

    assert any("SELECT id, name, price FROM items" in str(code.value) for code in at.code)
    assert any(button.label == "Connect" for button in at.form_submit_button)
    assert not any(element.value == "Connected" for element in at.success)

    [field for field in at.text_input if field.label == "Database"][0].set_value(db_path)
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()

    assert calls == [("connect", db_path), ("execute", "SELECT id, name, price FROM items")]
    assert any(element.value == "Connected" for element in at.success)
    assert "widget" in str(at.dataframe[0].value)

    at.run()
    assert len(calls) == 2
    assert "widget" in str(at.dataframe[0].value)
    assert at.session_state["db_creds"]["credentials"].database == db_path
    assert at.session_state["ui_state"]["result"]["rows"]

    monkeypatch.setenv("DB_IDLE_TIMEOUT_SECONDS", "60")
    at.session_state["db_creds"]["last_used"] = time.time() - 61
    at.run()
    assert "db_creds" not in at.session_state
    assert any(button.label == "Connect" for button in at.form_submit_button)

    [field for field in at.text_input if field.label == "Database"][0].set_value("bad")
    [button for button in at.form_submit_button if button.label == "Connect"][0].click().run()
    assert "db_creds" not in at.session_state
    assert "could not be verified" in at.warning[0].value
    assert any(button.label == "Connect" for button in at.form_submit_button)
