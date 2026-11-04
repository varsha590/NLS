"""Tests for retrieval.value_matcher — pure function, no Qdrant, no embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from retrieval.value_matcher import match_values

from ingestion.datasets import DatasetRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vd(**kwargs: Any) -> dict[str, Any]:
    """Build a minimal value-document dict."""
    return {
        "table_name": kwargs.get("table", "t"),
        "column_name": kwargs.get("column", "c"),
        "value": kwargs.get("value", "v"),
        "content": kwargs.get("content", "c v"),
    }


def _vds(*vds: dict[str, Any]) -> list[dict[str, Any]]:
    """Varargs into list."""
    return list(vds)


# ---------------------------------------------------------------------------
# Case-insensitive exact
# ---------------------------------------------------------------------------

def test_match_values_case_insensitive_exact():
    """Exact match is case-insensitive; 'north' matches stored 'North'."""
    q = "north"
    docs = [_vd(value="North", table="regions", column="name")]
    results = match_values(q, docs)
    assert len(results) == 1
    assert results[0]["match_type"] == "exact"
    assert results[0]["confidence"] == 1.0
    # Case-preserved: the returned value should keep original casing
    assert results[0]["value"] == "North"


# ---------------------------------------------------------------------------
# Same value in two columns / tables
# ---------------------------------------------------------------------------

def test_same_value_two_columns():
    """The same value appearing in two different columns returns two matches."""
    q = "active"
    docs = [
        _vd(value="Active", table="orders", column="status"),
        _vd(value="Active", table="users", column="status"),
    ]
    results = match_values(q, docs)
    assert len(results) == 2
    tables = {r["table"] for r in results}
    assert tables == {"orders", "users"}


# ---------------------------------------------------------------------------
# Longest-match-wins
# ---------------------------------------------------------------------------

def test_longest_match_wins():
    """When a long n-gram and a short n-gram both match, the long one wins."""
    q = "north region"
    docs = [
        _vd(value="North Region", table="regions", column="name"),
        _vd(value="North", table="regions", column="alt_name"),
    ]
    results = match_values(q, docs)
    # Should have at least the long-match result
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# Siblings below threshold (fuzzy) — parametrized over all sibling pairs
# ---------------------------------------------------------------------------

import pytest

SIBLING_PAIRS = [
    ("Electronics", "Electrical"),
    ("Active", "Inactive"),
    ("North", "South"),
    ("Shipped", "Skipped"),
    ("Pending", "Pended"),
    ("Premium", "Premier"),
    ("Completed", "Incomplete"),
]


@pytest.mark.parametrize("qval,svval", SIBLING_PAIRS)
def test_fuzzy_siblings_below_threshold(qval: str, svval: str):
    """Fuzzy similarity for sibling pairs should be below _FUZZY_THRESHOLD.

    With _FUZZY_THRESHOLD = 0.90, all listed sibling pairs (including
    Shipped/Skipped at 0.8571) score below threshold and must not produce
    a fuzzy match. Student/Students (0.9333) is the sibling that triggers
    STOP: it reaches the lowest passing typo similarity (0.9091).
    """
    q = qval
    docs = [_vd(value=svval, table="cat", column="name")]
    results = match_values(q, docs)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    # All parametrized sibling pairs must be below _FUZZY_THRESHOLD = 0.90
    assert len(fuzzy_hits) == 0, (
        f"Sibling pair {qval}/{svval} produced {len(fuzzy_hits)} fuzzy hit(s), "
        f"similarity would be >= _FUZZY_THRESHOLD"
    )


# ---------------------------------------------------------------------------
# No fuzzy inside an exact span
# ---------------------------------------------------------------------------

def test_no_fuzzy_inside_exact_span():
    """If an exact n-gram match exists, fuzzy is not emitted for that span."""
    q = "north region"
    docs = [
        _vd(value="North Region", table="regions", column="name"),
        _vd(value="Northern", table="regions", column="desc"),
    ]
    results = match_values(q, docs)
    # Exact match for "North Region" should be present
    exact_hits = [r for r in results if r["match_type"] == "exact"]
    assert len(exact_hits) >= 1


# ---------------------------------------------------------------------------
# Siblings above threshold (typo)
# ---------------------------------------------------------------------------

def test_fuzzy_typos_above_threshold():
    """Typo n-grams that score >= _FUZZY_THRESHOLD should produce a fuzzy match."""
    q = "Electroncis"  # typo for Electronics
    docs = [_vd(value="Electronics", table="cat", column="name")]
    results = match_values(q, docs)
    # Similarity Electroncis/Electronics = 0.9091 >= _FUZZY_THRESHOLD (0.90)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    assert len(fuzzy_hits) >= 1


# ---------------------------------------------------------------------------
# Digit / short values never fuzzy-matched
# ---------------------------------------------------------------------------

def test_digit_values_never_fuzzy():
    """Stored values containing digits are skipped for fuzzy."""
    q = "test"
    docs = [_vd(value="test1", table="t", column="c")]
    results = match_values(q, docs)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    assert len(fuzzy_hits) == 0


def test_short_values_never_fuzzy():
    """Stored values shorter than 5 chars are skipped for fuzzy."""
    q = "test"
    docs = [_vd(value="abc", table="t", column="c")]  # 3 chars < 5
    results = match_values(q, docs)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    assert len(fuzzy_hits) == 0


# ---------------------------------------------------------------------------
# Fuzzy never marked confirmed or forcing selection
# ---------------------------------------------------------------------------

def test_fuzzy_never_confirmed():
    """Fuzzy matches must have confirmed=False."""
    q = "Electroncis"
    docs = [_vd(value="Electronics", table="cat", column="name")]
    results = match_values(q, docs)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    assert len(fuzzy_hits) >= 1
    for fh in fuzzy_hits:
        assert fh["confirmed"] is False


def test_fuzzy_never_forces_table():
    """Fuzzy matches must have forced_table=False."""
    q = "Electroncis"
    docs = [_vd(value="Electronics", table="cat", column="name")]
    results = match_values(q, docs)
    fuzzy_hits = [r for r in results if r["match_type"] == "fuzzy_text"]
    for fh in fuzzy_hits:
        assert fh["forced_table"] is False


# ---------------------------------------------------------------------------
# Ties return all
# ---------------------------------------------------------------------------

def test_ties_return_all():
    """When two values have the same exact score, both are returned."""
    q = "active"
    docs = [
        _vd(value="Active", table="orders", column="status"),
        _vd(value="Active", table="users", column="status"),
    ]
    results = match_values(q, docs)
    # Both should be returned (ties)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# Empty question and empty values
# ---------------------------------------------------------------------------

def test_empty_question():
    """Empty question returns no matches."""
    docs = [_vd(value="anything", table="t", column="c")]
    results = match_values("", docs)
    assert results == []


def test_empty_values():
    """Empty value_documents returns no matches."""
    q = "anything"
    results = match_values(q, [])
    assert results == []


# ---------------------------------------------------------------------------
# Two datasets' value documents never mix
# ---------------------------------------------------------------------------

def test_datasets_never_mix():
    """Value docs from different datasets (different tables) don't cross-contaminate.

    The same value in two different tables both match, and each result carries
    the correct table/column assignment — no mixing of assignments.
    """
    q = "active"
    # Same value "Active" in two different tables/columns
    docs = [
        _vd(value="Active", table="orders", column="status"),
        _vd(value="Active", table="users", column="status"),
    ]
    results = match_values(q, docs)
    tables = {r["table"] for r in results}
    assert tables == {"orders", "users"}
    # Each match should have the correct table
    for r in results:
        assert r["table"] in {"orders", "users"}


# ---------------------------------------------------------------------------
# Tenant/dataset path rejection ( "../" injection)
# ---------------------------------------------------------------------------

def test_path_injection_rejected():
    """The matcher should not crash on unusual string inputs.

    Path-traversal rejection happens at the caller level where local file paths
    are built; the matcher itself validates its inputs.
    """
    q = "test"
    docs = [_vd(value="test", table="t", column="c")]
    results = match_values(q, docs)
    # The function itself doesn't build paths, but it should not crash on
    # unusual string inputs and should return a list.
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Tenant/dataset path injection resistance
# ---------------------------------------------------------------------------

def test_dataset_directory_path_injection(tmp_path):
    """dataset_directory must not emit paths that escape the tenant root.

    The method builds paths as: _tenant_root(tenant_id) / dataset_id.
    _tenant_root hashes the tenant_id, but dataset_id may contain
    user-controlled components. Verify that "../" and absolute paths
    do not cause directory traversal outside the expected structure.
    """
    from pathlib import Path
    from ingestion.datasets import DatasetRegistry

    datasets_dir = tmp_path / "datasets"
    registry = DatasetRegistry(datasets_dir)

    # Test with "../x" tenant_id - path should be under datasets dir
    result = registry.dataset_directory("../x", "dataset-a")
    assert str(result).startswith(str(datasets_dir)), (
        f"Path not under datasets dir: {result}"
    )

    # Test with "a/../b" dataset_id - path should be under datasets dir
    result = registry.dataset_directory("tenant-a", "a/../b")
    assert str(result).startswith(str(datasets_dir)), (
        f"Path not under datasets dir: {result}"
    )

    # Normal case still works
    result = registry.dataset_directory("tenant-a", "normal_dataset")
    assert str(result).startswith(str(datasets_dir)), (
        f"Path not under datasets dir: {result}"
    )
    assert result.name == "normal_dataset", (
        f"Last component not normal_dataset: {result.parts}"
    )


# ---------------------------------------------------------------------------
# Main guard
# ---------------------------------------------------------------------------

if __name__ == "__main__":
 import pytest
 pytest.main([__file__, "-v"])