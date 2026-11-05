"""Compatibility wrapper for dialect-neutral Groq SQL generation."""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from llm.generator import GenerationError, GroqGenerator, clean_sql
from llm.prompt_builder import build_query_prompt


class ClarificationRequiredError(RuntimeError):
    """Raised when the model asks the user to clarify an underspecified request."""


def get_system_instruction(current_date: Optional[str] = None) -> str:
    """Return generic SQL-generation instructions without choosing a dialect."""
    current_date = current_date or date.today().isoformat()
    return (
        f"Current date: {current_date}. Generate one read-only SELECT for the configured database dialect. "
        "Use only supplied tables and columns, and return SQL only."
    )


def generate_sql(
    context: str,
    question: str,
    dialect: str,
    *,
    validation_error: str | None = None,
) -> str:
    """Ask Groq for SQL only; this function never validates or executes the result."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("LLM_MODEL") or os.environ.get("GROQ_MODEL", "")
    generator = GroqGenerator(api_key, model)
    messages = build_query_prompt(context, question, dialect, validation_error)
    if messages is None:
        raise GenerationError("Schema context is malformed.")
    try:
        sql = generator.generate(messages)
    except Exception:
        raise GenerationError("The language model is temporarily unavailable.") from None
    if sql.startswith("ASK_FOR_CLARIFICATION:"):
        raise ClarificationRequiredError("Please clarify the question before generating SQL.")
    return sql


def clean_sql_output(sql: str) -> str:
    """Backward-compatible alias for Markdown fence removal."""
    return clean_sql(sql)
