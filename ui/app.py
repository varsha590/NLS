"""Streamlit interface for the database-agnostic text-to-SQL pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from core.startup import init_app
from ingestion.datasets import DatasetRegistry, UploadError
from retrieval.dataset_indexer import index_registered_dataset
from retrieval.embeddings import EmbeddingModel
from retrieval.qdrant_store import QdrantStorageError, QdrantVectorStore
from schema.metadata import SchemaMetadata, TableInfo, ColumnInfo

LOGGER = logging.getLogger(__name__)

st.set_page_config(
    page_title="Natural Language to SQL ",
    page_icon=":material/search:",
    layout="wide",
)


@st.cache_resource
def load_runtime(force: bool = False) -> dict[str, Any]:
    """Cache the shared engine, local indexes, and pipeline for this app process."""
    return init_app(force=force)


def _render_sidebar(runtime: dict[str, Any]) -> None:
    """Show live connection status and schema re-index control."""
    st.sidebar.title("Configuration")
    st.sidebar.metric("Connected dialect", runtime["adapter"].get_dialect())
    st.sidebar.metric("Tables indexed", runtime["indexed_tables"])
    catalog_status = runtime.get("catalog_status", "unknown")
    st.sidebar.caption(f"Schema index: {catalog_status}")
    stale_overrides = runtime.get("stale_overrides", [])
    if stale_overrides:
        st.sidebar.warning(
            "STALE OVERRIDES: " + ", ".join(stale_overrides),
            icon=":material/warning:",
        )
    for warning in runtime.get("override_warnings", []):
        st.sidebar.warning(warning, icon=":material/warning:")
    index_metrics = runtime.get("index_metrics", {})
    index_age = float(index_metrics.get("index_age_seconds", 0.0))
    st.sidebar.caption(f"Index age: {index_age / 3600:.1f} hours")
    with st.sidebar.expander("Index stages"):
        for stage_name, stage in index_metrics.get("stages", {}).items():
            details = [
                f"{name.replace('_', ' ')}: {value:.3f}s"
                if name.endswith("seconds")
                else f"{name.replace('_', ' ')}: {value}"
                for name, value in stage.items()
                if name != "status"
            ]
            st.caption(
                f"{stage_name.title()}: {stage.get('status', 'unknown')}"
                + (f" | {', '.join(details)}" if details else "")
            )
    if not runtime.get("index_complete", True):
        incomplete_tables = runtime.get("incomplete_tables", {})
        table_names = ", ".join(sorted(incomplete_tables))
        categories = ", ".join(sorted(set(incomplete_tables.values())))
        st.sidebar.warning(
            "Index incomplete. "
            + (f"Tables: {table_names}. " if table_names else "")
            + (f"Error categories: {categories}. " if categories else "")
            + "Re-index to retry.",
            icon="⚠️",
        )
    if st.sidebar.button("Re-index schema", icon=":material/refresh:"):
        load_runtime.clear()
        st.session_state.force_reindex = True
        st.session_state.skipped_mentions = set()
        st.session_state.last_result = None
        st.session_state.last_question = ""
        st.rerun()


def _render_result(result: dict[str, Any], question: str, runtime: dict[str, Any]) -> None:
    """Render answer, confirmations, SQL, and query rows."""
    if result.get("answer"):
        st.subheader("Answer")
        st.write(result["answer"])

    resolved_values = result.get("resolved_values", [])
    # Show auto-resolved interpretations above the answer
    for item in resolved_values:
        mention = item.get("mention", "")
        value = item.get("value", "")
        if mention.casefold() != value.casefold():
            st.info(f"Interpreted '{mention}' as '{value}'")

    # not_found is already conveyed by the answer; no separate info box needed

    ambiguous_values = result.get("ambiguous_values", [])
    if ambiguous_values:
        ambiguous = ambiguous_values[0]
        candidates = ambiguous.get("candidates", [])
        if len(candidates) > 1:
            st.warning(f"Confirm the value for {ambiguous['mention']!r}.")
            choices = list(range(len(candidates))) + [None]
            selected = st.radio(
                "Choose a matching value",
                choices,
                format_func=lambda choice: (
                    "None of these" if choice is None
                    else f"{candidates[choice]['value']} ({candidates[choice]['column']})"
                ),
                key=f"candidate-{ambiguous['mention']}",
            )
            if st.button("Use this", key=f"confirm-{ambiguous['mention']}"):
                if selected is None:
                    # Store skipped mention in session_state
                    skipped = st.session_state.setdefault("skipped_mentions", set())
                    skipped.add(ambiguous["mention"].casefold())
                    st.session_state.skipped_mentions = skipped
                    confirmed = [{"mention": ambiguous["mention"], "skip": True}]
                else:
                    value = candidates[selected]
                    confirmed = [{
                        "mention": ambiguous["mention"],
                        "column": value["column"],
                        "value": value["value"],
                        "confidence": value["confidence"],
                    }]
                with st.spinner("Updating value confirmation..."):
                    # Pass any previously skipped mentions too
                    all_confirmed = list(confirmed)
                    for sm in st.session_state.get("skipped_mentions", set()):
                        if sm != ambiguous["mention"].casefold():
                            all_confirmed.append({"mention": sm, "skip": True})
                    updated = runtime["pipeline"].run(question, confirmed_values=all_confirmed).to_dict()
                st.session_state.last_result = updated
                st.rerun()
        elif len(candidates) == 1:
            # Single candidate - auto-use, no dropdown
            pass

    with st.expander("View SQL"):
        if result.get("sql"):
            st.code(result["sql"], language="sql")
        else:
            st.info("No SQL was generated.")

    if result.get("rows") is not None and result.get("sql") and not result.get("errors"):
        if result["rows"]:
            st.dataframe(result["rows"], alt="Query result rows")
        else:
            st.info("No rows matched the question.")
    elif result.get("sql") and not result.get("errors"):
        st.info("No rows matched the question.")
    for error in result.get("errors", []):
        if "No matching value found" in error or "Ambiguous value" in error:
            continue
        st.error(error)

    # Show "This was correct" only when SQL validated AND executed without errors (0e fix).
    sql_is_verified = (
        bool(result.get("sql"))
        and not result.get("errors")
        and result.get("rows") is not None
    )
    if sql_is_verified:
        if st.button("This was correct", icon=":material/thumb_up:", key="save-example"):
            saved = runtime["examples"].save(question, result["sql"])
            if saved:
                st.success("Saved as a verified example for this database.")
            else:
                st.warning("Could not persist the example (storage unavailable).")
    if result.get("timings"):
        with st.expander("Run details"):
            st.write(f"Tables used: {', '.join(result.get('tables_used', [])) or 'None'}")
            st.write(f"Retries: {result.get('retries', 0)}")
            st.write("Operation counts")
            st.json(result.get("call_counts", {}))
            if result.get("run_details"):
                st.write(result["run_details"])
            st.json(result["timings"])
            index_metrics = runtime.get("index_metrics", {})
            st.write(
                f"Index path: {index_metrics.get('path', 'unknown')} | "
                f"Age: {float(index_metrics.get('index_age_seconds', 0.0)) / 3600:.1f} hours"
            )
            st.json(index_metrics.get("stages", {}))


def _get_value_documents(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract value documents from the runtime's value index."""
    value_documents: list[dict[str, Any]] = []
    try:
        local_store = runtime.get("local_store")
        if local_store is not None:
            value_records = getattr(local_store, "value_records", [])
            for vr in value_records:
                value_documents.append({
                    "table_name": vr.get("table_name", ""),
                    "column_name": vr.get("column", ""),
                    "value": vr.get("mention", ""),
                    "content": vr.get("content", ""),
                })
    except Exception:
        pass
    return value_documents


# ---- Question section ----

@st.cache_resource
def get_embedding_model(model_name: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")):
    """Cache the embedding model (same one used for indexing)."""
    from retrieval.embeddings import EmbeddingModel
    return EmbeddingModel(model_name)


def build_qdrant_store(runtime: dict[str, Any]) -> QdrantVectorStore:
    """Build Qdrant store reusing the existing setup."""
    from retrieval.qdrant_store import QdrantVectorStore
    return QdrantVectorStore(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        collection_name=os.getenv("QDRANT_COLLECTION", "nls_documents"),
    )


def main() -> None:
    """Register a dataset and inspect its stored schema without DB connections."""
    load_dotenv(override=False)
    st.title("Natural Language to SQL")
    st.subheader("Register a dataset")
    st.caption(
        "A .sql upload provides schema metadata and optional master values; it does not create a live database. "
        "Execution will require a separate database connection."
    )
    st.info(
        "Dataset registration is available now. Question generation and execution are available."
    )

    # Tenant IDs currently scope local data only; they are not user authentication.
    # tenant_id is an unauthenticated label; real authentication is a remaining limitation.
    st.text_input("Tenant ID", key="tenant_id", help="Use the same ID each time to find your datasets.")
    st.session_state.setdefault("tenant_id", os.getenv("TENANT_ID", "default"))
    tenant_id = st.session_state.tenant_id
    registry = DatasetRegistry(os.getenv("DATASET_STORAGE_PATH", "datasets"))
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "200"))

    with st.form("dataset-upload"):
        uploaded_file = st.file_uploader("SQL dump or SQLite database", type=["sql", "db"])
        dialect_choice = st.selectbox(
            "SQL dialect",
            ["Auto-detect", "SQLite", "MySQL", "PostgreSQL"],
        )
        submitted = st.form_submit_button("Register dataset", type="primary")

    if submitted:
        if uploaded_file is None:
            st.warning("Choose a .sql or .db file first.")
        elif not tenant_id.strip():
            st.warning("Enter a tenant ID.")
        else:
            override = None if dialect_choice == "Auto-detect" else dialect_choice.casefold()
            try:
                result = registry.register(
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    tenant_id=tenant_id.strip(),
                    dialect_override=override,
                    embedding_model_name=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                )
                st.session_state["selected_dataset_id"] = result["dataset_id"]
                for warning in result.get("warnings", []):
                    st.warning(warning)
                if result["status"] == "unchanged":
                    st.success("Dataset and Qdrant index are unchanged.")
                else:
                    try:
                        embedding_model = EmbeddingModel(
                            os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
                        )
                        qdrant_store = QdrantVectorStore(
                            url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
                            api_key=os.getenv("QDRANT_API_KEY") or None,
                            collection_name=os.getenv("QDRANT_COLLECTION", "nls_documents"),
                        )
                        try:
                            from retrieval.dataset_indexer import index_registered_dataset
                            document_count = index_registered_dataset(
                                registry,
                                qdrant_store,
                                tenant_id.strip(),
                                result["dataset_id"],
                                result["dataset_hash"],
                                embedding_model,
                            )
                        finally:
                            qdrant_store.close()
                        st.success(f"Dataset indexed: {document_count} documents.")
                    except QdrantStorageError as error:
                        st.error(str(error), title="Dataset not indexed")
                    except ValueError as error:
                        st.error(f"Embedding configuration is invalid: {error}", title="Dataset not indexed")
                    except (OSError, RuntimeError, TypeError):
                        st.error(
                            "Dataset registration succeeded, but embedding or indexing failed. "
                            "The dataset remains unindexed.",
                            title="Dataset not indexed",
                        )
            except UploadError as error:
                st.error(str(error), title="Upload rejected")

    st.caption(f"Maximum upload size: {max_upload_mb} MB")
    datasets = registry.list_datasets(tenant_id.strip()) if tenant_id.strip() else []
    if not datasets:
        st.info("No datasets are registered for this tenant yet.")
        st.stop()

    dataset_ids = [item["dataset_id"] for item in datasets]
    selected_id = st.selectbox(
        "Registered dataset",
        dataset_ids,
        index=(
            dataset_ids.index(st.session_state["selected_dataset_id"])
            if st.session_state.get("selected_dataset_id") in dataset_ids
            else 0
        ),
        format_func=lambda value: next(
            f"{item['filename']} ({item['dialect']})"
            for item in datasets
            if item["dataset_id"] == value
        ),
    )
    selected = next(item for item in datasets if item["dataset_id"] == selected_id)
    schema = registry.load_schema(tenant_id.strip(), selected_id)
    st.write(
        f"{selected['table_count']} tables | {selected['value_document_count']} master values | "
        f"Dialect: {schema.dialect}"
    )
    st.dataframe(
        [
            {
                "Table": table.name,
                "Columns": len(table.columns),
                "Relationships": len(table.foreign_keys),
            }
            for table in schema.tables.values()
        ],
        alt="Registered dataset schema summary",
    )

    # ---- Question section ----
    st.markdown("---")
    st.subheader("Ask a question")
    st.caption(f"Dataset: {selected['filename']} ({selected['dialect']})")

    # Cache the embedding model (same one used for indexing)
    embedder = get_embedding_model()

    # Build Qdrant store reusing existing setup
    qdrant_store = build_qdrant_store(st.session_state)

    # Get value documents from the value index
    value_documents = _get_value_documents(st.session_state)

    # Tenant ID from session state
    tenant_id = st.session_state.get("tenant_id", os.getenv("TENANT_ID", "default"))
    dataset_id = selected["dataset_id"]

    # Question form
    with st.form("question-form"):
        question = st.text_input("Enter your question")
        submitted = st.form_submit_button("Ask", type="primary")

        with st.expander("Advanced options"):
            st.caption(f"Outcome: {st.session_state.get('last_outcome', '—')}")
            st.caption(f"Dialect: {schema.dialect}")
            st.caption(f"Tables: {len(schema.tables)}")
            st.caption(f"Master values: {len(value_documents)}")
            st.caption(f"Embedder: {embedder.model_name}")
            st.caption(f"Dimension: {embedder.dim}")

    if submitted and question.strip():
        from ask import ask_question

        with st.spinner("Processing question..."):
            try:
                outcome, message = ask_question(
                    question,
                    schema,
                    value_documents,
                    embedder,
                    qdrant_store,
                    tenant_id,
                    dataset_id,
                    str(st.session_state.get("vector_store_path", "datasets")),
                )
                # Render the outcome message
                if outcome == "validated":
                    st.success(message)
                elif outcome == "unqueryable":
                    st.error(message)
                elif outcome == "retrieval_failed":
                    st.warning(message)
                elif outcome == "empty_question":
                    st.info(message)
                elif outcome == "too_long_question":
                    st.error(message)
                elif outcome == "re_index":
                    st.warning(message)
                elif outcome == "validator_failure":
                    st.info(message)
                elif outcome == "qdrant_failure":
                    st.error(message)
                elif outcome == "fallback":
                    st.info(message)

                # Show the outcome tag for debugging (moved to Advanced options in expander)
                st.session_state["last_outcome"] = outcome

            except Exception as error:
                LOGGER.warning("Question processing failed: %s", type(error).__name__)
                st.error("An unexpected error occurred. Please try again.")
    elif submitted and not question.strip():
        st.info("Please enter a question.")


if __name__ == "__main__":
    main()
