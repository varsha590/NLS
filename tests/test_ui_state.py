"""Unit tests for ui.state.next_ui_state - pure function, no Streamlit."""

from __future__ import annotations

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


def _initial() -> dict:
    return {"pending": None, "result": None, "error": None}


def test_ask_validated_sets_pending_and_clears_result():
    state = _initial()
    state["result"] = {"columns": ["a"], "rows": [{"a": 1}], "row_count": 1, "duration_ms": 5, "page": 1}
    state["error"] = "old error"
    new = next_ui_state(state, ASK_VALIDATED, {
        "tenant_id": "t",
        "dataset_id": "d",
        "dialect": "sqlite",
        "sql": "SELECT 1",
        "question": "q",
    })
    assert new["pending"] == {
        "tenant_id": "t",
        "dataset_id": "d",
        "dialect": "sqlite",
        "sql": "SELECT 1",
        "question": "q",
    }
    assert new["result"] is None
    assert new["error"] is None


def test_ask_other_clears_pending():
    state = {"pending": {"sql": "SELECT 1"}, "result": {"row_count": 1}, "error": "e"}
    new = next_ui_state(state, ASK_OTHER)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_submit_ok_stores_result_and_no_credentials():
    state = {"pending": {"sql": "SELECT 1"}, "result": None, "error": None}
    new = next_ui_state(state, SUBMIT_OK, {
        "columns": ["a", "b"],
        "rows": [{"a": 1, "b": 2}],
        "row_count": 1,
        "duration_ms": 42,
    })
    assert new["pending"] is None
    assert new["error"] is None
    assert new["result"] == {
        "columns": ["a", "b"],
        "rows": [{"a": 1, "b": 2}],
        "row_count": 1,
        "duration_ms": 42,
        "page": 1,
    }
    # No credentials anywhere in state
    flat = str(new)
    assert "credentials" not in flat


def test_submit_fail_keeps_pending_and_sets_error():
    state = {"pending": {"sql": "SELECT 1"}, "result": None, "error": None}
    new = next_ui_state(state, SUBMIT_FAIL, {"message": "connection failed"})
    assert new["pending"] == {"sql": "SELECT 1"}
    assert new["result"] is None
    assert new["error"] == "connection failed"


def test_page_next_changes_only_page():
    state = {
        "pending": None,
        "result": {"columns": ["a"], "rows": [{"a": i} for i in range(100)], "row_count": 100, "duration_ms": 5, "page": 1},
        "error": None,
    }
    new = next_ui_state(state, PAGE_NEXT, {"page_size": 10})
    assert new["result"]["page"] == 2
    assert new["pending"] is None
    assert new["error"] is None
    # rows unchanged
    assert len(new["result"]["rows"]) == 100


def test_page_next_capped_at_max_page():
    state = {
        "pending": None,
        "result": {"columns": ["a"], "rows": [{"a": i} for i in range(25)], "row_count": 25, "duration_ms": 5, "page": 2},
        "error": None,
    }
    new = next_ui_state(state, PAGE_NEXT, {"page_size": 10})
    assert new["result"]["page"] == 3  # max page = ceil(25/10) = 3


def test_page_prev_changes_only_page():
    state = {
        "pending": None,
        "result": {"columns": ["a"], "rows": [{"a": i} for i in range(10)], "row_count": 10, "duration_ms": 5, "page": 3},
        "error": None,
    }
    new = next_ui_state(state, PAGE_PREV)
    assert new["result"]["page"] == 2
    assert new["pending"] is None
    assert new["error"] is None


def test_page_prev_floors_at_one():
    state = {
        "pending": None,
        "result": {"columns": ["a"], "rows": [{"a": i} for i in range(10)], "row_count": 10, "duration_ms": 5, "page": 1},
        "error": None,
    }
    new = next_ui_state(state, PAGE_PREV)
    assert new["result"]["page"] == 1


def test_new_ask_clears_everything():
    state = {
        "pending": {"sql": "SELECT 1"},
        "result": {"row_count": 1},
        "error": "e",
    }
    new = next_ui_state(state, NEW_ASK)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_dataset_changed_clears_everything():
    state = {
        "pending": {"sql": "SELECT 1"},
        "result": {"row_count": 1},
        "error": "e",
    }
    new = next_ui_state(state, DATASET_CHANGED)
    assert new["pending"] is None
    assert new["result"] is None
    assert new["error"] is None


def test_no_credentials_in_state_any_event():
    state = _initial()
    events = [
        (ASK_VALIDATED, {"tenant_id": "t", "dataset_id": "d", "dialect": "sqlite", "sql": "SELECT 1", "question": "q"}),
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
    assert state == before  # original unchanged
    assert new["pending"] is None
