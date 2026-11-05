"""Prepare a query context using local schema and injected retrieval components."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, TypeAlias

from retrieval.qdrant_retriever import RetrievalResult, retrieve
from retrieval.qdrant_store import QdrantStorageError, QdrantVectorStore, VECTOR_SIZE
from retrieval.value_matcher import match_values
from schema.context import build_query_context
from schema.metadata import SchemaMetadata

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
    )