"""Code-defined sensitive-column policy shared by indexing and validation."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

SENSITIVE_COLUMN_PATTERNS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "ssn",
    "aadhaar",
    "aadhar",
    "pan",
    "card",
    "cvv",
    "otp",
    "email",
    "phone",
    "mobile",
    "contact",
    "address",
    "account_no",
    "ifsc",
    "upi",
    "api_key",
    "session",
    "ip_addr",
    "dob",
    "birth",
    "lat",
    "lng",
)


def split_identifier_tokens(name: str) -> list[str]:
    """Split snake_case, camelCase, and punctuation-delimited identifiers."""
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", separated)
    return [token.casefold() for token in re.split(r"[^a-zA-Z0-9]+", separated) if token]


def _matches_patterns(column_name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    tokens = split_identifier_tokens(column_name)
    for pattern in patterns:
        pattern_tokens = split_identifier_tokens(pattern)
        if pattern_tokens and any(
            tokens[index:index + len(pattern_tokens)] == pattern_tokens
            for index in range(len(tokens) - len(pattern_tokens) + 1)
        ):
            return True
    return False


def load_policy_config() -> dict[str, Any]:
    """Return the code-defined policy without reading a YAML configuration."""
    return get_policy()


def load_database_overrides(
    path: str | Path,
    metadata: Any | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Retain the legacy call shape while disabling YAML policy overrides."""
    del path, metadata
    return {}, [], []


def get_policy_overrides(database_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return code defaults with optional in-memory, non-sensitive overrides."""
    overrides: dict[str, Any] = {
        "patterns": {"block": list(SENSITIVE_COLUMN_PATTERNS)},
    }
    if database_overrides:
        policy = database_overrides.get("policy", database_overrides)
        if isinstance(policy, dict):
            for action in (
                "force_block", "force_mask", "force_allow", "force_value_low", "force_value_high"
            ):
                if action in policy:
                    overrides[action] = list(policy[action] or [])
    return overrides


def classify_column(
    column_key: str,
    sql_type: Any = "TEXT",
    policy_overrides: dict[str, Any] | None = None,
) -> str:
    """Return 'block', 'mask', or 'allow' using whole identifier tokens."""
    del sql_type
    column_name = column_key.rsplit(".", 1)[-1]
    overrides = policy_overrides or {}
    if _matches_patterns(column_name, SENSITIVE_COLUMN_PATTERNS):
        return "block"
    if _matches_patterns(column_name, tuple(overrides.get("patterns", {}).get("block", ()))):
        return "block"
    targets = overrides.get("force_block", ())
    if any(fnmatch.fnmatchcase(column_key.casefold(), str(target).casefold()) for target in targets):
        return "block"
    targets = overrides.get("force_mask", ())
    if any(fnmatch.fnmatchcase(column_key.casefold(), str(target).casefold()) for target in targets):
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
    """Return sensitive or explicitly blocked columns for one table."""
    return {
        column for column in column_names
        if is_blocked(f"{table_name}.{column}", policy_overrides=policy_overrides)
    }


def mask_value(value: Any) -> str:
    """Apply partial masking to a value (never exposes full sensitive text)."""
    if value is None:
        return ""
    text = str(value)
    if "@" in text:
        local, domain = text.split("@", 1)
        return (local[0] + "***@" if len(local) > 1 else "***@") + domain
    if len(text) > 4:
        return text[0] + "***" + text[-1]
    return "***"


def get_policy() -> dict[str, Any]:
    """Return a serializable view of the code-defined policy."""
    return {"patterns": {"block": list(SENSITIVE_COLUMN_PATTERNS)}}
