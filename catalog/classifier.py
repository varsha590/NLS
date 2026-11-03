"""Automated deny-first column classifier.

Determines the classification of every database column across all pipeline
consumers (schema embeddings, value embeddings, resolver, compact DDL, and logs).

Classes:
- BLOCKED: Sensitive data. Completely excluded from DDL, schema embeddings,
  retriever candidates, value indexes, prompt mappings, and logs.
- MASKED: Retained in DDL for query generation, but output values are masked.
- VALUE_LOW: Text column with low distinct count (<= threshold). Fully indexed.
- VALUE_HIGH: Text column with high distinct count and short text. Resolved at query time.
- SKIP: Non-text, keys, free text, embeddings, hashes, or unclassifiable columns.
  Retained in DDL for joins/projections (unless BLOCKED), but not indexed for values.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

LOGGER = logging.getLogger(__name__)

DEFAULT_CARDINALITY_THRESHOLD = 500
DEFAULT_MAX_AVG_TEXT_LENGTH = 100

# Default auto-block word tokens (matched against snake_case / camelCase words)
DEFAULT_BLOCK_PATTERNS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "otp",
    "email",
    "phone",
    "mobile",
    "contact",
    "address",
    "ssn",
    "aadhaar",
    "aadhar",
    "pan",
    "card",
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

# Weak or ambiguous tokens for review reporting
WEAK_BLOCK_TOKENS = frozenset({
    "pan",
    "lat",
    "lng",
    "dob",
    "birth",
    "card",
    "contact",
    "session",
    "token",
})

# Free-text column name indicators
FREE_TEXT_PATTERNS = (
    "description",
    "notes",
    "note",
    "comment",
    "comments",
    "remarks",
    "remark",
    "bio",
    "biography",
    "message",
    "messages",
    "body",
    "prompt",
    "response",
    "payload",
    "raw_text",
    "summary",
    "transcript",
    "content",
)

# Hash and embedding column name indicators
HASH_EMBEDDING_PATTERNS = (
    "embedding",
    "embeddings",
    "vector",
    "hash",
    "checksum",
    "digest",
    "sha256",
    "md5",
    "salt",
)


class ColumnClass(str, Enum):
    BLOCKED = "BLOCKED"
    MASKED = "MASKED"
    VALUE_LOW = "VALUE_LOW"
    VALUE_HIGH = "VALUE_HIGH"
    SKIP = "SKIP"


def split_identifier_tokens(name: str) -> list[str]:
    """Split an identifier (camelCase, PascalCase, snake_case) into lowercase tokens."""
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
    tokens = [t.lower() for t in re.split(r"[^a-zA-Z0-9]+", s2) if t]
    return tokens


def _matches_token_pattern(tokens: list[str], pattern: str) -> bool:
    """Check if tokens match a pattern on word boundaries.

    Handles single-word patterns (e.g. 'pan', 'lat') and multi-word patterns
    (e.g. 'account_no', 'api_key', 'ip_addr').
    """
    pattern_tokens = split_identifier_tokens(pattern)
    if not pattern_tokens:
        return False
    if len(pattern_tokens) == 1:
        return pattern_tokens[0] in tokens

    # Multi-token pattern: match consecutive subsequence
    k = len(pattern_tokens)
    for i in range(len(tokens) - k + 1):
        if tokens[i : i + k] == pattern_tokens:
            return True
    return False


def _match_override_list(
    key: str,
    bare_key: str,
    column_name: str,
    patterns: list[str] | tuple[str, ...],
) -> tuple[bool, bool]:
    """Test if a column matches an override list.

    Returns:
        (matched, is_exact): matched is True if pattern matches.
        is_exact is True only if pattern is an exact 'table.column' or 'column'
        match without wildcards.
    """
    key_cf = key.casefold()
    bare_key_cf = bare_key.casefold()
    col_cf = column_name.casefold()

    for pat in patterns:
        pat_cf = pat.strip().casefold()
        if not pat_cf:
            continue
        # Check exact matches
        if pat_cf in (key_cf, bare_key_cf):
            return True, True
        # Check wildcard pattern matching
        if any(ch in pat_cf for ch in ("*", "?", "[")):
            if (
                fnmatch.fnmatchcase(key_cf, pat_cf)
                or fnmatch.fnmatchcase(bare_key_cf, pat_cf)
                or fnmatch.fnmatchcase(col_cf, pat_cf)
            ):
                return True, False
        elif pat_cf == col_cf:
            return True, False
    return False, False


def is_text_type(sql_type: Any) -> bool:
    """Check if a SQLAlchemy or string SQL type represents character/text data."""
    type_str = str(sql_type).lower()
    # Explicit non-text markers
    non_text = (
        "int",
        "float",
        "double",
        "real",
        "decimal",
        "numeric",
        "bool",
        "date",
        "time",
        "binary",
        "blob",
        "bytea",
        "json",
        "vector",
        "uuid",
    )
    for nt in non_text:
        # Match whole word or prefix in type string
        if re.search(rf"\b{nt}\b", type_str):
            return False

    return any(marker in type_str for marker in ("char", "text", "string", "varchar", "clob"))


def is_key_column(column_name: str, is_primary_key: bool = False, is_foreign_key: bool = False) -> bool:
    """Return True if column is a primary key, foreign key, or surrogate key.

    Natural text keys (e.g. category_name, status, title) are allowed for value
    indexing if they represent semantic data values rather than opaque surrogate IDs.
    """
    name_cf = column_name.casefold()
    tokens = split_identifier_tokens(column_name)

    # Any column ending in _id or named id or key
    if name_cf == "id" or name_cf.endswith("_id") or (tokens and tokens[-1] in ("id", "pk", "fk", "key")):
        return True
    if is_foreign_key:
        return True
    if is_primary_key:
        # Natural text keys ending in semantic data words are preserved for value matching
        if tokens and tokens[-1] in ("name", "title", "status", "type", "category", "genre", "code"):
            return False
        return True
    return False


def is_candidate_text_column(
    table_name: str,
    column_name: str,
    sql_type: Any,
    is_primary_key: bool = False,
    is_foreign_key: bool = False,
    overrides: dict[str, Any] | None = None,
) -> bool:
    """Fast check whether a column is eligible for distinct count scanning.

    Returns False if the column is BLOCKED, MASKED, a key/ID, non-text,
    or matches free-text / hash / embedding patterns.
    """
    overrides = overrides or {}
    bare_table = table_name.rsplit(".", 1)[-1]
    qualified_key = f"{table_name}.{column_name}"
    bare_key = f"{bare_table}.{column_name}"
    tokens = split_identifier_tokens(column_name)

    # 1. Overrides
    if _match_override_list(qualified_key, bare_key, column_name, overrides.get("force_block", []))[0]:
        return False
    if _match_override_list(qualified_key, bare_key, column_name, overrides.get("force_mask", []))[0]:
        return False

    force_allow = overrides.get("force_allow", [])
    matched_fa, is_exact_fa = _match_override_list(qualified_key, bare_key, column_name, force_allow)

    # 2. Pattern block
    block_patterns = overrides.get("patterns", {}).get("block", DEFAULT_BLOCK_PATTERNS)
    for pat in block_patterns:
        if _matches_token_pattern(tokens, pat):
            if matched_fa and is_exact_fa:
                break
            return False

    # 3. Keys / IDs
    if is_key_column(column_name, is_primary_key=is_primary_key, is_foreign_key=is_foreign_key):
        return False

    # 4. Text type
    if not is_text_type(sql_type):
        return False

    # 5. Free text
    for ft_pat in FREE_TEXT_PATTERNS:
        if _matches_token_pattern(tokens, ft_pat):
            if not matched_fa:
                return False

    # 6. Embeddings / hashes
    for h_pat in HASH_EMBEDDING_PATTERNS:
        if _matches_token_pattern(tokens, h_pat):
            return False

    return True


def classify_column(
    table_name: str,
    column_name: str,
    sql_type: Any,
    distinct_count: int | None = None,
    avg_text_length: float | None = None,
    nullable: bool = True,
    is_primary_key: bool = False,
    is_foreign_key: bool = False,
    overrides: dict[str, Any] | None = None,
    cardinality_threshold: int = DEFAULT_CARDINALITY_THRESHOLD,
    max_avg_text_length: float = DEFAULT_MAX_AVG_TEXT_LENGTH,
) -> tuple[ColumnClass, str]:
    """Pure, unit-testable automatic deny-first column classifier.

    Returns:
        (ColumnClass, reason_str)
        reason_str contains only names, types, and counts — never real row values.
    """
    overrides = overrides or {}
    bare_table = table_name.rsplit(".", 1)[-1]
    qualified_key = f"{table_name}.{column_name}"
    bare_key = f"{bare_table}.{column_name}"
    tokens = split_identifier_tokens(column_name)

    # -------------------------------------------------------------------------
    # a. Overrides first
    # -------------------------------------------------------------------------
    force_block = overrides.get("force_block", [])
    matched_fb, _ = _match_override_list(qualified_key, bare_key, column_name, force_block)
    if matched_fb:
        return ColumnClass.BLOCKED, "override: force_block"

    force_mask = overrides.get("force_mask", [])
    matched_fm, _ = _match_override_list(qualified_key, bare_key, column_name, force_mask)
    if matched_fm:
        return ColumnClass.MASKED, "override: force_mask"

    force_val_low = overrides.get("force_value_low", [])
    matched_fvl, _ = _match_override_list(qualified_key, bare_key, column_name, force_val_low)
    if matched_fvl:
        return ColumnClass.VALUE_LOW, "override: force_value_low"

    force_val_high = overrides.get("force_value_high", [])
    matched_fvh, _ = _match_override_list(qualified_key, bare_key, column_name, force_val_high)
    if matched_fvh:
        return ColumnClass.VALUE_HIGH, "override: force_value_high"

    force_allow = overrides.get("force_allow", [])
    matched_fa, is_exact_fa = _match_override_list(qualified_key, bare_key, column_name, force_allow)

    # -------------------------------------------------------------------------
    # b. BLOCKED by name pattern (split words, not raw substrings)
    # -------------------------------------------------------------------------
    block_patterns = overrides.get("patterns", {}).get("block", DEFAULT_BLOCK_PATTERNS)
    if not block_patterns and "auto_block_patterns" in overrides:
        block_patterns = overrides.get("auto_block_patterns", DEFAULT_BLOCK_PATTERNS)

    matched_block_pattern = None
    for pat in block_patterns:
        if _matches_token_pattern(tokens, pat):
            matched_block_pattern = pat
            break

    if matched_block_pattern is not None:
        # force_allow never relaxes a name-pattern BLOCK unless the override is exact table.column
        if matched_fa and is_exact_fa:
            LOGGER.info(
                "Exact force_allow override relaxed pattern block",
                extra={"table": table_name, "column": column_name, "pattern": matched_block_pattern},
            )
        else:
            return (
                ColumnClass.BLOCKED,
                f"blocked by name pattern: '{matched_block_pattern}'",
            )

    # -------------------------------------------------------------------------
    # c. Keys and ID columns are never VALUE_* (retained in DDL for joins)
    # -------------------------------------------------------------------------
    if is_key_column(column_name, is_primary_key=is_primary_key, is_foreign_key=is_foreign_key):
        return ColumnClass.SKIP, "key or identifier column (available in DDL for joins)"

    # -------------------------------------------------------------------------
    # d. SKIP: non-text, free-text, embeddings, hashes, JSON/blob
    # -------------------------------------------------------------------------
    if not is_text_type(sql_type):
        if matched_fa:
            return ColumnClass.SKIP, f"non-text type ({sql_type}) allowed by override in DDL"
        return ColumnClass.SKIP, f"non-text type: {sql_type}"

    # Free text columns
    for ft_pat in FREE_TEXT_PATTERNS:
        if _matches_token_pattern(tokens, ft_pat):
            if matched_fa:
                break
            return ColumnClass.SKIP, f"free-text name pattern: '{ft_pat}'"

    # Embeddings and hashes
    for h_pat in HASH_EMBEDDING_PATTERNS:
        if _matches_token_pattern(tokens, h_pat):
            return ColumnClass.SKIP, f"embedding or hash column: '{h_pat}'"

    # Excessively long average text length
    if avg_text_length is not None and avg_text_length > max_avg_text_length:
        if not matched_fa:
            return (
                ColumnClass.SKIP,
                f"average text length {avg_text_length:.1f} exceeds {max_avg_text_length}",
            )

    # -------------------------------------------------------------------------
    # e. VALUE_LOW: distinct_count <= cardinality_threshold
    # -------------------------------------------------------------------------
    if distinct_count is not None:
        if distinct_count <= cardinality_threshold:
            return (
                ColumnClass.VALUE_LOW,
                f"text column with distinct count {distinct_count} <= threshold {cardinality_threshold}",
            )
        # ---------------------------------------------------------------------
        # f. VALUE_HIGH: distinct_count > threshold and short average length
        # ---------------------------------------------------------------------
        if avg_text_length is None or avg_text_length <= max_avg_text_length:
            return (
                ColumnClass.VALUE_HIGH,
                f"text column with distinct count {distinct_count} > threshold {cardinality_threshold} (short length)",
            )
        return (
            ColumnClass.SKIP,
            f"high-cardinality text column with long text (avg len {avg_text_length:.1f})",
        )

    # -------------------------------------------------------------------------
    # g. Unknown or unclassifiable means SKIP, never allow
    # -------------------------------------------------------------------------
    return ColumnClass.SKIP, f"unclassifiable column (text type '{sql_type}', count unavailable)"


def get_column_stats(
    connection: Connection,
    table: sa.Table,
    column_name: str,
    threshold: int = DEFAULT_CARDINALITY_THRESHOLD,
) -> tuple[int | None, float | None]:
    """Execute one cheap capped query for distinct count and average length.

    Uses a subquery with LIMIT threshold + 1 so full tables are never scanned.
    Never retrieves or logs real row values.
    """
    col = table.c.get(column_name)
    if col is None:
        return None, None

    try:
        # Bounded subquery: at most threshold + 1 distinct values
        subquery = (
            sa.select(col.label("val"))
            .where(col.is_not(None))
            .distinct()
            .limit(threshold + 1)
            .subquery()
        )
        val_col = subquery.c.val
        # Portable length expression
        len_expr = sa.func.length(val_col)
        stats_query = sa.select(
            sa.func.count().label("cnt"),
            sa.func.avg(len_expr).label("avg_len"),
        ).select_from(subquery)

        row = connection.execute(stats_query).fetchone()
        if row is not None:
            cnt = int(row[0]) if row[0] is not None else 0
            avg_len = float(row[1]) if row[1] is not None else None
            return cnt, avg_len
    except (sa.exc.SQLAlchemyError, Exception) as exc:
        LOGGER.debug(
            "Distinct count scan skipped or failed",
            extra={"table": table.name, "column": column_name, "error": str(exc)},
        )
    return None, None
