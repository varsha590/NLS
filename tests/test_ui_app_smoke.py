"""Smoke tests for the Streamlit entrypoint and widget-key uniqueness.

These use Streamlit's AppTest harness with local temp data only: no network,
no live server, no embedding model, and no Qdrant connection.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

try:
    from streamlit.testing.v1 import AppTest

    HAS_APPTEST = True
except Exception:  # pragma: no cover
    HAS_APPTEST = False


REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "app.py"
UI_DIR = REPO_ROOT / "ui"


def test_from_ui_app_import_main_is_callable():
    from ui.app import main

    assert callable(main)


def test_no_duplicate_widget_key_literals_in_ui():
    keys: list[str] = []
    for path in sorted(UI_DIR.glob("*.py")):
        keys.extend(re.findall(r'key="([^"]+)"', path.read_text(encoding="utf-8")))
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert not duplicates, f"Duplicate widget key literals in ui/: {duplicates}"


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest is not available")
def test_fresh_load_shows_only_tenant_label(monkeypatch, tmp_path):
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(tmp_path / "datasets"))

    at = AppTest.from_file(str(ENTRYPOINT)).run()

    assert not at.exception
    assert [widget.label for widget in at.text_input] == ["Tenant label"]
    assert not any(button.label == "Search" for button in at.form_submit_button)
    assert not any(button.label == "Connect" for button in at.form_submit_button)
    assert not at.download_button


@pytest.mark.skipif(not HAS_APPTEST, reason="AppTest is not available")
def test_pending_sql_renders_once_and_credentials_only_after(monkeypatch, tmp_path):
    from ingestion.datasets import DatasetRegistry

    dataset_root = tmp_path / "datasets"
    monkeypatch.setenv("DATASET_STORAGE_PATH", str(dataset_root))
    registry = DatasetRegistry(dataset_root)
    registered = registry.register(
        "items.sql",
        b"CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="acme",
        dialect_override="mysql",
        embedding_model_name="test-embedding-model",
    )
    metadata_path = (
        registry.dataset_directory("acme", registered["dataset_id"]) / "dataset.json"
    )
    metadata = json.loads(metadata_path.read_text())
    metadata["indexed"] = True
    metadata_path.write_text(json.dumps(metadata))

    at = AppTest.from_file(str(ENTRYPOINT))
    at.session_state["tenant_id"] = "acme"
    at.session_state["previous_tenant_id"] = "acme"
    at.session_state["selected_dataset_id"] = registered["dataset_id"]
    at.session_state["active_dataset_id"] = registered["dataset_id"]
    at.session_state["ui_state"] = {
        "pending": {
            "tenant_id": "acme",
            "dataset_id": registered["dataset_id"],
            "dialect": "mysql",
            "sql": "SELECT * FROM items",
            "question": "show items",
        },
        "result": None,
        "error": None,
        "previous_tenant_id": "acme",
    }

    at.run()

    assert not at.exception
    assert len(at.download_button) == 1
    assert at.download_button[0].label == "Download SQL"
    assert [code.value for code in at.code] == ["SELECT * FROM items"]
    labels = {widget.label for widget in at.text_input}
    assert {"Host", "Username", "Password", "Database"} <= labels
    assert any(button.label == "Connect" for button in at.form_submit_button)
