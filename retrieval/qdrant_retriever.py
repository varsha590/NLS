"""Pure-logic schema retriever with roll-up scoring, FK expansion, and table selection.

No Qdrant, no FAISS, no external dependencies. Uses only SchemaMetadata from schema.json.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo

from retrieval.qdrant_store import (
    QdrantIndexNotReadyError,
    QdrantMetadataMismatchError,
    QdrantStorageError,
    QdrantVectorStore,
    VECTOR_SIZE,
)
from config.data_policy import is_blocked, is_masked
from config.settings import Settings

LOGGER = logging.getLogger(__name__)


DEFAULT_SELECTED_COUNT = 3
MAX_SELECTED_COUNT = 5
MAX_TABLES_GROQ = 8
DEFAULT_DOMINANCE_RATIO = 2.0
DEFAULT_UBIQUITOUS_COLUMN_RATIO = 0.5
DEFAULT_CONTEXT_TOP_TABLES = 3


@dataclass
class RetrievalResult:
    """Result of schema retrieval with roll-up scoring and FK expansion."""

    tables: List[str]
    typed_hits: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    used_qdrant: bool = False
    truncated: bool = False
    ambiguity_flag: bool = False


def _lexical_tokens(value: str) -> list[str]:
    """Extract lowercase alphanumeric tokens from a string."""
    import re
    return re.findall(r"[a-zA-Z0-9_]+", value.casefold())


def compute_rollup_score(
    s_val: float,
    s_col: float,
    s_rel: float,
    s_tbl: float,
    types_present: int = 0,
) -> float:
    """Compute the roll-up score for a table.

    formula: 1.2 * S_val + 1.0 * S_col + 0.8 * S_rel + 0.6 * S_tbl + 0.03 * max(0, types_present - 1)
    """
    return (
        1.2 * s_val
        + 1.0 * s_col
        + 0.8 * s_rel
        + 0.6 * s_tbl
        + 0.03 * max(0, types_present - 1)
    )


def _score_from_similarity(sim: float) -> float:
    """Convert a similarity/vector score to the S_* component values.

    A raw similarity of x maps to S_val=x, S_col=x*0.8, S_rel=x*0.6, S_tbl=x*0.4.
    This is a simplified mapping; actual implementations may differ.
    """
    return sim


def select_tables(
    scored_tables: List[Tuple[str, float]],
    exact_matches: Optional[Set[str]] = None,
    default_k: int = DEFAULT_SELECTED_COUNT,
    max_k: int = MAX_SELECTED_COUNT,
) -> List[str]:
    """Select tables based on exact-value priority then score fill.

    - exact_matches tables are forced into selection first (these are tables where
      the user's query exactly matched a value in that table).
    - Remaining slots filled by highest roll-up score.
    - Fuzzy (non-exact) matches never force table selection.
    - At most max_k tables are returned.
    """
    if exact_matches is None:
        exact_matches = set()

    selected: List[str] = []
    selected_set: Set[str] = set()

    # Force exact-match tables first
    for table_name in scored_tables:
        name = table_name[0]
        if name in exact_matches and name not in selected_set:
            selected.append(name)
            selected_set.add(name)

    # Fill remaining slots by score (already sorted highest first)
    if len(selected) < default_k:
        for table_name, score in scored_tables:
            if len(selected) >= max_k:
                break
            if table_name not in selected_set:
                selected.append(table_name)
                selected_set.add(table_name)

    # If we still have room up to max_k, fill from score-sorted remaining
    if len(selected) < max_k:
        for table_name, score in scored_tables:
            if len(selected) >= max_k:
                break
            if table_name not in selected_set:
                selected.append(table_name)
                selected_set.add(table_name)

    return selected[:max_k]


def expand_fk_neighbors(
    metadata: SchemaMetadata,
    selected_tables: List[str],
    max_tables: int = MAX_TABLES_GROQ,
) -> Tuple[List[str], bool]:
    """Expand selected tables with 1-hop FK neighbors from schema.json.

    Order: join-path tables (shortest path first, alphabetical tie-break),
    then direct neighbors.
    Returns (expanded_table_list, truncated_flag).

    - 1-hop only: no 2-hop traversal.
    - Hard maximum max_tables tables sent to Groq.
    - Join-path tables ordered by shortest path first, then alphabetical tie-break.
    - Direct neighbors come after join-path tables.
    - If mandatory join-path tables cannot fit within max_tables, set truncated=True.
    - Never silently discard a mandatory join-path table.
    - Direct neighbors may be dropped to cap at max_tables.
    """
    expanded: List[str] = []
    expanded_set: Set[str] = set()
    truncated = False

    # Step 1: Add selected tables first
    for table_name in selected_tables:
        if table_name not in expanded_set:
            expanded.append(table_name)
            expanded_set.add(table_name)

    # Step 2: Collect 1-hop FK neighbors from schema.json
    # Each join-path table gets a path_length: 1 for direct FK from selected table.
    # Since we only do 1-hop traversal, all join-path tables have path_length=1,
    # but we track it for correct ordering and future extensibility.
    join_path_tables: List[Tuple[int, str]] = []  # (path_length, table_name)
    direct_neighbors: List[str] = []

    for table_name in selected_tables:
        table = metadata.get_table(table_name)
        if table is None:
            continue
        for fk in table.foreign_keys:
            remote_table = fk.get("remote_table")
            if remote_table and remote_table not in expanded_set:
                # All 1-hop remote tables from selected tables are join-path tables
                # with path length 1. Alphabetical tie-break will order equals.
                join_path_tables.append((1, remote_table))

    # Sort join-path tables by shortest path first, then alphabetical tie-break
    join_path_tables.sort(key=lambda x: (x[0], x[1]))

    # Step 3: Add join-path tables first
    for path_length, table_name in join_path_tables:
        if table_name not in expanded_set:
            # Check if there's room for this join-path table
            if len(expanded) >= max_tables:
                # Mandatory join-path table cannot fit; mark truncated
                # but never silently drop a previously added join-path table
                truncated = True
                # Skip this table - it won't be added, but truncated indicates the condition
                continue
            expanded.append(table_name)
            expanded_set.add(table_name)

    # Step 4: Add direct neighbors (after join-path tables), capped at max_tables
    for table_name in selected_tables:
        table = metadata.get_table(table_name)
        if table is None:
            continue
        for fk in table.foreign_keys:
            remote_table = fk.get("remote_table")
            if remote_table and remote_table not in expanded_set:
                direct_neighbors.append(remote_table)

    # Sort direct neighbors alphabetically
    direct_neighbors.sort()
    for table_name in direct_neighbors:
        if table_name not in expanded_set:
            if len(expanded) >= max_tables:
                truncated = True
                # Direct neighbor can't fit; drop it to cap
                continue
            expanded.append(table_name)
            expanded_set.add(table_name)

    # Step 5: Final cap — ensure we never exceed max_tables
    if len(expanded) > max_tables:
        truncated = True
        expanded = expanded[:max_tables]

    return expanded, truncated


def build_table_context(
    metadata: SchemaMetadata,
    table_name: str,
    sensitive_filter: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build context for a single table from schema.json after sensitive filter.

    - Every column except BLOCKED/MASKED (SKIP and VALUE_HIGH stay visible, name and type only)
    - Neighbors include join keys plus their other visible columns
    - table.description and column.comment are omitted
    """
    table = metadata.get_table(table_name)
    if table is None:
        return {"table_name": table_name, "columns": [], "neighbors": []}

    # Filter columns: SKIP and VALUE_HIGH stay visible, BLOCKED/MASKED are excluded
    # Name and type only - no comment/description
    allowed_cols: List[dict[str, Any]] = []
    for column in table.columns:
        col_key = f"{table_name}.{column.name}"
        # Check if column is blocked or masked
        from config.data_policy import is_blocked, is_masked

        if is_blocked(col_key, policy_overrides=sensitive_filter) or is_masked(
            col_key, policy_overrides=sensitive_filter
        ):
            continue
        # SKIP and VALUE_HIGH stay visible
        # Include name and type only, omit comment
        allowed_cols.append(
            {"name": column.name, "data_type": column.data_type}
        )

    # Build neighbors: join keys plus their other visible columns
    neighbors: List[dict[str, Any]] = []
    for fk in table.foreign_keys:
        remote_table = fk.get("remote_table")
        remote_cols = fk.get("remote_cols", [])
        if remote_table:
            remote_table_obj = metadata.get_table(remote_table)
            if remote_table_obj is not None:
                # Add the join key column from the remote table
                for col in remote_table_obj.columns:
                    if col.name in remote_cols:
                        col_key = f"{remote_table}.{col.name}"
                        from config.data_policy import is_blocked, is_masked

                        if not (is_blocked(col_key, policy_overrides=sensitive_filter) or is_masked(
                            col_key, policy_overrides=sensitive_filter
                        )):
                            neighbors.append(
                                {"name": col.name, "data_type": col.data_type, "table": remote_table}
                            )

    return {
        "table_name": table_name,
        "columns": allowed_cols,
        "neighbors": neighbors,
    }


def retrieve(
    metadata: SchemaMetadata,
    query: str,
    selected_k: int = DEFAULT_SELECTED_COUNT,
    max_tables: int = MAX_TABLES_GROQ,
    sensitive_filter: Optional[dict[str, Any]] = None,
    exact_value_tables: Optional[Set[str]] = None,
    qdrant_store: Optional[QdrantVectorStore] = None,
    qdrant_tenant_id: str = "",
    qdrant_dataset_id: str = "",
    qdrant_embedding_model_name: str = "",
    qdrant_embedding_dimension: int = VECTOR_SIZE,
    qdrant_dataset_metadata_path: str | None = None,
    query_vector: Sequence[float] | None = None,
    settings: Settings | None = None,
) -> RetrievalResult:
    """Pure-logic schema retrieval with roll-up scoring and FK expansion.

    Uses the supplied question embedding for typed Qdrant searches. Without a
    query vector, retrieval stays on the lexical-only path. Results are scored,
    selected, and expanded using the local schema metadata.
    """
    if exact_value_tables is None:
        exact_value_tables = set()
    dominance_ratio = (
        settings.dominance_ratio if settings is not None else DEFAULT_DOMINANCE_RATIO
    )
    ubiquitous_ratio = (
        settings.ubiquitous_column_ratio
        if settings is not None
        else DEFAULT_UBIQUITOUS_COLUMN_RATIO
    )
    ignored_columns = (
        settings.ignored_columns if settings is not None else ()
    )
    context_top_tables = (
        settings.context_top_tables
        if settings is not None
        else DEFAULT_CONTEXT_TOP_TABLES
    )

    # A missing embedding deliberately selects lexical fallback; never query with a zero vector.
    qdrant_results: dict[str, list[dict[str, Any]]] = {}
    qdrant_search_succeeded = False
    if (
        qdrant_store is not None
        and qdrant_tenant_id
        and qdrant_dataset_id
        and qdrant_dataset_metadata_path
        and query_vector is not None
    ):
        try:
            qdrant_results["table"] = qdrant_store.search_table(
                query_vector,
                qdrant_tenant_id,
                qdrant_dataset_id,
                selected_k,
                qdrant_dataset_metadata_path,
                qdrant_embedding_model_name,
                qdrant_embedding_dimension,
            )
            column_search = qdrant_store.search_column(
                query_vector,
                qdrant_tenant_id,
                qdrant_dataset_id,
                selected_k,
                qdrant_dataset_metadata_path,
                qdrant_embedding_model_name,
                qdrant_embedding_dimension,
            )
            qdrant_results["column"] = column_search
            # Relationship search (limit: selected_k * 2)
            rel_search = qdrant_store.search_relationship(
                query_vector,
                qdrant_tenant_id,
                qdrant_dataset_id,
                selected_k,
                qdrant_dataset_metadata_path,
                qdrant_embedding_model_name,
                qdrant_embedding_dimension,
            )
            qdrant_results["relationship"] = rel_search
            master_search = qdrant_store.search_master_value(
                query_vector,
                qdrant_tenant_id,
                qdrant_dataset_id,
                selected_k,
                qdrant_dataset_metadata_path,
                qdrant_embedding_model_name,
                qdrant_embedding_dimension,
            )
            qdrant_results["master_value"] = master_search
            qdrant_search_succeeded = True
        except QdrantIndexNotReadyError:
            raise
        except QdrantMetadataMismatchError:
            raise
        except QdrantStorageError as error:
            # Other Qdrant errors: explicit logged fallback to pure-logic lexical scoring
            LOGGER.warning(
                "Qdrant search failed; falling back to pure-logic lexical scoring: %s",
                error,
            )
            qdrant_results = {}

    # Step 1: Compute roll-up scores for all tables
    vector_scores: dict[str, dict[str, float]] = {}
    for document_type, results in qdrant_results.items():
        for result in results:
            table_name = result.get("table_name")
            if not table_name:
                continue
            scores = vector_scores.setdefault(table_name, {})
            scores[document_type] = max(
                scores.get(document_type, 0.0), float(result.get("similarity", 0.0))
            )

    scored_tables: List[Tuple[str, float]] = []
    query_tokens = set(_lexical_tokens(query))
    for table_name, table in metadata.tables.items():
        if qdrant_search_succeeded:
            table_scores = vector_scores.get(table_name, {})
            s_val = table_scores.get("master_value", 0.0)
            s_col = table_scores.get("column", 0.0)
            s_rel = table_scores.get("relationship", 0.0)
            s_tbl = table_scores.get("table", 0.0)
            types_present = len(table_scores)
        else:
            s_val = 1.0 if table_name in exact_value_tables else 0.0
            s_col = 0.0
            s_rel = 0.0
            s_tbl = 0.0
            types_present = 0
            if query_tokens:
                for column in table.columns:
                    if column.name.casefold() in query_tokens:
                        s_rel += 0.5
                col_token_count = sum(
                    len(_lexical_tokens(column.name)) + len(_lexical_tokens(column.data_type))
                    for column in table.columns
                )
                s_col = min(1.0, col_token_count / len(query_tokens)) if col_token_count else 0.0
            table_name_tokens = set(_lexical_tokens(table_name))
            if table_name_tokens and query_tokens:
                s_tbl = len(table_name_tokens & query_tokens) / len(query_tokens)

        score = compute_rollup_score(s_val, s_col, s_rel, s_tbl, types_present)
        scored_tables.append((table_name, score))

    # Sort by score descending, then by name for tie-breaking
    scored_tables.sort(key=lambda x: (-x[1], x[0]))

    # Step 2: Select only the tables that will fit the LLM context.
    selection_cap = max(1, min(int(max_tables), int(context_top_tables)))
    selected = select_tables(
        scored_tables,
        exact_matches=exact_value_tables,
        default_k=selected_k,
        max_k=selection_cap,
    )

    # Step 3: Expand with FK neighbors
    expanded, truncated = expand_fk_neighbors(metadata, selected, max_tables=max_tables)

    # Step 4: Limit the LLM context to the top-scored tables.
    context_tables = expanded[: max(1, int(context_top_tables))]

    # Step 5: Build ambiguity flag over the tables actually sent to the LLM.
    ubiquitous_columns = None
    if qdrant_search_succeeded:
        ubiquitous_columns = _dataset_ubiquitous_columns(
            qdrant_store,
            qdrant_tenant_id,
            qdrant_dataset_id,
            metadata,
            ubiquitous_ratio,
        )
    ambiguity_flag = _compute_ambiguity_flag(
        query,
        metadata,
        context_tables,
        scored_tables=scored_tables,
        ubiquitous_columns=ubiquitous_columns,
        dominance_ratio=dominance_ratio,
        ignored_columns=ignored_columns,
    )

    return RetrievalResult(
        tables=context_tables,
        typed_hits=qdrant_results,
        used_qdrant=qdrant_search_succeeded,
        truncated=truncated,
        ambiguity_flag=ambiguity_flag,
    )


def _split_into_tokens(name: str) -> list[str]:
    """Split a snake_case or identifier name into individual tokens.

    Falls back to single-token if splitting yields the whole name unchanged.
    """
    import re
    # Split on underscores and camelCase boundaries
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", separated)
    tokens = [token.casefold() for token in re.split(r"[^a-zA-Z0-9]+", separated) if token]
    # If splitting didn't actually split (e.g., single word), return the original
    if len(tokens) <= 1:
        return [name.casefold()]
    return tokens


def _singularize(token: str) -> str:
    """Reduce a generic English plural token to its singular form."""
    if token.endswith("ies") and len(token) > 3:
        return token[:-3] + "y"
    if token.endswith("sses") and len(token) > 4:
        return token[:-2]
    if token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if token.endswith("ses") and len(token) > 3:
        return token[:-2]
    if token.endswith("us") and len(token) > 3:
        return token
    if token.endswith("s") and not token.endswith("ss") and len(token) > 1:
        return token[:-1]
    return token


def _normalize_tokens(value: str) -> list[str]:
    """Split and normalize a table/column/query token consistently.

    Handles snake_case/camelCase, drops one-letter type prefixes (vDisplayName,
    iRecordId, e_status), and singularizes generic English plurals.
    """
    tokens = [_singularize(token) for token in _split_into_tokens(value)]
    if len(tokens) > 1:
        tokens = [token for token in tokens if len(token) > 1 or token.isdigit()]
    return tokens


def _dataset_ubiquitous_columns(
    qdrant_store: Any,
    tenant_id: str,
    dataset_id: str,
    metadata: SchemaMetadata,
    threshold: float,
) -> Optional[Set[str]]:
    """Return column names present in more than *threshold* of schema tables.

    Reads column/table payloads from Qdrant for the explicit tenant/dataset
    scope and caches the result per dataset on the store instance. Returns
    None when schema points are unavailable so callers can skip the rule.
    """
    if qdrant_store is None or not tenant_id or not dataset_id:
        return None
    cache = getattr(qdrant_store, "_ubiquitous_column_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            setattr(qdrant_store, "_ubiquitous_column_cache", cache)
        except Exception:
            pass
    cache_key = (tenant_id, dataset_id, float(threshold))
    if cache_key in cache:
        return cache[cache_key]

    scroll = getattr(qdrant_store, "_scroll_metadata", None)
    if not callable(scroll):
        return None
    try:
        payloads = scroll(None, tenant_id=tenant_id, dataset_id=dataset_id)
    except TypeError:
        try:
            payloads = scroll(None)
        except Exception:
            return None
    except Exception:
        return None
    if not isinstance(payloads, list):
        return None

    table_names: Set[str] = set()
    column_tables: dict[str, Set[str]] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        document_type = payload.get("document_type")
        table_name = payload.get("table_name")
        column_name = payload.get("column_name")
        if document_type in {"table", "table_ddl"} and table_name:
            table_names.add(str(table_name))
        elif document_type in {"column", "column_description"} and table_name and column_name:
            column_tables.setdefault(str(column_name), set()).add(str(table_name))

    total_tables = len(table_names) or len(metadata.tables)
    if total_tables <= 0:
        ubiquitous: Set[str] = set()
    else:
        ubiquitous = {
            column_name
            for column_name, tables in column_tables.items()
            if len(tables) / total_tables > threshold
        }
    cache[cache_key] = ubiquitous
    return ubiquitous


def _compute_ambiguity_flag(
    query: str,
    metadata: SchemaMetadata,
    table_names: List[str],
    scored_tables: Optional[List[Tuple[str, float]]] = None,
    ubiquitous_columns: Optional[Set[str]] = None,
    dominance_ratio: float = DEFAULT_DOMINANCE_RATIO,
    ignored_columns: Sequence[str] = (),
) -> bool:
    """Determine if the query has ambiguous column references across tables.

    A clearly dominant top table never needs clarification. Columns shared by
    most of the schema (ubiquitous, derived from data) and explicitly ignored
    columns are excluded from ambiguity. Query and schema tokens are normalized
    the same way, including generic plural handling.
    """
    unique_tables = list(dict.fromkeys(table_names))
    if len(unique_tables) <= 1:
        return False

    if scored_tables:
        ordered = sorted(scored_tables, key=lambda item: (-float(item[1]), item[0]))
        top_score = float(ordered[0][1])
        second_score = float(ordered[1][1]) if len(ordered) > 1 else 0.0
        if top_score > 0 and (
            second_score == 0 or top_score >= dominance_ratio * second_score
        ):
            return False

    query_tokens = {
        token
        for raw_token in _lexical_tokens(query)
        for token in _normalize_tokens(raw_token)
    }
    ignored_norm = {" ".join(_normalize_tokens(name)) for name in ignored_columns}
    ubiquitous_norm = {
        " ".join(_normalize_tokens(name)) for name in (ubiquitous_columns or ())
    }

    name_to_tables: dict[str, Set[str]] = {}
    for table_name in unique_tables:
        table = metadata.get_table(table_name)
        if table is None:
            continue
        for column in table.columns:
            norm_name = " ".join(_normalize_tokens(column.name))
            if not norm_name:
                continue
            if norm_name in ignored_norm or norm_name in ubiquitous_norm:
                continue
            name_to_tables.setdefault(norm_name, set()).add(table_name)

    ambiguous_cols = {
        name: sorted(tables)
        for name, tables in name_to_tables.items()
        if len(tables) > 1
    }
    if not ambiguous_cols:
        return False

    for tables in ambiguous_cols.values():
        for token in query_tokens:
            matching_tables: List[str] = []
            for table_name in tables:
                table = metadata.get_table(table_name)
                if table is None:
                    continue
                if token in _normalize_tokens(table_name) or any(
                    token in _normalize_tokens(column.name) for column in table.columns
                ):
                    matching_tables.append(table_name)
            if len(matching_tables) == 1:
                return False

    return True


def _has_ambiguous_columns(metadata: SchemaMetadata, table_names: List[str]) -> bool:
    """Check if multiple tables have columns with the same name (e.g., 'id')."""
    name_counts: dict[str, int] = {}
    for table_name in table_names:
        table = metadata.get_table(table_name)
        if table is None:
            continue
        for column in table.columns:
            col_name = column.name
            name_counts[col_name] = name_counts.get(col_name, 0) + 1
    # If any column name appears in more than one table, it's ambiguous
    return any(count > 1 for count in name_counts.values())