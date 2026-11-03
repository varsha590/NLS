"""Tests for table-name-independent catalog value matching."""

from retrieval.value_resolver import (
    extract_ngrams,
    find_all_matches_in_question,
    resolve_values,
)


def test_extract_ngrams_handles_arbitrary_text():
    assert extract_ngrams("north region sales", 2) == ["north region", "region sales"]


def test_catalog_match_uses_exact_stored_value_case_insensitively():
    hints, no_matches = resolve_values(
        "show NORTH REGION", {"locations.region_name": ["North Region", "South Region"]}
    )

    assert no_matches == []
    assert len(hints) == 1
    assert hints[0].column == "locations.region_name"
    assert hints[0].value == "North Region"
    assert hints[0].match_type == "exact"


def test_fuzzy_match_resolves_against_arbitrary_catalog_column():
    matches = find_all_matches_in_question("find north regoin", ["North Region", "South Region"])

    assert matches
    assert matches[0][0] == "north region"
    assert matches[0][2] == "fuzzy"


def test_allowed_table_filter_uses_catalog_key_only():
    hints, _ = resolve_values(
        "North Region",
        {"locations.region_name": ["North Region"]},
        allowed_tables=["other_table"],
    )

    assert hints == []
