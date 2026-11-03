"""Compatibility wrapper for dialect-neutral Groq SQL generation."""

from __future__ import annotations

from datetime import date
from typing import Optional

from config.settings import Settings
from llm.generator import GenerationError, GroqGenerator, clean_sql
from llm.prompt_builder import build_prompt


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
    question: str,
    schema_context: str,
    allowed_tables: list[str],
    model_name: Optional[str] = None,
    correction_sql: Optional[str] = None,
    error_message: Optional[str] = None,
) -> str:
    """Generate SQL with the configured Groq model, preserving the legacy signature."""
    settings = Settings.from_env()
    generator = GroqGenerator(settings.groq_api_key, model_name or settings.llm_model)
    correction = None
    if correction_sql and error_message:
        correction = f"Previous SQL: {correction_sql}\nValidation error: {error_message}"
    messages = build_prompt(
        question=question,
        dialect="configured SQL",
        ddl=schema_context,
        correction=correction,
    )
    try:
        sql = generator.generate(messages)
    except GenerationError:
        raise
    if sql.startswith("ASK_FOR_CLARIFICATION:"):
        raise ClarificationRequiredError(sql.split(":", 1)[1].strip())
    return sql


def clean_sql_output(sql: str) -> str:
    """Backward-compatible alias for Markdown fence removal."""
    return clean_sql(sql)
