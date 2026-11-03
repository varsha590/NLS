"""Groq SQL generation and result summarization."""

from __future__ import annotations

import logging
import re
from typing import Any

LOGGER = logging.getLogger(__name__)


class GenerationError(RuntimeError):
    """Raised when the configured LLM cannot produce a usable response."""


def clean_sql(text: str) -> str:
    """Remove surrounding Markdown code fences from generated SQL."""
    cleaned = text.strip()
    match = re.fullmatch(r"```(?:sql)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else cleaned.strip("`").strip()


class GroqGenerator:
    """Call Groq lazily so SQLite tests and offline indexing need no API key."""

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def _complete(self, messages: list[dict[str, str]], max_tokens: int = 1200) -> str:
        if not self.api_key:
            raise GenerationError("Set GROQ_API_KEY in .env to enable SQL generation.")
        try:
            from groq import Groq

            response = Groq(api_key=self.api_key).chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise GenerationError("The LLM returned an empty response.")
            return content.strip()
        except GenerationError:
            raise
        except Exception as error:
            LOGGER.error("LLM request failed", extra={"error_type": type(error).__name__})
            raise GenerationError("The language model is temporarily unavailable.") from error

    def generate(self, messages: list[dict[str, str]]) -> str:
        """Generate and clean one SQL string."""
        return clean_sql(self._complete(messages))

    def summarize(self, question: str, rows: list[dict[str, Any]]) -> str:
        """Return a safe summary without sending row values to the LLM."""
        if not rows:
            return "The query completed successfully and returned no matching rows."
        columns = list(rows[0].keys()) if rows else []
        messages = [
            {"role": "system", "content": "Summarize these database query results concisely. Do not invent facts."},
            {"role": "user", "content": f"Question: {question}\nColumns: {columns}\nRow count: {len(rows)}"},
        ]
        return self._complete(messages, max_tokens=300)