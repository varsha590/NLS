"""Pure UI state machine for the validated-query rerun flow.

No Streamlit imports. State holds ONLY: pending, result, error. Never credentials.
"""

from __future__ import annotations

from typing import Any

# Event names.
ASK_VALIDATED = "ask_validated"
ASK_OTHER = "ask_other"
SUBMIT_OK = "submit_ok"
SUBMIT_FAIL = "submit_fail"
PAGE_NEXT = "page_next"
PAGE_PREV = "page_prev"
NEW_ASK = "new_ask"
DATASET_CHANGED = "dataset_changed"


def _empty_pending() -> dict[str, Any]:
    return None


def _empty_result() -> dict[str, Any]:
    return None


def _initial_state() -> dict[str, Any]:
    return {
        "pending": None,
        "result": None,
        "error": None,
        "previous_tenant_id": None,
    }


def _copy_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "pending": state.get("pending"),
        "result": state.get("result"),
        "error": state.get("error"),
        "previous_tenant_id": state.get("previous_tenant_id"),
    }


def next_ui_state(
    state: dict[str, Any], event: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a new UI state dict for the given event/payload.

    Never mutates ``state``. Credentials are never stored.
    """
    if state is None:
        state = _initial_state()

    new = _copy_state(state)

    if event == NEW_ASK:
        new["pending"] = None
        new["result"] = None
        new["error"] = None
        return new

    if event == DATASET_CHANGED:
        new["pending"] = None
        new["result"] = None
        new["error"] = None
        return new

    if event == ASK_VALIDATED:
        new["pending"] = {
            "tenant_id": payload["tenant_id"],
            "dataset_id": payload["dataset_id"],
            "dialect": payload["dialect"],
            "sql": payload["sql"],
            "question": payload["question"],
        }
        new["result"] = None
        new["error"] = None
        return new

    if event == ASK_OTHER:
        new["pending"] = None
        new["result"] = None
        new["error"] = None
        return new

    if event == SUBMIT_OK:
        new["pending"] = state.get("pending")
        new["error"] = None
        new["result"] = {
            "columns": payload["columns"],
            "rows": payload["rows"],
            "row_count": payload["row_count"],
            "duration_ms": payload["duration_ms"],
            "page": 1,
        }
        return new

    if event == SUBMIT_FAIL:
        new["pending"] = state.get("pending")  # keep pending so form stays
        new["result"] = None
        new["error"] = payload["message"]
        return new

    if event == PAGE_NEXT:
        result = state.get("result")
        if result is None:
            return new
        page_size = int(payload.get("page_size", 50)) if payload else 50
        row_count = int(result.get("row_count", 0))
        max_page = max(1, (row_count + page_size - 1) // page_size) if row_count > 0 else 1
        new_result = dict(result)
        new_result["page"] = min(max_page, int(result.get("page", 1)) + 1)
        new["result"] = new_result
        return new

    if event == PAGE_PREV:
        result = state.get("result")
        if result is None:
            return new
        new_result = dict(result)
        new_result["page"] = max(1, int(result.get("page", 1)) - 1)
        new["result"] = new_result
        return new

    return new
