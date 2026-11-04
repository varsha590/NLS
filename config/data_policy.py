"""Data policy: column-level access control and privacy boundary."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from catalog.classifier import (
    ColumnClass,
    _is_credential_name,
    classify_column as core_classify,
    split_identifier_tokens,
)

LOGGER = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "data_policy.yaml"


def load_policy_config() -> dict[str, Any]:
    """Load configuration from config/data_policy.yaml."""
    if not _CONFIG_PATH.exists():
        return {}
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_database_overrides(
    path: str | Path,
    metadata: Any | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Load namespace-local overrides and report stale or unsafe targets by name only."""
    override_path = Path(path)
    if not override_path.is_file():
        return {}, [], []
    with override_path.open(encoding="utf-8") as file_obj:
        raw = yaml.safe_load(file_obj) or {}
    if not isinstance(raw, dict):
        return {}, [], ["overrides.yaml: invalid root structure"]

    policy = raw.get("policy", {})
    if not isinstance(policy, dict):
        policy = {}
        raw["policy"] = policy
    stale: list[str] = []
    warnings: list[str] = []
    if metadata is None:
        return raw, stale, warnings

    catalog_keys = {
        f"{table.name}.{column.name}".casefold()
        for table in metadata.tables.values()
        for column in table.columns
    }
    for action in (
        "force_block", "force_mask", "force_allow", "force_value_low", "force_value_high"
    ):
        valid: list[str] = []
        for target in policy.get(action, []) or []:
            target = str(target).strip()
            column_name = target.rsplit(".", 1)[-1]
            exact_catalog_target = (
                target.casefold() in catalog_keys
                and not any(character in target for character in "*?[]")
            )
            if action == "force_allow" and _is_credential_name(
                split_identifier_tokens(column_name)
            ):
                if not exact_catalog_target:
                    warnings.append(f"Rejected credential-name force_allow: {target}")
                    continue
            if not exact_catalog_target:
                stale.append(target)
                continue
            valid.append(target)
        policy[action] = valid
    return raw, sorted(set(stale)), sorted(set(warnings))


def get_policy_overrides(database_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge generic global policy with validated namespace-local policy overrides."""
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

    database_policy = (database_overrides or {}).get("policy", {})
    if isinstance(database_policy, dict):
        for action in (
            "force_block", "force_mask", "force_allow", "force_value_low", "force_value_high"
        ):
            if action in database_policy:
                overrides[action] = list(database_policy.get(action) or [])
        if isinstance(database_policy.get("patterns"), dict):
            patterns = dict(overrides.get("patterns", {}))
            patterns.update(database_policy["patterns"])
            overrides["patterns"] = patterns

    return overrides


def classify_column(
    column_key: str,
    sql_type: Any = "TEXT",
    policy_overrides: dict[str, Any] | None = None,
) -> str:
    """Return 'block', 'mask', or 'allow' for a column key (e.g. 'customers.email')."""
    if "." in column_key:
        table_name, column_name = column_key.rsplit(".", 1)
    else:
        table_name, column_name = "", column_key

    overrides = policy_overrides if policy_overrides is not None else get_policy_overrides()
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


def is_blocked(
    column_key: str,
    sql_type: Any = "TEXT",
    policy_overrides: dict[str, Any] | None = None,
) -> bool:
    """Return True if the column is blocked."""
    return classify_column(column_key, sql_type=sql_type, policy_overrides=policy_overrides) == "block"


def is_masked(
    column_key: str,
    sql_type: Any = "TEXT",
    policy_overrides: dict[str, Any] | None = None,
) -> bool:
    """Return True if the column is masked."""
    return classify_column(column_key, sql_type=sql_type, policy_overrides=policy_overrides) == "mask"


def blocked_columns_for_table(
    table_name: str,
    column_names: list[str],
    policy_overrides: dict[str, Any] | None = None,
) -> set[str]:
    """Return the set of blocked column names for a given table."""
    result = set()
    for col in column_names:
        key = f"{table_name}.{col}"
        if is_blocked(key, policy_overrides=policy_overrides):
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
