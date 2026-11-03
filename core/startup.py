"""Application startup and process-wide database-agnostic resources."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from catalog.introspect import introspect_catalog
from config.settings import Settings
from db.adapter import DatabaseAdapter
from llm.generator import GroqGenerator
from pipeline.orchestrator import TextToSQLPipeline
from retrieval.embeddings import EmbeddingModel
from retrieval.examples import ExampleStore
from retrieval.local_store import LocalVectorStore
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.value_index import ValueIndex
from schema.documents import (
    build_column_document,
    build_relationship_document,
    build_table_document,
)
from schema.metadata import is_internal_table_name

LOGGER = logging.getLogger(__name__)
_runtime: dict[str, Any] = {}


def _config_policy_hash(threshold: int) -> str:
    """Fingerprint policy/config inputs that affect index eligibility and content."""
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for relative_path in ("config/data_policy.yaml", "config/value_resolution.yaml"):
        digest.update((root / relative_path).read_bytes())
    digest.update(str(threshold).encode("ascii"))
    return digest.hexdigest()


def _schema_records(metadata: Any) -> list[dict[str, Any]]:
    """Build schema-only documents from unprotected catalog structure."""
    records: list[dict[str, Any]] = []
    for table in metadata.tables.values():
        if is_internal_table_name(table.name):
            continue
        records.append({
            "table_name": table.name,
            "column_name": None,
            "metadata_type": "table_ddl",
            "content": build_table_document(table),
        })
        for column in table.columns:
            content = build_column_document(table, column)
            if content:
                records.append({
                    "table_name": table.name,
                    "column_name": column.name,
                    "metadata_type": "column_description",
                    "content": content,
                })
        for index, relation in enumerate(table.foreign_keys):
            content = build_relationship_document(table, relation)
            if content:
                column_name = (
                    relation.get("column")
                    or relation.get("local_column")
                    or f"relationship_{index}"
                )
                records.append({
                    "table_name": table.name,
                    "column_name": column_name,
                    "metadata_type": "relationship",
                    "content": content,
                })
    return records


def init_app(force: bool = False) -> dict[str, Any]:
    """Connect read-only, introspect, and locally index the configured database."""
    settings = Settings.from_env()
    adapter = DatabaseAdapter(settings.database_url, settings.query_timeout_seconds)
    connection = adapter.connect()
    try:
        connection.exec_driver_sql("SELECT 1")
    finally:
        connection.close()

    metadata = introspect_catalog(
        adapter.engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
        sample_limit=0,
    )
    embedding_model = EmbeddingModel(settings.embedding_model)
    local_store = LocalVectorStore(
        root=settings.vector_store_path,
        namespace=adapter.namespace(),
        model_name=embedding_model.model_name,
        dimension=embedding_model.dim,
        policy_hash=_config_policy_hash(settings.value_cardinality_threshold),
        example_candidate_limit=settings.example_candidate_limit,
    )
    had_local_index = local_store.count_schema() > 0 or local_store.count_values() > 0
    if force:
        local_store.clear_indexes()

    schema_ok = local_store.build_schema(_schema_records(metadata), embedding_model)
    value_index = ValueIndex(
        adapter=adapter,
        metadata=metadata,
        cardinality_threshold=settings.value_cardinality_threshold,
        embedder=embedding_model,
        local_store=local_store,
    )
    value_index.build()
    value_ok = value_index.build_success
    index_complete = schema_ok and value_ok
    if not index_complete:
        LOGGER.warning(
            "Local index build completed with errors",
            extra={"dialect": adapter.get_dialect()},
        )

    retriever = HybridSchemaRetriever(metadata, embedding_model, local_store=local_store)
    generator = GroqGenerator(settings.groq_api_key, settings.llm_model)
    examples = ExampleStore(
        settings.vector_store_path,
        adapter,
        local_store=local_store,
        candidate_limit=settings.example_candidate_limit,
    )
    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=metadata,
        retriever=retriever,
        generator=generator,
        value_index=value_index,
        examples=examples,
        max_rows=settings.max_rows,
        max_retries=settings.max_retries,
        schema_top_k=settings.schema_top_k,
        value_top_k=settings.value_top_k,
    )

    catalog_status = (
        "incomplete"
        if not index_complete
        else "cached" if had_local_index and not force
        else "indexed"
    )
    runtime = {
        "settings": settings,
        "adapter": adapter,
        "engine": adapter.engine,
        "metadata": metadata,
        "retriever": retriever,
        "local_store": local_store,
        "value_index": value_index,
        "examples": examples,
        "pipeline": pipeline,
        "indexed_tables": len(metadata.tables),
        "catalog_status": catalog_status,
        "index_complete": index_complete,
    }
    _runtime.clear()
    _runtime.update(runtime)
    LOGGER.info(
        "Application ready",
        extra={"dialect": adapter.get_dialect(), "indexed_tables": len(metadata.tables)},
    )
    return runtime


def get_runtime() -> dict[str, Any]:
    """Return resources created by the most recent successful initialization."""
    if not _runtime:
        raise RuntimeError("Application startup has not completed.")
    return _runtime