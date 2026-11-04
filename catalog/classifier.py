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
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from config.data_policy import SENSITIVE_COLUMN_PATTERNS

LOGGER = logging.getLogger(__name__)

DEFAULT_CARDINALITY_THRESHOLD = 500
DEFAULT_MAX_AVG_TEXT_LENGTH = 100

# Default auto-block word tokens (matched against snake_case / camelCase words)
DEFAULT_BLOCK_PATTERNS = SENSITIVE_COLUMN_PATTERNS

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

CREDENTIAL_BLOCK_PATTERNS = ("password", "passwd", "pwd", "token", "secret", "otp", "api_key")
FLAG_OPTION_PAIRS = (
    frozenset(("0", "1")),
    frozenset(("false", "true")),
    frozenset(("no", "yes")),
    frozenset(("n", "y")),
    frozenset(("off", "on")),
    frozenset(("disabled", "enabled")),
)

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


def normalize_sql_type_name(sql_type: Any) -> str:
    """Normalize a reflected or textual SQL type, dropping charset/collation suffixes."""
    type_name = str(sql_type).strip()
    type_name = re.split(r"\s+(?:COLLATE|CHARACTER\s+SET|CHARSET)\s+", type_name, maxsplit=1, flags=re.IGNORECASE)[0]
    return type_name.strip().casefold()


def parse_enum_options(sql_type: Any) -> tuple[str, ...] | None:
    """Read ENUM/SET options from type metadata or its SQL type declaration."""
    declared_options = getattr(sql_type, "enums", None)
    if declared_options:
        return tuple(str(option) for option in declared_options)

    type_text = str(sql_type)
    match = re.search(r"\b(?:enum|set)\s*\(", type_text, re.IGNORECASE)
    if match is None:
        return None

    options: list[str] = []
    index = match.end()
    while index < len(type_text):
        while index < len(type_text) and type_text[index].isspace():
            index += 1
        if index >= len(type_text) or type_text[index] != "'":
            return None
        index += 1
        value: list[str] = []
        while index < len(type_text):
            character = type_text[index]
            if character == "\\" and index + 1 < len(type_text):
                value.append(type_text[index + 1])
                index += 2
            elif character == "'":
                if index + 1 < len(type_text) and type_text[index + 1] == "'":
                    value.append("'")
                    index += 2
                else:
                    index += 1
                    break
            else:
                value.append(character)
                index += 1
        else:
            return None
        options.append("".join(value))
        while index < len(type_text) and type_text[index].isspace():
            index += 1
        if index < len(type_text) and type_text[index] == ",":
            index += 1
            continue
        if index < len(type_text) and type_text[index] == ")":
            return tuple(options) or None
        return None
    return None


def _is_credential_name(tokens: list[str]) -> bool:
    return any(_matches_token_pattern(tokens, pattern) for pattern in CREDENTIAL_BLOCK_PATTERNS)


def reviewable_sensitive_name_tokens(
    column_name: str,
    block_patterns: tuple[str, ...] | list[str] = DEFAULT_BLOCK_PATTERNS,
) -> list[str]:
    """Return matched non-credential sensitive-name patterns for report review."""
    tokens = split_identifier_tokens(column_name)
    if _is_credential_name(tokens):
        return []
    return [
        pattern
        for pattern in block_patterns
        if pattern in DEFAULT_BLOCK_PATTERNS and _matches_token_pattern(tokens, pattern)
    ]


def is_pii_shaped_value(value: Any) -> bool:
    """Detect obvious contact/identifier shapes without retaining or reporting values."""
    text = str(value).strip()
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", text):
        return True
    if re.fullmatch(r"\+?[\d().\-\s]{7,}", text) and sum(char.isdigit() for char in text) >= 7:
        return True
    if re.fullmatch(r"\d{5}(?:-\d{4})?", text):
        return True
    if re.search(
        r"\b(?:p\.?\s*o\.?\s*box|\d{1,6}\s+[\w.'-]+(?:\s+[\w.'-]+){0,3}\s+(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|court|ct|boulevard|blvd))\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def is_flag_like_options(options: tuple[str, ...] | list[str]) -> bool:
    """Identify numeric option sets or conventional two-value boolean labels."""
    normalized = tuple(option.strip().casefold() for option in options)
    if normalized and all(re.fullmatch(r"\d+", option) for option in normalized):
        return True
    return len(normalized) == 2 and frozenset(normalized) in FLAG_OPTION_PAIRS


def is_text_type(sql_type: Any) -> bool:
    """Check if a SQLAlchemy or string SQL type represents character/text data."""
    type_str = normalize_sql_type_name(sql_type)
    if re.match(r"(?:enum|set)\s*\(", type_str):
        return True
    if type_str in ("enum", "set"):
        return True
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
            if pat in DEFAULT_BLOCK_PATTERNS and not _is_credential_name(tokens):
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
    sensitive_values_clean: bool = False,
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

    options = parse_enum_options(sql_type)
    options_have_pii_shape = options is not None and any(is_pii_shaped_value(option) for option in options)
    credential_named = _is_credential_name(tokens)
    reviewable_name = matched_block_pattern in DEFAULT_BLOCK_PATTERNS and not credential_named
    options_are_safe = options is not None and not options_have_pii_shape and reviewable_name

    if matched_block_pattern is not None:
        # force_allow never relaxes a name-pattern BLOCK unless the override is exact table.column
        if matched_fa and is_exact_fa:
            LOGGER.info(
                "Exact force_allow override relaxed pattern block",
                extra={"table": table_name, "column": column_name, "pattern": matched_block_pattern},
            )
        elif not (options_are_safe or (reviewable_name and sensitive_values_clean)):
            return (
                ColumnClass.BLOCKED,
                f"blocked by name pattern: '{matched_block_pattern}'",
            )

    if options_have_pii_shape:
        return ColumnClass.BLOCKED, "blocked because declared options have a PII-like shape"

    # -------------------------------------------------------------------------
    # c. Keys and ID columns are never VALUE_* (retained in DDL for joins)
    # -------------------------------------------------------------------------
    if is_key_column(column_name, is_primary_key=is_primary_key, is_foreign_key=is_foreign_key):
        return ColumnClass.SKIP, "key or identifier column (available in DDL for joins)"

    if options is not None:
        option_count = len(options)
        if option_count <= cardinality_threshold:
            return ColumnClass.VALUE_LOW, f"declared option count {option_count} <= threshold {cardinality_threshold}"
        return ColumnClass.VALUE_HIGH, f"declared option count {option_count} > threshold {cardinality_threshold}"

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
            if matched_block_pattern is not None and sensitive_values_clean:
                return ColumnClass.VALUE_LOW, f"low-cardinality values ({distinct_count}) appear non-PII; manual review recommended"
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
    on_error: Callable[[str], None] | None = None,
) -> tuple[int | None, float | None]:
    """Execute one cheap capped query for distinct count and average length.

    Uses a subquery with LIMIT threshold + 1 so full tables are never scanned.
    Never retrieves or logs real row values.
    """
    col = table.c.get(column_name)
    if col is None:
        LOGGER.warning(
            "Column stats unavailable for %s.%s (%s)",
            table.name,
            column_name,
            "column_not_found",
            extra={"table": table.name, "column": column_name, "error_category": "column_not_found"},
        )
        if on_error:
            on_error("column_not_found")
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
        category = "no_result"
        LOGGER.warning(
            "Column stats unavailable for %s.%s (%s)",
            table.name,
            column_name,
            category,
            extra={"table": table.name, "column": column_name, "error_category": category},
        )
        if on_error:
            on_error(category)
    except Exception as exc:
        if isinstance(exc, sa.exc.OperationalError):
            category = "operational_or_connection_error"
        elif isinstance(exc, sa.exc.ProgrammingError):
            category = "query_or_schema_error"
        elif isinstance(exc, sa.exc.DataError):
            category = "data_error"
        elif isinstance(exc, sa.exc.SQLAlchemyError):
            category = "database_error"
        else:
            category = "unexpected_error"
        LOGGER.warning(
            "Column stats unavailable for %s.%s (%s)",
            table.name,
            column_name,
            category,
            extra={"table": table.name, "column": column_name, "error_category": category},
        )
        if on_error:
            on_error(category)
    return None, None


def get_column_values_have_pii_shape(
    connection: Connection,
    table: sa.Table,
    column_name: str,
    threshold: int = DEFAULT_CARDINALITY_THRESHOLD,
    on_error: Callable[[str], None] | None = None,
) -> bool | None:
    """Check bounded distinct values in memory and return only whether a PII shape was found."""
    col = table.c.get(column_name)
    if col is None:
        category = "column_not_found"
        LOGGER.warning(
            "Column value-shape check unavailable for %s.%s (%s)",
            table.name,
            column_name,
            category,
            extra={"table": table.name, "column": column_name, "error_category": category},
        )
        if on_error:
            on_error(category)
        return None

    try:
        query = (
            sa.select(col)
            .where(col.is_not(None))
            .distinct()
            .limit(threshold + 1)
        )
        values = connection.execute(query).scalars().all()
        return any(is_pii_shaped_value(value) for value in values)
    except Exception as exc:
        if isinstance(exc, sa.exc.OperationalError):
            category = "operational_or_connection_error"
        elif isinstance(exc, sa.exc.ProgrammingError):
            category = "query_or_schema_error"
        elif isinstance(exc, sa.exc.DataError):
            category = "data_error"
        elif isinstance(exc, sa.exc.SQLAlchemyError):
            category = "database_error"
        else:
            category = "unexpected_error"
        LOGGER.warning(
            "Column value-shape check unavailable for %s.%s (%s)",
            table.name,
            column_name,
            category,
            extra={"table": table.name, "column": column_name, "error_category": category},
        )
        if on_error:
            on_error(category)
        return None
