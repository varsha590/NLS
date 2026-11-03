#!/usr/bin/env python3
"""Run automated deny-first classification on the configured target database.

Writes classification_report.md containing, per table.column: class and reason.
Names, types, classes, and counts only — NEVER database row values.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from catalog.classifier import (
    ColumnClass,
    DEFAULT_CARDINALITY_THRESHOLD,
    WEAK_BLOCK_TOKENS,
    classify_column,
    get_column_stats,
    split_identifier_tokens,
)
from catalog.introspect import introspect_catalog
from config.data_policy import get_policy_overrides
from config.settings import Settings
from schema.metadata import is_internal_table_name


def generate_classification_report(output_path: Path | None = None) -> str:
    settings = Settings.from_env()
    engine = sa.create_engine(settings.database_url, pool_pre_ping=True)
    metadata = introspect_catalog(
        engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
        sample_limit=0,  # Do not collect row samples
    )
    overrides = get_policy_overrides()

    class_priority = {
        ColumnClass.BLOCKED.value: 0,
        ColumnClass.MASKED.value: 1,
        ColumnClass.VALUE_LOW.value: 2,
        ColumnClass.VALUE_HIGH.value: 3,
        ColumnClass.SKIP.value: 4,
    }

    records: list[dict] = []
    weak_matches: list[dict] = []
    counts: Counter[str] = Counter()

    with engine.connect() as conn:
        for table_info in metadata.tables.values():
            if is_internal_table_name(table_info.name):
                continue
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

                # 1. Preliminary classification
                prelim_class, prelim_reason = classify_column(
                    table_name=table_key,
                    column_name=col_name,
                    sql_type=sql_type,
                    is_primary_key=col_info.is_primary_key,
                    is_foreign_key=col_info.is_foreign_key,
                    overrides=overrides,
                    cardinality_threshold=settings.value_cardinality_threshold,
                )

                cnt = None
                avg_len = None

                # Only run distinct count query if text candidate not already blocked/skipped
                if prelim_class not in (ColumnClass.BLOCKED, ColumnClass.MASKED, ColumnClass.SKIP):
                    if reflected is not None:
                        cnt, avg_len = get_column_stats(
                            conn,
                            reflected,
                            col_name,
                            threshold=settings.value_cardinality_threshold,
                        )

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

                records.append({
                    "table": table_key,
                    "column": col_name,
                    "type": str(col_type),
                    "class": class_str,
                    "count": cnt if cnt is not None else "-",
                    "reason": final_reason,
                    "is_weak": is_weak,
                })

    # Sort records: BLOCKED, MASKED, VALUE_LOW, VALUE_HIGH, SKIP, then table, column
    records.sort(
        key=lambda r: (class_priority.get(r["class"], 99), r["table"], r["column"])
    )

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
    ]

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

