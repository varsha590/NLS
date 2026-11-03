"""Data policy: column-level access control and privacy boundary."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from catalog.classifier import ColumnClass, classify_column as core_classify

LOGGER = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "data_policy.yaml"


def load_policy_config() -> dict[str, Any]:
    """Load configuration from config/data_policy.yaml."""
    if not _CONFIG_PATH.exists():
        return {}
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_policy_overrides() -> dict[str, Any]:
    """Normalize config/data_policy.yaml into an overrides dictionary for the classifier."""
    cfg = load_policy_config()
    overrides = dict(cfg.get("overrides", {}))

    # Support legacy config structures
    if "columns" in cfg:
        force_block = list(overrides.get("force_block", []))
        force_mask = list(overrides.get("force_mask", []))
        force_allow = list(overrides.get("force_allow", []))
        for col, action in cfg["columns"].items():
            act = str(action).lower()
            if act == "block":
                force_block.append(col)
            elif act == "mask":
                force_mask.append(col)
            elif act == "allow":
                force_allow.append(col)
        overrides["force_block"] = force_block
        overrides["force_mask"] = force_mask
        overrides["force_allow"] = force_allow

    if "patterns" in cfg:
        overrides["patterns"] = cfg["patterns"]
    elif "auto_block_patterns" in cfg:
        overrides["patterns"] = {"block": cfg["auto_block_patterns"]}

    return overrides


def classify_column(column_key: str, sql_type: Any = "TEXT") -> str:
    """Return 'block', 'mask', or 'allow' for a column key (e.g. 'customers.email')."""
    if "." in column_key:
        table_name, column_name = column_key.rsplit(".", 1)
    else:
        table_name, column_name = "", column_key

    overrides = get_policy_overrides()
    col_class, _ = core_classify(
        table_name=table_name,
        column_name=column_name,
        sql_type=sql_type,
        overrides=overrides,
    )

    if col_class == ColumnClass.BLOCKED:
        return "block"
    if col_class == ColumnClass.MASKED:
        return "mask"
    return "allow"


def is_blocked(column_key: str, sql_type: Any = "TEXT") -> bool:
    """Return True if the column is blocked."""
    return classify_column(column_key, sql_type=sql_type) == "block"


def is_masked(column_key: str, sql_type: Any = "TEXT") -> bool:
    """Return True if the column is masked."""
    return classify_column(column_key, sql_type=sql_type) == "mask"


def blocked_columns_for_table(table_name: str, column_names: list[str]) -> set[str]:
    """Return the set of blocked column names for a given table."""
    result = set()
    for col in column_names:
        key = f"{table_name}.{col}"
        if is_blocked(key):
            result.add(col)
    return result


def mask_value(value: Any) -> str:
    """Apply partial masking to a value (never exposes full sensitive text)."""
    if value is None:
        return ""
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
    """Return the raw policy dictionary."""
    return load_policy_config()
