"""Construct constrained, dialect-aware text-to-SQL prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_prompt(
    question: str,
    dialect: str,
    ddl: str,
    resolved_values: list[dict[str, Any]] | None = None,
    examples: list[dict[str, str]] | None = None,
    correction: str | None = None,
    hints_path: str | Path = "hints.md",
) -> list[dict[str, str]]:
    """Build system and user messages from current catalog context and hints."""
    try:
        domain_hints = Path(hints_path).read_text(encoding="utf-8").strip()
    except OSError:
        domain_hints = ""
    value_text = "\n".join(
        f"- {item['mention']} -> {item['column']} = {item['value']}"
        for item in resolved_values or []
    ) or "None"
    examples_text = "\n\n".join(
        f"Question: {example['question']}\nSQL: {example['sql']}"
        for example in examples or []
    ) or "None"
    system = (
        f"You generate SQL for the {dialect} dialect. Return SQL only. "
        "Generate one read-only SELECT statement. Use only the tables and columns in the supplied schema. "
        "Use full table names or consistent aliases, and never invent identifiers. "
        "Use resolved values exactly as supplied. Interpret activity and ranking language using measurable "
        "quantities and relationships in the schema; do not turn an activity into a status or category "
        "filter unless the question explicitly asks for that stored value. For historical activity or "
        "volume, aggregate measures from event or transaction records; do not use current status, "
        "availability, or inventory state as a proxy. When a requested full name is split across multiple "
        "schema columns, select all name components."
    )
    user = (
        f"Question:\n{question}\n\nSchema:\n{ddl}\n\nResolved values:\n{value_text}\n\n"
        f"Domain hints:\n{domain_hints or 'None'}\n\nVerified examples:\n{examples_text}"
    )
    if correction:
        user += f"\n\nCorrect the previous SQL using this validation error:\n{correction}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]