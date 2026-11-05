"""Prepare a query context using local schema and injected retrieval components."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, TypeAlias

from llm.generator import GenerationError
from llm.prompt_builder import build_query_prompt
from llm.sql_generator import generate_sql
from retrieval.qdrant_retriever import RetrievalResult, retrieve
from retrieval.qdrant_store import QdrantStorageError, QdrantVectorStore, VECTOR_SIZE
from retrieval.value_matcher import match_values
from schema.context import build_query_context
from schema.metadata import SchemaMetadata
from validation.validator import ValidationError, ValueSafetyError, validate_sql

LOGGER = logging.getLogger(__name__)


class QuestionEmbedder(Protocol):
    """Minimal embedding interface required by query preparation."""

    model_name: str
    dim: int

    def embed_single(self, text: str) -> Sequence[float]: ...


@dataclass(frozen=True)
class QueryReady:
    status: Literal["ok"]
    context: str
    retrieval: RetrievalResult
    value_matches: list[dict[str, Any]]
    question: str
    metadata: SchemaMetadata


@dataclass(frozen=True)
class ValidatedQuery:
    status: Literal["validated"] = "validated"
    sql: str = ""


@dataclass(frozen=True)
class QueryGenerationFailed:
    status: Literal["generation_failed"] = "generation_failed"
    message: str = "I could not produce a safe query for that request. Please revise the question."


@dataclass(frozen=True)
class QueryGenerationUnavailable:
    status: Literal["generation_unavailable"] = "generation_unavailable"
    message: str = "The query service is unavailable right now. Please try again."


@dataclass(frozen=True)
class QueryDialectMissing:
    status: Literal["dialect_missing"] = "dialect_missing"
    message: str = "The dataset needs re-indexing to determine the SQL dialect."


@dataclass(frozen=True)
class DatasetUnqueryable:
    status: Literal["unqueryable"] = "unqueryable"
    message: str = "This dataset can't be queried. Please re-upload it."


GeneratedQueryOutcome: TypeAlias = ValidatedQuery | QueryGenerationFailed | QueryGenerationUnavailable | QueryDialectMissing | DatasetUnqueryable


@dataclass(frozen=True)
class QueryNeedsNarrowerQuestion:
    status: Literal["truncated"] = "truncated"
    message: str = "Please narrow the question so its related tables fit the query context."


@dataclass(frozen=True)
class QueryNeedsTableClarification:
    status: Literal["ambiguity"] = "ambiguity"
    message: str = "Please clarify which table you mean."


@dataclass(frozen=True)
class QueryRetrievalFailed:
    status: Literal["retrieval_failed"] = "retrieval_failed"
    message: str = "I could not retrieve the indexed dataset. Please try again or re-index it."


QueryWorkflowOutcome: TypeAlias = (
    QueryReady
    | QueryNeedsNarrowerQuestion
    | QueryNeedsTableClarification
    | QueryRetrievalFailed
)


def prepare_query(
    *,
    question: str,
    metadata: SchemaMetadata,
    value_documents: list[dict[str, Any]],
    embedder: QuestionEmbedder,
    qdrant_store: QdrantVectorStore,
    tenant_id: str,
    dataset_id: str,
    dataset_metadata_path: str,
    selected_k: int = 3,
    max_tables: int = 8,
    sensitive_filter: dict[str, Any] | None = None,
) -> QueryWorkflowOutcome:
    """Embed once, retrieve with Qdrant, then build context from local matches."""
    try:
        if embedder.dim != VECTOR_SIZE:
            return QueryRetrievalFailed()
        matches = match_values(question, value_documents)
        exact_matches = [
            match for match in matches if match.get("match_type") == "exact"
        ]
        exact_value_tables = {str(match["table"]) for match in exact_matches}
        query_vector = embedder.embed_single(question)
        if hasattr(query_vector, "tolist"):
            query_vector = query_vector.tolist()
        retrieval_result = retrieve(
            metadata,
            question,
            selected_k=selected_k,
            max_tables=max_tables,
            sensitive_filter=sensitive_filter,
            exact_value_tables=exact_value_tables,
            qdrant_store=qdrant_store,
            qdrant_tenant_id=tenant_id,
            qdrant_dataset_id=dataset_id,
            qdrant_embedding_model_name=embedder.model_name,
            qdrant_embedding_dimension=embedder.dim,
            qdrant_dataset_metadata_path=dataset_metadata_path,
            query_vector=query_vector,
        )
    except (QdrantStorageError, ValueError, RuntimeError) as error:
        LOGGER.warning("Query retrieval failed: %s", type(error).__name__)
        return QueryRetrievalFailed()
    except Exception as error:
        LOGGER.warning("Query preparation failed: %s", type(error).__name__)
        return QueryRetrievalFailed()

    if not retrieval_result.used_qdrant:
        return QueryRetrievalFailed()
    if retrieval_result.truncated:
        return QueryNeedsNarrowerQuestion()
    if retrieval_result.ambiguity_flag:
        return QueryNeedsTableClarification()

    try:
        if exact_matches:
            matches = exact_matches
        for match in matches:
            match["forced_table"] = False
            if match.get("match_type") == "fuzzy_text":
                match["label"] = "possible match, unconfirmed"
                match["confirmed"] = False

        context = build_query_context(
            metadata,
            retrieval_result.tables,
            matches,
            policy_overrides=sensitive_filter,
        )
    except Exception as error:
        LOGGER.warning("Query context preparation failed: %s", type(error).__name__)
        return QueryRetrievalFailed()
    return QueryReady(
        status="ok",
        context=context,
        retrieval=retrieval_result,
        value_matches=matches,
        question=question,
        metadata=metadata,
    )


def _sanitize_validator_feedback(error: ValidationError | ValueSafetyError) -> str:
    """Return a fixed generic message for retry feedback, never exposing filtered-out names."""
    msg = str(error)
    if isinstance(error, ValueSafetyError):
        if error.kind == "ambiguous":
            return "A value in the query is ambiguous."
        if error.kind == "not_found":
            return "A value in the query was not found."
        return "The query contains an invalid value."
    # ValidationError categories - match on message patterns
    if "does not exist" in msg and "column" in msg.casefold():
        return "The query referenced an unknown column."
    if "does not exist in the catalog" in msg:
        return "The query referenced an unknown table."
    if "was not included in the provided schema" in msg:
        return "The query referenced a table not in the schema."
    if "is ambiguous" in msg and "column" in msg.casefold():
        return "The query referenced an ambiguous column."
    if "restricted column" in msg or "That information isn't available" in msg:
        return "The query referenced a disallowed column."
    if "Multiple SQL statements" in msg:
        return "Only one SELECT statement is allowed."
    if "SQL comments are not allowed" in msg:
        return "SQL comments are not allowed."
    if "Could not parse SQL" in msg:
        return "The SQL could not be parsed."
    if "Mutating or administrative" in msg:
        return "Only read-only SELECT queries are allowed."
    if "restricted SQL function" in msg:
        return "A restricted SQL function was used."
    if "Only a single read-only SELECT" in msg:
        return "Only a single read-only SELECT query is allowed."
    if "Invalid table or column reference" in msg:
        return "The query contains an invalid table or column reference."
    return "The query is invalid."


def generate_sql_from_messages(
    messages: list[dict[str, str]],
    validation_error: str | None = None,
) -> str:
    """Generate SQL from pre-built prompt messages (single prompt build)."""
    import os
    from llm.generator import GroqGenerator, GenerationError
    from llm.sql_generator import ClarificationRequiredError
    api_key = os.environ.get("GROQ_API_KEY", "")
    model = os.environ.get("LLM_MODEL") or os.environ.get("GROQ_MODEL", "")
    generator = GroqGenerator(api_key, model)
    try:
        sql = generator.generate(messages)
    except Exception:
        raise GenerationError("The language model is temporarily unavailable.") from None
    if sql.startswith("ASK_FOR_CLARIFICATION:"):
        raise ClarificationRequiredError("Please clarify the question before generating SQL.")
    return sql


def generate_and_validate_query(query: QueryReady) -> GeneratedQueryOutcome:
    """Generate SQL and validate it against the complete local schema catalog."""
    dialect = query.metadata.dialect or ""
    if not dialect:
        return QueryDialectMissing()

    validation_error: str | None = None
    for attempt in range(2):
        # Build prompt once per attempt - check for forbidden closing tag
        messages = build_query_prompt(
            query.context,
            query.question,
            dialect,
            validation_error=validation_error,
        )
        if messages is None:
            # Schema context contained forbidden closing tag
            return DatasetUnqueryable()

        try:
            sql = generate_sql_from_messages(messages)
            validated_sql = validate_sql(
                sql,
                metadata=query.metadata,
                dialect=dialect,
            )
            return ValidatedQuery(sql=validated_sql)
        except ValidationError as error:
            if attempt == 0:
                validation_error = _sanitize_validator_feedback(error)
                continue
            return QueryGenerationFailed()
        except ValueSafetyError as error:
            if attempt == 0:
                validation_error = _sanitize_validator_feedback(error)
                continue
            return QueryGenerationFailed()
        except GenerationError as error:
            LOGGER.warning("SQL generation failed: %s", type(error).__name__)
            return QueryGenerationUnavailable()
    return QueryGenerationFailed()