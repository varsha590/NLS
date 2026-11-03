"""Generic value-catalog matching helpers retained for compatibility."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from rapidfuzz import fuzz, process

FUZZY_THRESHOLD = 75
NGRAM_SIZES = (1, 2, 3, 4)


@dataclass
class ValueHint:
    """A resolved value hint for a user mention."""

    mention: str
    column: str
    value: str
    match_type: str


@dataclass
class NoMatchResult:
    """Closest catalog values for an unresolved mention."""

    mention: str
    column: str
    closest_values: list[str]


def extract_ngrams(text: str, n: int) -> list[str]:
    """Extract word n-grams from text."""
    words = text.casefold().split()
    if len(words) < n:
        return [" ".join(words)]
    return [" ".join(words[index:index + n]) for index in range(len(words) - n + 1)]


def detect_referenced_columns(question: str, catalog: dict[str, list[str]] | None = None) -> list[str]:
    """Detect columns whose stored values appear in the question."""
    if catalog is None:
        return []
    normalized = question.casefold()
    return [
        column
        for column, values in catalog.items()
        if any(re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", normalized) for value in values)
    ]


def find_all_matches_in_question(question: str, values: list[str]) -> list[tuple[str, str, str]]:
    """Return exact and high-confidence fuzzy matches from a generic value list."""
    normalized = question.casefold()
    matches: list[tuple[str, str, str]] = []
    occupied: list[tuple[int, int]] = []
    for value in sorted(values, key=len, reverse=True):
        start = 0
        while True:
            index = normalized.find(value.casefold(), start)
            if index < 0:
                break
            end = index + len(value)
            if not any(index < right and end > left for left, right in occupied):
                matches.append((value.casefold(), value, "exact"))
                occupied.append((index, end))
            start = index + 1
    if matches:
        return matches
    tokens = list(re.finditer(r"[\w&'-]+", question, flags=re.UNICODE))
    for size in NGRAM_SIZES:
        for start in range(max(0, len(tokens) - size + 1)):
            end_index = min(start + size, len(tokens))
            phrase = question[tokens[start].start():tokens[end_index - 1].end()]
            best = process.extractOne(phrase, values, scorer=fuzz.WRatio)
            if best and best[1] >= FUZZY_THRESHOLD:
                matches.append((str(best[0]).casefold(), phrase, "fuzzy"))
    return matches


def find_mentions_in_question(
    question: str, catalog: dict[str, list[str]]
) -> list[tuple[str, str, str]]:
    """Find catalog values mentioned in the question, without table-specific cues."""
    mentions = []
    for column, values in catalog.items():
        mentions.extend((mention, column, match_type) for _, mention, match_type in find_all_matches_in_question(question, values))
    return mentions


def extract_mention_near_keyword(question: str, column: str) -> str:
    """Compatibility helper returning the question phrase without domain rules."""
    del column
    return question.strip()


def resolve_values(
    question: str,
    catalog: dict[str, list[str]],
    allowed_tables: Optional[list[str]] = None,
) -> tuple[list[ValueHint], list[NoMatchResult]]:
    """Resolve values present in an arbitrary catalog, optionally by table allowlist."""
    hints: list[ValueHint] = []
    for mention, column, match_type in find_mentions_in_question(question, catalog):
        table_name = column.rsplit(".", 1)[0]
        if allowed_tables and table_name not in allowed_tables:
            continue
        values = catalog[column]
        if match_type == "exact":
            value = next((candidate for candidate in values if candidate.casefold() == mention.casefold()), mention)
            hints.append(ValueHint(mention, column, value, match_type))
        else:
            match = process.extractOne(mention, values, scorer=fuzz.WRatio)
            if match:
                hints.append(ValueHint(mention, column, str(match[0]), "fuzzy"))
    return hints, []


def format_value_hints_for_context(hints: list[ValueHint]) -> str:
    """Format exact resolved values for an LLM prompt."""
    if not hints:
        return ""
    lines = ["=== VALUE HINTS ==="]
    lines.extend(f"- {hint.column}: {hint.mention!r} -> {hint.value!r}" for hint in hints)
    return "\n".join(lines)


def format_no_matches_for_ui(no_matches: list[NoMatchResult]) -> str:
    """Format unresolved value candidates for a UI message."""
    return "\n".join(
        f"No match for {item.mention!r} in {item.column}: {', '.join(item.closest_values)}"
        for item in no_matches
    )
