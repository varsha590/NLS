#!/usr/bin/env python3
"""Run automated deny-first classification on the configured target database.

Writes classification_report.md containing, per table.column: class and reason.
Names, types, classes, and counts only — NEVER database row values.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from catalog.classifier import (
    ColumnClass,
    DEFAULT_BLOCK_PATTERNS,
    WEAK_BLOCK_TOKENS,
    classify_column,
    get_column_values_have_pii_shape,
    get_column_stats,
    is_candidate_text_column,
    is_flag_like_options,
    normalize_sql_type_name,
    parse_enum_options,
    reviewable_sensitive_name_tokens,
    split_identifier_tokens,
)
from catalog.introspect import introspect_catalog
from config.data_policy import get_policy_overrides, load_database_overrides
from config.settings import Settings
from db.adapter import DatabaseAdapter
from schema.metadata import is_internal_table_name

LOGGER = logging.getLogger(__name__)

DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD = 0.9


def _possible_duplicate_table_groups(
    tables: list,
    similarity_threshold: float = DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
) -> list[dict]:
    """Group tables by Jaccard similarity of their column-name/type structures."""
    signatures = {
        table.name: frozenset(
            (column.name.casefold(), normalize_sql_type_name(column.data_type))
            for column in table.columns
        )
        for table in tables
    }
    adjacency: dict[str, set[str]] = {name: set() for name in signatures}
    matched_scores: dict[tuple[str, str], float] = {}
    for left_name, right_name in combinations(signatures, 2):
        left = signatures[left_name]
        right = signatures[right_name]
        union = left | right
        similarity = len(left & right) / len(union) if union else 1.0
        if similarity >= similarity_threshold:
            adjacency[left_name].add(right_name)
            adjacency[right_name].add(left_name)
            matched_scores[(left_name, right_name)] = similarity

    groups: list[dict] = []
    unseen = set(adjacency)
    while unseen:
        start = unseen.pop()
        component = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            neighbors = adjacency[current] & unseen
            unseen.difference_update(neighbors)
            component.update(neighbors)
            frontier.extend(neighbors)
        if len(component) < 2:
            continue
        scores = [
            score
            for (left_name, right_name), score in matched_scores.items()
            if left_name in component and right_name in component
        ]
        groups.append({"tables": sorted(component), "minimum_similarity": min(scores)})
    return sorted(groups, key=lambda group: group["tables"])


def generate_classification_report(output_path: Path | None = None) -> str:
    settings = Settings.from_env()
    engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
    metadata = introspect_catalog(
        engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
    )
    adapter = DatabaseAdapter(settings.database_url, engine=engine)
    overrides_path = Path(settings.vector_store_path) / adapter.namespace() / "overrides.yaml"
    database_overrides, stale_overrides, override_warnings = load_database_overrides(
        overrides_path, metadata
    )
    overrides = get_policy_overrides(database_overrides)

    class_priority = {
        ColumnClass.BLOCKED.value: 0,
        ColumnClass.MASKED.value: 1,
        ColumnClass.VALUE_LOW.value: 2,
        ColumnClass.VALUE_HIGH.value: 3,
        ColumnClass.SKIP.value: 4,
    }

    records: list[dict] = []
    weak_matches: list[dict] = []
    review_candidates: list[dict] = []
    flag_like_columns: list[dict] = []
    stats_unavailable: dict[str, str] = {}
    shape_checks_unavailable: dict[str, str] = {}
    counts: Counter[str] = Counter()
    report_tables = [
        table_info
        for table_info in metadata.tables.values()
        if not is_internal_table_name(table_info.name)
    ]

    with engine.connect() as conn:
        for table_info in report_tables:
            bare_table_name = table_info.name.rsplit(".", 1)[-1]
            try:
                reflected = sa.Table(
                    bare_table_name,
                    sa.MetaData(),
                    schema=table_info.schema,
                    autoload_with=engine,
                )
            except Exception:
                reflected = None

            table_key = table_info.name

            for col_info in table_info.columns:
                col_name = col_info.name
                col_type = col_info.data_type

                # Check if reflected column exists
                refl_col = reflected.c.get(col_name) if reflected is not None else None
                sql_type = refl_col.type if refl_col is not None else col_type
                options = parse_enum_options(sql_type)
                cnt = len(options) if options is not None else None
                avg_len = None
                sensitive_values_clean = False
                matched_review_tokens = reviewable_sensitive_name_tokens(
                    col_name,
                    tuple(overrides.get("patterns", {}).get("block", DEFAULT_BLOCK_PATTERNS)),
                )
                should_scan = options is None and is_candidate_text_column(
                    table_name=table_key,
                    column_name=col_name,
                    sql_type=sql_type,
                    is_primary_key=col_info.is_primary_key,
                    is_foreign_key=col_info.is_foreign_key,
                    overrides=overrides,
                )

                if should_scan:
                    qualified_column = f"{table_key}.{col_name}"
                    if reflected is None or refl_col is None:
                        stats_unavailable[qualified_column] = "reflection_unavailable"
                        LOGGER.warning(
                            "Column stats unavailable for %s (%s)",
                            qualified_column,
                            "reflection_unavailable",
                            extra={
                                "table": table_key,
                                "column": col_name,
                                "error_category": "reflection_unavailable",
                            },
                        )
                    else:
                        error_categories: list[str] = []
                        cnt, avg_len = get_column_stats(
                            conn,
                            reflected,
                            col_name,
                            threshold=settings.value_cardinality_threshold,
                            on_error=error_categories.append,
                        )
                        if cnt is None:
                            stats_unavailable[qualified_column] = (
                                error_categories[-1] if error_categories else "no_result"
                            )
                        elif matched_review_tokens and cnt <= settings.value_cardinality_threshold:
                            shape_errors: list[str] = []
                            has_pii_shape = get_column_values_have_pii_shape(
                                conn,
                                reflected,
                                col_name,
                                threshold=settings.value_cardinality_threshold,
                                on_error=shape_errors.append,
                            )
                            sensitive_values_clean = has_pii_shape is False
                            if shape_errors:
                                shape_checks_unavailable[qualified_column] = shape_errors[-1]

                # 2. Final classification
                final_class, final_reason = classify_column(
                    table_name=table_key,
                    column_name=col_name,
                    sql_type=sql_type,
                    distinct_count=cnt,
                    avg_text_length=avg_len,
                    is_primary_key=col_info.is_primary_key,
                    is_foreign_key=col_info.is_foreign_key,
                    overrides=overrides,
                    cardinality_threshold=settings.value_cardinality_threshold,
                    sensitive_values_clean=sensitive_values_clean,
                )

                class_str = final_class.value
                counts[class_str] += 1

                # Check for weak/ambiguous token matching
                tokens = split_identifier_tokens(col_name)
                matched_weak = [t for t in tokens if t in WEAK_BLOCK_TOKENS]
                is_weak = False
                if class_str == ColumnClass.BLOCKED.value and matched_weak:
                    # Weak if token matches but column has multiple tokens (e.g. translation_lat, company_pan)
                    is_weak = True
                    weak_matches.append({
                        "table": table_key,
                        "column": col_name,
                        "tokens": matched_weak,
                        "reason": final_reason,
                    })

                if class_str == ColumnClass.VALUE_LOW.value and matched_review_tokens:
                    review_candidates.append({
                        "table": table_key,
                        "column": col_name,
                        "tokens": matched_review_tokens,
                        "count": cnt,
                    })

                if (
                    class_str == ColumnClass.VALUE_LOW.value
                    and options is not None
                    and is_flag_like_options(options)
                ):
                    flag_like_columns.append({
                        "table": table_key,
                        "column": col_name,
                        "option_count": len(options),
                    })

                records.append({
                    "table": table_key,
                    "column": col_name,
                    "type": str(col_type),
                    "class": class_str,
                    "count": cnt if cnt is not None else "-",
                    "option_count": len(options) if options is not None else None,
                    "reason": final_reason,
                    "is_weak": is_weak,
                })

    # Sort records: BLOCKED, MASKED, VALUE_LOW, VALUE_HIGH, SKIP, then table, column
    records.sort(
        key=lambda r: (class_priority.get(r["class"], 99), r["table"], r["column"])
    )
    duplicate_groups = _possible_duplicate_table_groups(report_tables)
    total_columns = sum(len(table.columns) for table in report_tables)

    # Format Markdown
    lines = [
        "# Database Column Classification Report",
        "",
        "Deny-first privacy classification summary across all catalog columns.",
        "Values, row data, and credentials are never included in this report.",
        "",
        "## Summary Counts",
        "",
        "| Class | Column Count | Description |",
        "|---|---|---|",
        f"| **BLOCKED** | {counts.get('BLOCKED', 0)} | Completely excluded from DDL, embeddings, retriever, and logs |",
        f"| **MASKED** | {counts.get('MASKED', 0)} | Retained in DDL for queries; output values masked |",
        f"| **VALUE_LOW** | {counts.get('VALUE_LOW', 0)} | Fully indexed for value resolution (distinct count <= threshold) |",
        f"| **VALUE_HIGH** | {counts.get('VALUE_HIGH', 0)} | Resolved dynamically at query time; not sent to LLM |",
        f"| **SKIP** | {counts.get('SKIP', 0)} | Keys, non-text, free text, embeddings, hashes (retained in DDL for joins) |",
        f"| **Total** | {len(records)} | Total columns classified |",
        "",
        "## Catalog Size",
        "",
        f"Tables included: **{len(report_tables)}**",
        f"Columns included: **{total_columns}**",
        "",
        "## STALE OVERRIDES",
        "",
    ]
    if stale_overrides:
        lines.extend(f"- `{name}`" for name in stale_overrides)
    else:
        lines.append("No stale table or column overrides.")
    if override_warnings:
        lines.extend(["", "Rejected overrides:"])
        lines.extend(f"- {warning}" for warning in override_warnings)
    lines.extend([
        "",
        "## POSSIBLE DUPLICATE TABLES",
        "",
        f"Structure similarity threshold: {DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD:.0%}. Detection uses column-name/type structure only; groups are advisory and no tables are excluded automatically.",
        "",
    ])

    if duplicate_groups:
        lines.extend([
            "| Group | Tables | Minimum matched similarity |",
            "|---|---|---:|",
        ])
        for index, group in enumerate(duplicate_groups, start=1):
            table_list = ", ".join(f"`{table_name}`" for table_name in group["tables"])
            lines.append(
                f"| {index} | {table_list} | {group['minimum_similarity']:.1%} |"
            )
        lines.append("")
    else:
        lines.extend(["No table pairs met the structure similarity threshold.", ""])

    lines.extend(["## REVIEW", ""])
    if review_candidates:
        lines.extend([
            "Low-cardinality columns with non-credential sensitive-name matches and no detected PII-shaped values. They remain VALUE_LOW for manual review.",
            "",
            "| Table | Column | Matched pattern(s) | Option / distinct count |",
            "|---|---|---|---:|",
        ])
        for candidate in review_candidates:
            lines.append(
                f"| `{candidate['table']}` | `{candidate['column']}` | {', '.join(candidate['tokens'])} | {candidate['count']} |"
            )
        lines.append("")
    else:
        lines.extend(["No low-cardinality sensitive-name columns qualified for review.", ""])

    lines.extend(["## FLAG-LIKE VALUE COLUMNS", ""])
    if flag_like_columns:
        lines.extend([
            "VALUE_LOW columns whose declared options are all digits or a recognized boolean-like pair. Meaning is intentionally not inferred.",
            "",
            "| Table | Column | Option count |",
            "|---|---|---:|",
        ])
        for candidate in flag_like_columns:
            lines.append(
                f"| `{candidate['table']}` | `{candidate['column']}` | {candidate['option_count']} |"
            )
        lines.append("")
    else:
        lines.extend(["No VALUE_LOW columns had digit-only options or a recognized boolean-like pair.", ""])

    lines.extend(["## Columns With Stats Unavailable", ""])
    if stats_unavailable:
        lines.extend([
            "Each entry below includes an error category; no exception text or row values are included.",
            "",
            "| Table.Column | Error category |",
            "|---|---|",
        ])
        for qualified_column, category in sorted(stats_unavailable.items()):
            lines.append(f"| `{qualified_column}` | {category} |")
        lines.append("")
    else:
        lines.extend(["0 columns had stats unavailable.", ""])

    lines.extend(["## Sensitive-Value Shape Checks Unavailable", ""])
    if shape_checks_unavailable:
        lines.extend([
            "These candidates remain BLOCKED because low-cardinality values could not be checked safely.",
            "",
            "| Table.Column | Error category |",
            "|---|---|",
        ])
        for qualified_column, category in sorted(shape_checks_unavailable.items()):
            lines.append(f"| `{qualified_column}` | {category} |")
        lines.append("")
    else:
        lines.extend(["0 sensitive-value shape checks were unavailable.", ""])

    if weak_matches:
        lines.extend([
            "## Ambiguous / Weak Token Matches (Review Recommended)",
            "",
            "Columns blocked by a short or generic token where manual review may be helpful:",
            "",
            "| Table | Column | Matched Token(s) | Reason |",
            "|---|---|---|---|",
        ])
        for wm in weak_matches:
            lines.append(f"| `{wm['table']}` | `{wm['column']}` | `{', '.join(wm['tokens'])}` | {wm['reason']} |")
        lines.append("")
    else:
        lines.extend([
            "## Ambiguous / Weak Token Matches",
            "",
            "No columns matched block patterns via ambiguous/weak tokens.",
            "",
        ])

    lines.extend([
        "## Detailed Column Classifications",
        "",
        "| Table | Column | SQL Type | Class | Distinct Count | Reason |",
        "|---|---|---|---|---|---|",
    ])
    for r in records:
        lines.append(
            f"| `{r['table']}` | `{r['column']}` | `{r['type']}` | **{r['class']}** | {r['count']} | {r['reason']} |"
        )
    lines.append("")

    report_content = "\n".join(lines)

    target_path = output_path or (PROJECT_ROOT / "classification_report.md")
    target_path.write_text(report_content, encoding="utf-8")
    return report_content


def main() -> None:
    report = generate_classification_report()
    print("Classification report generated successfully.")
    print("-" * 60)
    # Print summary to stdout
    for line in report.splitlines()[:25]:
        print(line)


if __name__ == "__main__":
    main()

