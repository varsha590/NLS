"""Tests for retrieval/qdrant_retriever.py — pure-logic schema retriever.

No Qdrant, no FAISS, no embeddings. Tests the roll-up scoring, FK expansion,
table selection, ambiguity flag, and context building logic.
"""

from __future__ import annotations

import pytest
import numpy as np

from retrieval.qdrant_retriever import (
    compute_rollup_score,
    RetrievalResult,
    select_tables,
    expand_fk_neighbors,
    retrieve,
    _compute_ambiguity_flag,
    _split_into_tokens,
)
from schema.metadata import SchemaMetadata, TableInfo, ColumnInfo


def test_compute_rollup_score_s_rel():
    """Roll-up score: S_rel=0.5 -> 0.40 (1.0 * 0.40)."""
    score = compute_rollup_score(s_val=0, s_col=0, s_rel=0.5, s_tbl=0, types_present=0)
    assert abs(score - 0.4) < 1e-10


def test_compute_rollup_score_types_present():
    """types_present=1 adds 0, types_present=2 adds 0.03."""
    assert compute_rollup_score(s_val=0, s_col=0, s_rel=0, s_tbl=0, types_present=0) == 0.0
    assert compute_rollup_score(s_val=0, s_col=0, s_rel=0, s_tbl=0, types_present=1) == 0.0
    assert abs(compute_rollup_score(s_val=0, s_col=0, s_rel=0, s_tbl=0, types_present=2) - 0.03) < 1e-10


def test_select_tables_exact_matches():
    """Exact-value tables are forced into selection first."""
    scored = [("products", 0.9), ("orders", 0.7), ("users", 0.5)]
    # No exact matches
    selected = select_tables(scored, exact_matches=set())
    assert len(selected) == 3
    # With exact match for "users"
    selected = select_tables(scored, exact_matches={"users"})
    assert selected[0] == "users"  # exact match forced to front


def test_select_tables_force_cap():
    """At most max_k tables returned."""
    scored = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6), ("e", 0.5), ("f", 0.4)]
    selected = select_tables(scored, exact_matches=set(), default_k=3, max_k=5)
    assert len(selected) <= 5


def test_expand_fk_neighbors_basic():
    """1-hop FK expansion from selected tables."""
    cols_order = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("customer_id", "INTEGER"),
    ]
    table_order = TableInfo("orders", "", cols_order, ["id"], [
        {"local_cols": ["customer_id"], "remote_table": "customers",
         "remote_cols": ["id"], "constrain_name": "fk_1",
         "local_cols": ["customer_id"], "remote_cols": ["id"]}
    ])

    cols_cust = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("name", "TEXT"),
    ]
    table_cust = TableInfo("customers", "", cols_cust, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "customers": table_cust})
    expanded, truncated = expand_fk_neighbors(metadata, ["orders"], max_tables=8)
    assert "orders" in expanded
    assert "customers" in expanded
    assert truncated == False


def test_expand_fk_neighbors_truncated():
    """truncated=True when tables exceed max_tables."""
    cols_order = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("customer_id", "INTEGER"),
    ]
    table_order = TableInfo("orders", "", cols_order, ["id"], [
        {"local_cols": ["customer_id"], "remote_table": "customers",
         "remote_cols": ["id"], "constrain_name": "fk_1",
         "local_cols": ["customer_id"], "remote_cols": ["id"]}
    ])

    cols_cust = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("name", "TEXT"),
    ]
    table_cust = TableInfo("customers", "", cols_cust, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "customers": table_cust})
    expanded, truncated = expand_fk_neighbors(metadata, ["orders"], max_tables=1)
    # With max=1, only the selected table fits; join-path dropped
    assert "orders" in expanded
    assert truncated == True


def test_expand_fk_neighbors_never_drops_join_path():
    """Join-path tables are never dropped silently."""
    cols_a = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("b_id", "INTEGER"),
    ]
    table_a = TableInfo("a", "", cols_a, ["id"], [
        {"local_cols": ["b_id"], "remote_table": "b", "remote_cols": ["id"],
         "constrain_name": "fk_a_b", "local_cols": ["b_id"], "remote_cols": ["id"]}
    ])

    cols_b = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
    ]
    table_b = TableInfo("b", "", cols_b, ["id"], [])

    metadata = SchemaMetadata({"a": table_a, "b": table_b})
    # Even if this would exceed max, join-path tables are preserved
    expanded, truncated = expand_fk_neighbors(metadata, ["a"], max_tables=1)
    # With max=1, only 'a' fits; truncated indicates join-path couldn't be included
    assert "a" in expanded


def test_expand_fk_neighbors_direct_neighbors_dropped():
    """Direct neighbors may be dropped to cap at max_tables."""
    cols_a = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("b_id", "INTEGER"),
        ColumnInfo("c_id", "INTEGER"),
    ]
    table_a = TableInfo("a", "", cols_a, ["id"], [
        {"local_cols": ["b_id"], "remote_table": "b", "remote_cols": ["id"],
         "constrain_name": "fk_a_b", "local_cols": ["b_id"], "remote_cols": ["id"]},
        {"local_cols": ["c_id"], "remote_table": "c", "remote_cols": ["id"],
         "constrain_name": "fk_a_c", "local_cols": ["c_id"], "remote_cols": ["id"]},
    ])

    cols_b = [ColumnInfo("id", "INTEGER", is_primary_key=True)]
    table_b = TableInfo("b", "", cols_b, ["id"], [])

    cols_c = [ColumnInfo("id", "INTEGER", is_primary_key=True)]
    table_c = TableInfo("c", "", cols_c, ["id"], [])

    metadata = SchemaMetadata({"a": table_a, "b": table_b, "c": table_c})
    expanded, truncated = expand_fk_neighbors(metadata, ["a"], max_tables=2)
    # 'a' + one of 'b' or 'c' should fit at max=2
    assert "a" in expanded
    assert truncated == True  # capped at max


def test_ambiguity_flag_show_id():
    """"show id" across multiple tables -> ambiguity_flag=True."""
    cols_order = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("order_id", "INTEGER")]
    table_order = TableInfo("orders", "", cols_order, ["id"], [])

    cols_users = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("user_name", "TEXT")]
    table_users = TableInfo("users", "", cols_users, ["id"], [])

    cols_products = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("product_name", "TEXT")]
    table_products = TableInfo("products", "", cols_products, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "users": table_users, "products": table_products})
    result = retrieve(metadata, "show id")
    assert result.ambiguity_flag == True


def test_ambiguity_flag_show_order_id():
    """"show order id" disambiguates toward orders table."""
    cols_order = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("order_id", "INTEGER")]
    table_order = TableInfo("orders", "", cols_order, ["id"], [])

    cols_users = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("user_name", "TEXT")]
    table_users = TableInfo("users", "", cols_users, ["id"], [])

    cols_products = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("product_name", "TEXT")]
    table_products = TableInfo("products", "", cols_products, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "users": table_users, "products": table_products})
    result = retrieve(metadata, "show order id")
    assert result.ambiguity_flag == False, (
        "'show order id' must not set ambiguity_flag; 'order' token disambiguates"
    )


def test_ambiguity_flag_show_product_id():
    """"show product id" disambiguates toward products table."""
    cols_order = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("order_id", "INTEGER")]
    table_order = TableInfo("orders", "", cols_order, ["id"], [])

    cols_users = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("user_name", "TEXT")]
    table_users = TableInfo("users", "", cols_users, ["id"], [])

    cols_products = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("product_name", "TEXT")]
    table_products = TableInfo("products", "", cols_products, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "users": table_users, "products": table_products})
    result = retrieve(metadata, "show product id")
    assert result.ambiguity_flag == False, (
        "'show product id' must not set ambiguity_flag; 'product' token disambiguates"
    )


def test_context_no_description_or_comment():
    """Schema context omits table.description and column.comment."""
    from retrieval.qdrant_retriever import build_table_context

    cols = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("order_id", "INTEGER"),
        ColumnInfo("created_at", "TIMESTAMP"),  # SKIP column - stays visible
        ColumnInfo("password", "TEXT"),        # BLOCKED - filtered out
    ]
    table = TableInfo("orders", "An orders table", cols, ["id"], [])
    metadata = SchemaMetadata({"orders": table})

    ctx = build_table_context(metadata, "orders", sensitive_filter=None)
    col_names = [c["name"] for c in ctx["columns"]]
    # description and comment should be omitted
    assert "description" not in str(ctx)
    assert "comment" not in str(ctx)
    # created_at (SKIP) should be visible (name+type only)
    assert "created_at" in col_names
    # password (BLOCKED) should be filtered
    assert "password" not in col_names


def test_context_skip_column_visible():
    """SKIP columns (created_at) are visible in context, name+type only."""
    from retrieval.qdrant_retriever import build_table_context

    cols = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("created_at", "TIMESTAMP"),  # SKIP - stays visible
    ]
    table = TableInfo("orders", "", cols, ["id"], [])
    metadata = SchemaMetadata({"orders": table})

    ctx = build_table_context(metadata, "orders", sensitive_filter=None)
    col_names = [c["name"] for c in ctx["columns"]]
    assert "created_at" in col_names
    # Only name and type, no comment
    created_col = [c for c in ctx["columns"] if c["name"] == "created_at"][0]
    assert "comment" not in str(created_col)


def test_split_into_tokens():
    """Snake_case splitting works correctly."""
    assert _split_into_tokens("order_id") == ["order", "id"]
    assert _split_into_tokens("created_at") == ["created", "at"]
    assert _split_into_tokens("id") == ["id"]
    assert _split_into_tokens("OrderId") == ["order", "id"]


def test_compute_rollup_score_column_beats_weak_value():
    """Column+relationship beating a lone weak value hit."""
    # A table with s_col=1.0 + s_rel=0.8 = 1.8 beats a table with s_val=0.5 only
    # (0.6 * 0.5 = 0.3 for the weak value table)
    score1 = compute_rollup_score(s_val=0.5, s_col=0, s_rel=0, s_tbl=0)
    score2 = compute_rollup_score(s_val=0, s_col=1.0, s_rel=0.8, s_tbl=0)
    assert score2 > score1


def test_select_tables_forced_low_vector():
    """Forced table with low vector score still selected first."""
    scored = [("products", 0.2), ("orders", 0.5)]
    # Exact match for products forces it to front even with lower score
    selected = select_tables(scored, exact_matches={"products"})
    assert selected[0] == "products"


def test_select_tables_fuzzy_never_forcing():
    """Fuzzy (non-exact) matches never force table selection."""
    scored = [("a", 0.9), ("b", 0.8)]
    # No exact matches, but fuzzy should not force — just score-sort
    selected = select_tables(scored, exact_matches=set())
    assert len(selected) == 2


def test_expand_fk_neighbors_fk_cap_gives_truncated():
    """FK cap causes truncated=True when total tables exceed max."""
    cols_a = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("b_id", "INTEGER"),
        ColumnInfo("c_id", "INTEGER"),
    ]
    table_a = TableInfo("a", "", cols_a, ["id"], [
        {"local_cols": ["b_id"], "remote_table": "b", "remote_cols": ["id"],
         "constrain_name": "fk_a_b", "local_cols": ["b_id"], "remote_cols": ["id"]},
        {"local_cols": ["c_id"], "remote_table": "c", "remote_cols": ["id"],
         "constrain_name": "fk_a_c", "local_cols": ["c_id"], "remote_cols": ["id"]},
    ])

    cols_b = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
    ]
    table_b = TableInfo("b", "", cols_b, ["id"], [])

    cols_c = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
    ]
    table_c = TableInfo("c", "", cols_c, ["id"], [])

    metadata = SchemaMetadata({"a": table_a, "b": table_b, "c": table_c})
    # selected=["a"] has FKs to both b and c (1-hop each), max_tables=2
    # "a" + first join-path alphabetically fits, second can't fit → truncated=True
    expanded, truncated = expand_fk_neighbors(metadata, ["a"], max_tables=2)
    assert "a" in expanded
    assert truncated == True  # can't fit both b and c within max=2


def test_expand_fk_neighbors_selected_at_cap():
    """Selected tables at cap, no room for join-path or direct neighbors."""
    cols_a = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
    ]
    table_a = TableInfo("a", "", cols_a, ["id"], [])

    metadata = SchemaMetadata({"a": table_a})
    expanded, truncated = expand_fk_neighbors(metadata, ["a"], max_tables=1)
    assert len(expanded) == 1
    assert expanded[0] == "a"
    assert truncated == False


def test_build_table_context_api_key_hit_dropped():
    """Injected api_key column hit is dropped by sensitive filter."""
    from retrieval.qdrant_retriever import build_table_context

    cols = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("api_key", "TEXT"),        # BLOCKED per SENSITIVE_COLUMN_PATTERNS
        ColumnInfo("name", "TEXT"),
    ]
    table = TableInfo("users", "", cols, ["id"], [])
    metadata = SchemaMetadata({"users": table})

    # api_key matches SENSITIVE_COLUMN_PATTERNS ("api_key"), so is_blocked returns True
    ctx = build_table_context(metadata, "users", sensitive_filter={})
    col_names = [c["name"] for c in ctx["columns"]]
    assert "api_key" not in col_names, "api_key should be blocked by sensitive filter"
    assert "name" in col_names

    # Test with explicit policy_overrides
    ctx2 = build_table_context(
        metadata, "users", sensitive_filter={"api_key": "BLOCKED"}
    )
    col_names2 = [c["name"] for c in ctx2["columns"]]
    assert "api_key" not in col_names2


def test_ambiguity_flag_show_id():
    """"show id" across multiple tables -> ambiguity_flag=True."""
    cols_order = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("order_id", "INTEGER")]
    table_order = TableInfo("orders", "", cols_order, ["id"], [])

    cols_users = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("user_name", "TEXT")]
    table_users = TableInfo("users", "", cols_users, ["id"], [])

    cols_products = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("product_name", "TEXT")]
    table_products = TableInfo("products", "", cols_products, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "users": table_users, "products": table_products})
    result = retrieve(metadata, "show id")
    assert result.ambiguity_flag == True


def test_ambiguity_flag_show_order_id():
    """"show order id" disambiguates toward orders table."""
    cols_order = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("order_id", "INTEGER")]
    table_order = TableInfo("orders", "", cols_order, ["id"], [])

    cols_users = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("user_name", "TEXT")]
    table_users = TableInfo("users", "", cols_users, ["id"], [])

    cols_products = [ColumnInfo("id", "INTEGER", is_primary_key=True), ColumnInfo("product_name", "TEXT")]
    table_products = TableInfo("products", "", cols_products, ["id"], [])

    metadata = SchemaMetadata({"orders": table_order, "users": table_users, "products": table_products})
    result = retrieve(metadata, "show order id")
    assert result.ambiguity_flag == False, (
        "'show order id' must not set ambiguity_flag; 'order' token disambiguates"
    )


def test_context_no_description_or_comment():
    """Schema context omits table.description and column.comment."""
    from retrieval.qdrant_retriever import build_table_context

    cols = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("order_id", "INTEGER"),
        ColumnInfo("created_at", "TIMESTAMP"),  # SKIP column - stays visible
        ColumnInfo("password", "TEXT"),        # BLOCKED - filtered out
    ]
    table = TableInfo("orders", "An orders table", cols, ["id"], [])
    metadata = SchemaMetadata({"orders": table})

    ctx = build_table_context(metadata, "orders", sensitive_filter=None)
    col_names = [c["name"] for c in ctx["columns"]]
    # description and comment should be omitted
    assert "description" not in str(ctx)
    assert "comment" not in str(ctx)
    # created_at (SKIP) should be visible (name+type only)
    assert "created_at" in col_names
    # password (BLOCKED) should be filtered
    assert "password" not in col_names


def test_context_skip_column_visible():
    """SKIP columns (created_at) are visible in context, name+type only."""
    from retrieval.qdrant_retriever import build_table_context

    cols = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("created_at", "TIMESTAMP"),  # SKIP - stays visible
    ]
    table = TableInfo("orders", "", cols, ["id"], [])

    metadata = SchemaMetadata({"orders": table})

    ctx = build_table_context(metadata, "orders", sensitive_filter=None)
    col_names = [c["name"] for c in ctx["columns"]]
    assert "created_at" in col_names
    # Only name and type, no comment
    created_col = [c for c in ctx["columns"] if c["name"] == "created_at"][0]
    assert "comment" not in str(created_col)


def test_expand_fk_neighbors_shortest_path_ordering():
    """1-hop path tables come before 2-hop path tables (shortest path first)."""
    cols_a = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("b_id", "INTEGER"),
    ]
    table_a = TableInfo("a", "", cols_a, ["id"], [
        {"local_cols": ["b_id"], "remote_table": "b", "remote_cols": ["id"],
         "constrain_name": "fk_a_b", "local_cols": ["b_id"], "remote_cols": ["id"]}
    ])

    cols_b = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
        ColumnInfo("c_id", "INTEGER"),
    ]
    table_b = TableInfo("b", "", cols_b, ["id"], [
        {"local_cols": ["c_id"], "remote_table": "c", "remote_cols": ["id"],
         "constrain_name": "fk_b_c", "local_cols": ["c_id"], "remote_cols": ["id"]}
    ])

    cols_c = [
        ColumnInfo("id", "INTEGER", is_primary_key=True),
    ]
    table_c = TableInfo("c", "", cols_c, ["id"], [])

    metadata = SchemaMetadata({"a": table_a, "b": table_b, "c": table_c})
    # a→b→c: b is 1-hop from a, c is 2-hop from a (but we only do 1-hop)
    # With the spec "no 2-hop traversal", c should NOT appear as a join-path table
    # from a. Only b (1-hop) should appear.
    expanded, truncated = expand_fk_neighbors(metadata, ["a"], max_tables=3)
    assert "a" in expanded
    assert "b" in expanded  # 1-hop from a
    # c should NOT appear as a join-path table from a (1-hop only)
    # since we don't traverse 2-hop


if __name__ == "__main__":
    pytest.main([__file__, "-v"])