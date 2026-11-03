"""Data policy: column-level access control for sensitive data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "data_policy.yaml"


def _load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _auto_block_patterns() -> list[str]:
    cfg = _load_config()
    return [p.casefold() for p in cfg.get("auto_block_patterns", [])]


def _explicit_columns() -> dict[str, str]:
    cfg = _load_config()
    return {k.casefold(): v for k, v in cfg.get("columns", {}).items()}


def classify_column(column_key: str) -> str:
    """Return 'block', 'mask', or 'allow' for a column key like 'customers.email'."""
    explicit = _explicit_columns()
    key_cf = column_key.casefold()
    if key_cf in explicit:
        return explicit[key_cf]
    # Auto-block based on column name
    col_name = column_key.rsplit(".", 1)[-1].casefold()
    for pattern in _auto_block_patterns():
        if pattern in col_name:
            return "block"
    return "allow"


def is_blocked(column_key: str) -> bool:
    return classify_column(column_key) == "block"


def is_masked(column_key: str) -> bool:
    return classify_column(column_key) == "mask"


def blocked_columns_for_table(table_name: str, column_names: list[str]) -> set[str]:
    """Return set of blocked column names for a table."""
    result = set()
    for col in column_names:
        key = f"{table_name}.{col}"
        if is_blocked(key):
            result.add(col)
    return result


def mask_value(value: Any) -> str:
    """Apply partial masking to a value."""
    s = str(value)
    if "@" in s:
        local, domain = s.split("@", 1)
        if len(local) > 1:
            return local[0] + "***@" + domain
        return "***@" + domain
    if len(s) > 4:
        return s[0] + "***" + s[-1]
    return "***"


def get_policy() -> dict[str, Any]:
    return _load_config()