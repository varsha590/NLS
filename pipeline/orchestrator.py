"""Coordinate retrieval, generation, validation, execution, and answer synthesis."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlalchemy as sa
import sqlglot
from sqlglot import exp

from db.adapter import DatabaseAdapter, DatabaseUnavailableError
from llm.generator import GenerationError, GroqGenerator
from llm.prompt_builder import build_prompt
from retrieval.examples import ExampleStore
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.value_index import ValueIndex

try:
    from config.data_policy import is_blocked, is_masked, mask_value
except Exception:
    # Fail closed: treat as blocked and mask all values if data policy is unavailable
    def is_blocked(key: str) -> bool:
        return True
    def is_masked(key: str) -> bool:
        return True
    def mask_value(v: Any) -> str:
        return "***"
from schema.metadata import SchemaMetadata
from validation.validator import ValidationError, ValueSafetyError, validate_sql

LOGGER = logging.getLogger(__name__)


def _build_answer_text(question: str, rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Build a natural-language answer from result rows without sending values to an LLM."""
    if not rows:
        return "The query completed successfully and returned no matching rows."
    if len(rows) == 1 and len(columns) == 1:
        col = columns[0]
        val = rows[0].get(col)
        return f"{col}: {val}"
    if len(rows) == 1:
        parts = [f"{col}: {rows[0].get(col)}" for col in columns]
        return "; ".join(parts)
    # Top-N or multi-row: build a list
    lines = []
    for row in rows[:20]:
        parts = [f"{col}: {row.get(col)}" for col in columns]
        lines.append(", ".join(parts))
    return "\n".join(lines)


@dataclass
class PipelineResult:
    """Stable structured output for UI, tests, and evaluation callers."""

    sql: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    resolved_values: list[dict[str, Any]] = field(default_factory=list)
    tables_used: list[str] = field(default_factory=list)
    retries: int = 0
    timings: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    ambiguous_values: list[dict[str, Any]] = field(default_factory=list)
    not_found_values: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return asdict(self)


class TextToSQLPipeline:
    """Run the database-agnostic query workflow using injected collaborators."""

    def __init__(
        self,
        adapter: DatabaseAdapter,
        metadata: SchemaMetadata,
        retriever: HybridSchemaRetriever,
        generator: GroqGenerator,
        value_index: ValueIndex | None = None,
        examples: ExampleStore | None = None,
        max_rows: int = 100,
        max_retries: int = 3,
        schema_top_k: int = 8,
        value_top_k: int = 5,
    ) -> None:
        self.adapter = adapter
        self.metadata = metadata
        self.retriever = retriever
        self.generator = generator
        self.value_index = value_index
        self.examples = examples
        self.max_rows = max_rows
        self.max_retries = max_retries
        self.schema_top_k = schema_top_k
        self.value_top_k = value_top_k

    def _uses_status_as_activity_proxy(self, question: str, sql: str) -> bool:
        """Detect status filters in questions phrased as activity metrics."""
        if self.value_index is None:
            return False
        question_words = set(re.findall(r"[\w'-]+", question.casefold()))
        metric_terms = getattr(self.value_index, "metric_terms", set())
        if not question_words.intersection(metric_terms):
            return False
        try:
            parsed = sqlglot.parse_one(sql, read=self.adapter.get_sqlglot_dialect())
        except sqlglot.errors.ParseError:
            return False
        where = parsed.args.get("where")
        if where is None:
            return False
        status_columns = getattr(self.value_index, "status_filter_column_names", set())
        return any(
            column.name.casefold() in status_columns
            for column in where.find_all(exp.Column)
        )

    def run(self, question: str, confirmed_values: list[dict[str, Any]] | None = None) -> PipelineResult:
        """Process a natural-language question and return rows plus an answer."""
        result = PipelineResult()
        total_started = time.monotonic()
        try:
            value_started = time.monotonic()
            raw_value_matches = (
                self.value_index.resolve_question(question, self.value_top_k)
                if self.value_index else []
            )
            supplied_values = confirmed_values or []
            skipped_mentions = {
                value.get("mention", "").casefold()
                for value in supplied_values
                if value.get("skip")
            }
            confirmed_mentions = {
                value.get("mention", "").casefold()
                for value in supplied_values
            }
            result.ambiguous_values = [
                match for match in raw_value_matches
                if match.get("ambiguous")
                and match.get("mention", "").casefold() not in confirmed_mentions
            ]
            result.not_found_values = [
                match for match in raw_value_matches
                if match.get("not_found")
                and match.get("mention", "").casefold() not in skipped_mentions
            ]
            result.resolved_values = [
                match for match in raw_value_matches
                if not match.get("ambiguous") and not match.get("not_found")
            ]
            result.resolved_values.extend(value for value in supplied_values if not value.get("skip"))
            result.timings["value_resolution_ms"] = (time.monotonic() - value_started) * 1000
            if result.ambiguous_values:
                result.answer = "Please confirm the highlighted value before I generate a query."
                result.timings["total_ms"] = (time.monotonic() - total_started) * 1000
                return result

            retrieval_started = time.monotonic()
            retrieval_question = question
            metric_terms = getattr(self.value_index, "metric_terms", set())
            question_words = set(re.findall(r"[\w'-]+", question.casefold()))
            if question_words.intersection(metric_terms):
                expansion = getattr(self.value_index, "activity_query_expansion", ())
                retrieval_question = " ".join((question, *expansion))
            retrieval = self.retriever.retrieve(retrieval_question, self.schema_top_k)
            result.tables_used = retrieval["tables"]
            result.timings["schema_retrieval_ms"] = (time.monotonic() - retrieval_started) * 1000
            examples = self.examples.retrieve(question, self.value_top_k) if self.examples else []

            correction = None
            for attempt in range(self.max_retries + 1):
                result.retries = attempt
                # Send resolved value mappings to LLM only for VALUE_LOW columns (Phase 1 privacy boundary)
                llm_resolved_values = [
                    v for v in result.resolved_values
                    if self.value_index is None
                    or v.get("column") in self.value_index.values
                ]
                messages = build_prompt(
                    question=question,
                    dialect=self.adapter.get_dialect(),
                    ddl=retrieval["ddl"],
                    resolved_values=llm_resolved_values,
                    examples=examples,
                    correction=correction,
                )
                generation_started = time.monotonic()
                try:
                    generated_sql = self.generator.generate(messages)
                    result.timings["generation_ms"] = result.timings.get("generation_ms", 0) + (
                        time.monotonic() - generation_started
                    ) * 1000
                    result.sql = generated_sql
                    result.sql = validate_sql(
                        generated_sql,
                        metadata=self.metadata,
                        dialect=self.adapter.get_sqlglot_dialect(),
                        allowed_tables=set(result.tables_used),
                        max_rows=self.max_rows,
                        adapter=self.adapter,
                        value_index=self.value_index,
                        resolved_values=result.resolved_values,
                    )
                    if self._uses_status_as_activity_proxy(question, result.sql):
                        raise ValidationError(
                            "An activity or ranking query cannot use a current-status filter "
                            "as a proxy for historical activity. Use event or transaction measures."
                        )
                except (GenerationError, ValidationError) as error:
                    result.timings["generation_ms"] = result.timings.get("generation_ms", 0) + (
                        time.monotonic() - generation_started
                    ) * 1000 if isinstance(error, GenerationError) else result.timings.get("generation_ms", 0)
                    result.errors.append(str(error))
                    result.sql = ""  # Clear unverified SQL on validation failure (0e fix)
                    correction = str(error)
                    if attempt < self.max_retries:
                        continue
                    if "That information isn't available." in str(error):
                        result.answer = "That information isn't available."
                    else:
                        result.answer = "I could not produce a safe query for that request. Please revise the question."
                    break
                except ValueSafetyError as error:
                    col_key = error.column or ""
                    is_restricted_col = (
                        is_blocked(col_key)
                        or is_masked(col_key)
                        or (self.value_index is not None and col_key in getattr(self.value_index, "large_columns", set()))
                    )
                    safe_error_str = (
                        f"Literal filter on restricted column '{col_key}' rejected."
                        if is_restricted_col
                        else str(error)
                    )
                    metric_terms = getattr(self.value_index, "metric_terms", set())
                    excluded_terms = getattr(self.value_index, "excluded_terms", set())
                    mention_words = {word.casefold() for word in error.mention.split()}
                    is_metric_phrase = bool(mention_words & metric_terms) and mention_words.issubset(
                        metric_terms | excluded_terms
                    )
                    if (
                        error.kind == "not_found"
                        and is_metric_phrase
                        and attempt < self.max_retries
                    ):
                        result.errors.append(safe_error_str)
                        result.sql = ""
                        correction = (
                            f"{safe_error_str} The rejected literal is configured as metric vocabulary, "
                            "not a stored value. Reinterpret the requested historical activity using "
                            "measures in event or transaction records and their schema relationships. "
                            "Do not use status, availability, or inventory-state columns as a proxy "
                            "unless the question explicitly asks for current status."
                        )
                        continue
                    if error.kind == "ambiguous":
                        result.ambiguous_values = [{
                            "mention": error.mention if not is_restricted_col else "[restricted]",
                            "ambiguous": True,
                            "candidates": [{"column": error.column, "value": v if not is_restricted_col else "[restricted]", "confidence": 0.0} for v in error.closest],
                            "confidence": 0.0,
                        }]
                    else:
                        result.not_found_values = [{
                            "mention": error.mention if not is_restricted_col else "[restricted]",
                            "not_found": True,
                            "column": error.column,
                            "candidates": [{"value": v} for v in (error.closest if not is_restricted_col else [])],
                            "confidence": 0.0,
                        }]
                    result.errors.append(safe_error_str)
                    result.sql = ""  # Clear unverified SQL
                    if is_restricted_col:
                        result.answer = "I could not produce a safe query for that request."
                    elif error.kind == "not_found":
                        closest_values = [v for v in error.closest if v and v != "none"]
                        closest_str = ", ".join(closest_values) if closest_values else "none"
                        result.answer = f"I couldn't find a value matching '{error.mention}'. Closest: {closest_str}."
                    elif error.kind == "ambiguous":
                        result.answer = "Please confirm the highlighted value before I generate a query."
                    else:
                        result.answer = "I couldn't verify all values in the generated query."
                    result.timings["total_ms"] = (time.monotonic() - total_started) * 1000
                    return result

                execution_started = time.monotonic()
                try:
                    query_result = self.adapter.run_readonly_query(result.sql, self.max_rows)
                    result.rows = query_result.rows
                    result.columns = query_result.columns
                    # Apply masking for 'mask' columns
                    if result.rows and result.columns:
                        masked_columns = [col for col in result.columns if is_masked(f"{result.tables_used[0] if result.tables_used else ''}.{col}".strip("."))]
                        # More robust: check all tables
                        mask_cols = set()
                        for col in result.columns:
                            for tbl in (result.tables_used or [""]):
                                if is_masked(f"{tbl}.{col}"):
                                    mask_cols.add(col)
                        if mask_cols:
                            for row in result.rows:
                                for col in mask_cols:
                                    if col in row and row[col] is not None:
                                        row[col] = mask_value(row[col])
                    result.errors.clear()
                    result.timings["execution_ms"] = result.timings.get("execution_ms", 0) + (
                        time.monotonic() - execution_started
                    ) * 1000
                    break
                except DatabaseUnavailableError as error:
                    result.timings["execution_ms"] = result.timings.get("execution_ms", 0) + (
                        time.monotonic() - execution_started
                    ) * 1000
                    result.errors.append(str(error))
                    result.sql = ""  # Clear unexecuted SQL on execution failure (0e fix)
                    correction = str(error)
                    if attempt >= self.max_retries:
                        result.answer = "The query could not be run against the connected database."

            has_unresolved = bool(result.not_found_values) or bool(result.ambiguous_values)
            if has_unresolved:
                if result.not_found_values:
                    nf = result.not_found_values[0]
                    # Try to get closest values
                    closest_values = []
                    if nf.get("candidates"):
                        closest_values = [c.get("value", c) for c in nf["candidates"] if isinstance(c, dict)]
                    if not closest_values and self.value_index:
                        # Look up closest from score candidates
                        try:
                            col = nf.get("column")
                            sc = self.value_index._score_candidates(nf["mention"], col, 5)
                            closest_values = [c["value"] for c in sc[:3]]
                        except Exception:
                            pass
                    # For safety-net not_found, closest may be stored in candidates
                    if not closest_values:
                        # Check if candidates have value key (safety net stores them)
                        for c in nf.get("candidates", []):
                            if isinstance(c, dict) and "value" in c:
                                closest_values.append(c["value"])
                            elif isinstance(c, str):
                                closest_values.append(c)
                    closest_str = ", ".join(closest_values) if closest_values else "none"
                    result.answer = f"I couldn't find a value matching '{nf['mention']}'. Closest: {closest_str}."
                elif result.ambiguous_values:
                    result.answer = "Please confirm the highlighted value before I generate a query."
            if has_unresolved:
                pass
            else:
                if result.sql and result.rows and (
                    not result.errors or result.timings.get("execution_ms") is not None
                ):
                    # Build answer in code (no LLM call with rows)
                    result.answer = _build_answer_text(question, result.rows, result.columns)
                elif result.sql and not result.errors:
                    result.answer = _build_answer_text(question, result.rows, result.columns)
            if not result.answer:
                result.answer = "The query completed." if result.sql else "No query was generated."
        except (DatabaseUnavailableError, GenerationError, ValidationError, ValueError, OSError, sa.exc.SQLAlchemyError) as error:
            LOGGER.exception("Text-to-SQL pipeline failed")
            result.errors.append(str(error))
            result.answer = "The request could not be completed. Check the connection and try again."
        result.timings["total_ms"] = (time.monotonic() - total_started) * 1000
        return result