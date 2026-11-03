"""Application startup and process-wide database-agnostic resources."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from catalog.introspect import introspect_catalog
from config.settings import Settings
from db.adapter import DatabaseAdapter, EmbeddingStore
from llm.generator import GroqGenerator
from pipeline.orchestrator import TextToSQLPipeline
from retrieval.embeddings import EmbeddingModel
from retrieval.examples import ExampleStore
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.value_index import ValueIndex
LOGGER = logging.getLogger(__name__)
_runtime: dict[str, Any] = {}
_catalog_fingerprints: set[tuple[str, str]] = set()


def init_app(force: bool = False) -> dict[str, Any]:
    """Connect, introspect, and locally index the configured database schema."""
    settings = Settings.from_env()
    adapter = DatabaseAdapter(settings.database_url, settings.query_timeout_seconds)
    connection = adapter.connect()
    try:
        connection.exec_driver_sql("SELECT 1")
    finally:
        connection.close()

    adapter.ensure_pgvector()

    metadata = introspect_catalog(
        adapter.engine,
        allowed_schemas=settings.allowed_schemas,
        excluded_tables=settings.excluded_tables,
    )
    schema_payload = metadata.to_dict()
    schema_hash = hashlib.sha256(
        json.dumps(schema_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    catalog_fingerprint = (adapter.namespace(), schema_hash)
    previously_indexed = not force and catalog_fingerprint in _catalog_fingerprints

    embedding_store = EmbeddingStore(adapter)

    schema_count = embedding_store.count_schema()

    cached_is_current = not force and schema_count > 0

    embedding_model = EmbeddingModel(settings.embedding_model)

    if not cached_is_current:
        # Build schema embeddings from introspected metadata
        embedding_store.build_schema_embeddings(metadata)
        # Build value embeddings from database values
        embedding_store.build_value_embeddings(metadata, embedding_model, settings.value_cardinality_threshold)
    else:
        # Refresh what changed - only update rows that differ
        embedding_store.build_schema_embeddings(metadata)
        embedding_store.build_value_embeddings(metadata, embedding_model, settings.value_cardinality_threshold)

    # Create ValueIndex with embedding_store for value resolution
    value_index = ValueIndex(
        adapter=adapter,
        metadata=metadata,
        cardinality_threshold=settings.value_cardinality_threshold,
        embedder=embedding_model,
        storage_path=settings.vector_store_path,
        embedding_store=embedding_store,
    )
    value_index.build()
    _catalog_fingerprints.add(catalog_fingerprint)

    retriever = HybridSchemaRetriever(metadata, embedding_model, embedding_store=embedding_store)

    generator = GroqGenerator(settings.groq_api_key, settings.llm_model)
    examples = ExampleStore(settings.vector_store_path, adapter)
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

    # Store resources in runtime
    global _runtime
    _runtime = {
        "settings": settings,
        "adapter": adapter,
        "engine": adapter.engine,
        "metadata": metadata,
        "retriever": retriever,
        "embedding_store": embedding_store,
        "value_index": value_index,
        "examples": examples,
        "pipeline": pipeline,
        "indexed_tables": len(metadata.tables),
        "catalog_status": "cached" if schema_count > 0 or previously_indexed else "indexed",
    }
    LOGGER.info(
        "Application ready",
        extra={"dialect": adapter.get_dialect(), "indexed_tables": len(metadata.tables)},
    )
    return _runtime


def get_runtime() -> dict[str, Any]:
    """Return resources created by the most recent successful initialization."""
    if not _runtime:
        raise RuntimeError("Application startup has not completed.")
    return _runtime