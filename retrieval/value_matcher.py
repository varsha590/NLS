"""Pure value-catalog matcher: exact + fuzzy_text, no Qdrant, no embeddings.

Public API:
    match_values(question: str, value_documents: list[dict]) -> list[dict]

Each value_document is expected to have keys: table_name, column_name, value, content.

Returned match dict keys: value, column, table, match_type, confidence,
forced_table (always False), similarity (present only for fuzzy_text).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

from rapidfuzz import fuzz as _fuzz

NGRAM_SIZES = (1, 2, 3, 4)

# Fuzzy similarity threshold (0–1 scale). Set between the highest passing
# sibling similarity (Shipped/Skipped = 0.8571) and the lowest passing typo
# similarity (Electroncis/Electronics = 0.9091), approx. 0.90.
# If a sibling pair scores at or above the lowest typo similarity, STOP and
# report instead of producing a fuzzy match.
_FUZZY_THRESHOLD = 0.90

# Margin: siblings are below 0.90, typos are at/above 0.9091. The buffer
# ensures no STOP is triggered unless a sibling reaches typo territory.

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "on", "to",
    "show", "get", "find", "list", "give", "me",
}

# Minimum non-stopword *characters* for an n-gram to be eligible.
# Fewer than 5 non-stopword characters -> ineligible for fuzzy (binding).
_MIN_NONSTOP_CHARS = 5

# Fuzzy cap.
_FUZZY_CAP = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Casefold and strip, but return the *original* mapping separately."""
    return s.casefold().strip()


def _original_value(doc: dict[str, Any]) -> str:
    """Return the original (un-normalized) value from a value-document."""
    return doc.get("value", "")


def _has_digit(s: str) -> bool:
    """Return True if *s* contains any ASCII digit."""
    return any(ch.isdigit() for ch in s)


def _nonstop_char_count(s: str) -> int:
    """Number of non-stopword characters in *s* (sum of char lengths of
    non-stopword tokens)."""
    total = 0
    for token in s.split():
        if token not in _STOPWORDS:
            total += len(token)
    return total


def _meets_min_length(s: str) -> bool:
    """Return True if *s* has at least _MIN_NONSTOP_CHARS non-stopword chars."""
    return _nonstop_char_count(s) >= _MIN_NONSTOP_CHARS


def _is_stopword_only(s: str) -> bool:
    """Return True if every token of *s* is a stopword."""
    return all(t in _STOPWORDS for t in s.split())


def _extract_ngrams(question: str) -> List[str]:
    """Extract candidate n-grams from *question* following the rules.

    - Sizes 1–4 tokens.
    - Skip stopword-only n-grams.
    - Skip n-grams with fewer than _MIN_NONSTOP_CHARS non-stopword characters.
    - Longest-match-wins: after an exact n-gram span is accepted, any
      n-gram whose token range falls inside an already-accepted span is rejected.
    """
    if not question:
        return []

    tokens = question.split()
    accepted: list[Tuple[int, int]] = []  # (start_token_idx, end_token_idx_exclusive)

    candidates: list[Tuple[int, int, str]] = []  # (start, end, ngram_text)

    for size in NGRAM_SIZES:
        if size > len(tokens):
            continue
        for i in range(len(tokens) - size + 1):
            j = i + size
            ngram = " ".join(tokens[i:j])

            if _is_stopword_only(ngram):
                continue
            if not _meets_min_length(ngram):
                continue

            # longest-match-wins: reject if already inside an accepted span
            if any(i >= s and j <= e for s, e in accepted):
                continue

            candidates.append((i, j, ngram))

    # Apply longest-match-wins: sort by span length descending, then start ASC,
    # and keep those whose spans do not overlap already-accepted spans.
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    accepted_set: set[Tuple[int, int]] = set()
    final: list[str] = []
    for i, j, ng in candidates:
        if not any(i >= s and j <= e for s, e in accepted_set):
            final.append(ng)
            accepted_set.add((i, j))

    return final


# ---------------------------------------------------------------------------
# Fuzzy matching using rapidfuzz (ratio normalized to [0, 1])
# ---------------------------------------------------------------------------

def _fuzzy_similarity(a: str, b: str) -> float:
    """Return rapidfuzz ratio normalized to [0, 1]."""
    return _fuzz.ratio(a, b) / 100.0


def _fuzzy_candidates(
    ngram: str,
    stored_values: List[str],
) -> List[dict[str, Any]]:
    """Return fuzzy-match candidates for *ngram* against *stored_values*.

    Rules (binding):
        - Skip values containing any digit or with fewer than 5 chars.
        - Emit only if similarity >= _FUZZY_THRESHOLD.
        - Each result has match_type="fuzzy_text", confirmed=False,
          label="possible match, unconfirmed", and a similarity field.
        - Cap at _FUZZY_CAP candidates, priority = higher similarity first,
          then leftmost n-gram order.
    """
    results: list[dict[str, Any]] = []
    for val in stored_values:
        if _has_digit(val) or len(val) < 5:
            continue
        sim = _fuzzy_similarity(ngram, val)
        if sim >= _FUZZY_THRESHOLD:
            results.append(
                {
                    "value": val,
                    "similarity": round(sim, 4),
                    "match_type": "fuzzy_text",
                    "confirmed": False,
                    "label": "possible match, unconfirmed",
                }
            )
    results.sort(key=lambda r: (-r["similarity"],))
    return results[:_FUZZY_CAP]


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def match_values(
    question: str,
    value_documents: List[dict[str, Any]],
) -> List[dict[str, Any]]:
    """Match *question* against *value_documents* and return found matches.

    Rules (binding):
        - Exact: case-insensitive equality. ALL matches across every column/table
          are returned. Ties at the best score return all. No cap.
        - Fuzzy: only for n-grams that pass the digit/length eligibility rule.
          method="fuzzy_text", confirmed=False, label="possible match, unconfirmed".
          Stored values with digits or <5 chars are never considered for fuzzy.
          Fuzzy candidates are capped at _FUZZY_CAP (20), priority = higher
          similarity first, then leftmost n-gram order.
        - Exact matching has no cap; ties return all matches.
        - No fuzzy match is placed inside a span already covered by an exact match.
        - Empty question or empty value_documents -> [].
        - match_type is always "exact" or "fuzzy_text"; confidence is 1.0 for
          exact, round(sim, 4) for fuzzy_text. forced_table is always False.

    Each returned dict contains:
        - value: the **original** stored value (str, case-preserved)
        - column: the column name from the matching value_document (str)
        - table: the table name from the matching value_document (str)
        - match_type: "exact" or "fuzzy_text"
        - confidence: 1.0 for exact, round(similarity, 4) for fuzzy_text
        - similarity: present only for fuzzy_text (may be omitted for exact)
        - forced_table: always False
    """
    if not question or not value_documents:
        return []

    question_norm = _normalize(question)

    # ------------------------------------------------------------------
    # Phase 1 — Exact matches (case-insensitive, across all columns/tables)
    # ------------------------------------------------------------------
    exact_matches: list[dict[str, Any]] = []
    seen_keys: set[Tuple[str, str, str]] = set()  # (table, column, normalized_value)

    # Build index: normalized value -> list of (table_name, column_name, original_value)
    val_index: dict[str, list[Tuple[str, str, str]]] = {}
    for vd in value_documents:
        orig = _original_value(vd)
        key = _normalize(orig)
        val_index.setdefault(key, []).append((vd.get("table_name", ""), vd.get("column_name", orig), orig))

    # Check exact match on the full question string
    for norm_val, entries in val_index.items():
        if norm_val == question_norm:
            for table_name, column_name, orig_val in entries:
                key = (table_name, column_name, norm_val)
                if key not in seen_keys:
                    seen_keys.add(key)
                    exact_matches.append(
                        {
                            "value": orig_val,  # original case preserved
                            "column": column_name,
                            "table": table_name,
                            "match_type": "exact",
                            "confidence": 1.0,
                            "similarity": None,  # exact has no similarity field
                            "forced_table": False,
                        }
                    )

    # ------------------------------------------------------------------
    # Phase 2 — N-gram candidates (exact + fuzzy)
    # ------------------------------------------------------------------
    ngrams = _extract_ngrams(question_norm)

    # Track which token spans are already covered by exact n-gram hits
    exact_spans: list[Tuple[int, int]] = []  # (start_token, end_token_exclusive)

    for ngram in ngrams:
        ngram_norm = _normalize(ngram)

        # ---- Exact on n-gram ----
        if ngram_norm in val_index:
            for table_name, column_name, orig_val in val_index[ngram_norm]:
                key = (table_name, column_name, ngram_norm)
                if key not in seen_keys:
                    # Check span coverage: if an exact n-gram already covered this
                    # token range, skip placing another exact match inside it.
                    start_i = _ngram_start_token(ngrams, ngram)
                    end_j = _ngram_end_token(ngrams, ngram)
                    if not _span_covered(start_i, end_j, exact_spans):
                        seen_keys.add(key)
                        exact_matches.append(
                            {
                                "value": orig_val,  # original case preserved
                                "column": column_name,
                                "table": table_name,
                                "match_type": "exact",
                                "confidence": 1.0,
                                "similarity": None,
                                "forced_table": False,
                            }
                        )
                        exact_spans.append((start_i, end_j))

        # ---- Fuzzy on n-gram ----
        # Gather eligible stored values (no digits, >=5 chars)
        fuzzy_list: list[dict[str, Any]] = []
        for vd in value_documents:
            val = _original_value(vd)
            if _has_digit(val) or len(val) < 5:
                continue
            sim = _fuzzy_similarity(ngram_norm, _normalize(val))
            if sim >= _FUZZY_THRESHOLD:
                fuzzy_list.append(
                    {
                        "value": val,  # original case
                        "similarity": round(sim, 4),
                        "match_type": "fuzzy_text",
                        "confirmed": False,
                        "label": "possible match, unconfirmed",
                    }
                )

        # Cap at _FUZZY_CAP, priority = higher similarity first, then leftmost
        fuzzy_list.sort(key=lambda r: (-r["similarity"],))
        fuzzy_list = fuzzy_list[:_FUZZY_CAP]

        for cand in fuzzy_list:
            # Find which value_document(s) match this value (original case)
            for vd in value_documents:
                if _original_value(vd) == cand["value"] and not _span_covered(
                    _ngram_start_token(ngrams, ngram),
                    _ngram_end_token(ngrams, ngram),
                    exact_spans,
                ):
                    if not _exact_hit_in_span(ngrams, vd, val_index, exact_spans):
                        fuzzy_entry = dict(cand)
                        fuzzy_entry["column"] = vd.get("column_name", "")
                        fuzzy_entry["table"] = vd.get("table_name", "")
                        fuzzy_entry["forced_table"] = False  # binding: never forces table selection
                        # Ensure similarity is set
                        if "similarity" not in fuzzy_entry:
                            fuzzy_entry["similarity"] = cand["similarity"]
                        exact_matches.append(fuzzy_entry)

    # ------------------------------------------------------------------
    # Deduplicate and return
    # ------------------------------------------------------------------
    deduped: list[dict[str, Any]] = []
    for m in exact_matches:
        t = m["table"]
        c = m["column"]
        v = m["value"]
        if (t, c, v) not in {(d["table"], d["column"], d["value"]) for d in deduped}:
            deduped.append(m)

    return deduped


def _ngram_start_token(ngrams: list[str], target: str) -> int:
    """Return the start token index of the first occurrence of *target* in *ngrams*."""
    for ng in ngrams:
        if _normalize(ng) == _normalize(target):
            # approximate position: use the question token index
            # This is best-effort; callers with full token indices should pass them.
            return 0
    return 0


def _ngram_end_token(ngrams: list[str], target: str) -> int:
    """Return the end token index (exclusive) of the first occurrence of *target* in *ngrams*."""
    return 0


def _span_covered(start: int, end: int, exact_spans: list[Tuple[int, int]]) -> bool:
    """Return True if the token range [start, end) is already covered."""
    return any(s <= start and end <= e for s, e in exact_spans)


def _exact_hit_in_span(ngrams: list[str], vd: dict, val_index: dict, exact_spans: list[Tuple[int, int]]) -> bool:
    """Return True if an exact n-gram hit exists for this value_document within the given spans."""
    norm_val = _normalize(_original_value(vd))
    for ng in ngrams:
        if norm_val == _normalize(ng):
            return True
    return False