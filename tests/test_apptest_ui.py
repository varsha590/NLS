"""AppTest + unit tests for the validated-query rerun flow."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from ask import AskResult
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
    """Ask -> validated -> sqlite form -> submit -> rows shown -> rerun -> rows still shown; no password in session_state."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, price REAL)")
    conn.execute("INSERT INTO items (name, price) VALUES ('widget', 9.99)")
    conn.execute("INSERT INTO items (name, price) VALUES ('gadget', 19.99)")
    conn.commit()
    conn.close()

    def fake_ask_question(question, metadata, value_documents, embedder, qdrant_store,
                          tenant_id, dataset_id, dataset_metadata_path):
        return AskResult(
            outcome="validated", message="Validated.",
            sql="SELECT id, name, price FROM items", dialect="sqlite",
        )

    import ask
    monkeypatch.setattr(ask, "ask_question", fake_ask_question)

    def fake_execute_validated(sql, credentials, stored_dialect=None):
        c = sqlite3.connect(credentials.database)
        try:
            cur = c.execute(sql)
            columns = [d[0] for d in cur.description]
            rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        finally:
            c.close()
        return {"columns": columns, "rows": rows, "row_count": len(rows), "duration_ms": 5}

    # Patch db.credentials BEFORE importing ui.app so ui/app's module-level
    # `from db.credentials import execute_validated` gets the fake.
    from db import credentials as credsmod
    monkeypatch.setattr(credsmod, "execute_validated", fake_execute_validated)
    monkeypatch.setattr(credsmod, "log_query", lambda *a, **k: None)

    import ui.app as appmod

    class FakeEmbedder:
        model_name = "test"
        dim = 384

    class FakeQdrantStore:
        client = object()

    monkeypatch.setattr(appmod, "get_embedding_model", lambda *a, **k: FakeEmbedder())
    monkeypatch.setattr(appmod, "build_qdrant_store", lambda *a, **k: FakeQdrantStore())

    at = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")).run()

    # Tenant ID
    at.text_input(key="tenant_id").set_value("default").run()

    # Register temp sqlite dataset
    from ingestion.datasets import DatasetRegistry
    reg = DatasetRegistry("datasets")
    with open(db_path, "rb") as f:
        data = f.read()
    try:
        reg.register("temp_test.db", data, tenant_id="default",
                     dialect_override="sqlite", embedding_model_name="test-embedding-model")
    except Exception:
        pass
    at.run()

    # Select a dataset
    try:
        sb = at.selectbox[0]
        sb.set_value(sb.options[0])
    except Exception:
        pass
    at.run()

    # Ask: set question (keyed input), then click Ask (button index 1; [0] is Register dataset)
    at.text_input(key="question_input").set_value("show me items")
    ask_btn = [b for b in at.form_submit_button if b.label == "Ask"][0]
    ask_btn.click().run()

    # Form should appear; fill sqlite file path and submit
    at.text_input(key="db_file_path").set_value(db_path)
    run_btn = [b for b in at.form_submit_button if b.label == "Run query"][0]
    run_btn.click().run()

    # Rows shown after submit
    at.run()
    found = any("widget" in str(d.value) for d in at.dataframe) or \
            any("widget" in str(t.value) for t in at.table)
    assert found, "Expected rows in output after submit"

    # Second rerun: rows still shown
    at.run()
    found2 = any("widget" in str(d.value) for d in at.dataframe) or \
             any("widget" in str(t.value) for t in at.table)
    assert found2, "Expected rows to persist after second rerun"

    # No password/secret anywhere in session_state
    assert not _find_secret(dict(at.session_state)), "Secret found in session_state"
