"""Streamlit interface for the database-agnostic text-to-SQL pipeline."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import streamlit as st

from db.credentials import (
    DbConnectionError,
    DbCredentials,
    execute_validated,
    log_query,
    page_rows,
    test_connection,
)
from ingestion.datasets import DatasetRegistry, UploadError
from retrieval.embeddings import EmbeddingModel
from retrieval.qdrant_store import QdrantStorageError, QdrantVectorStore
from pipeline.query_workflow import (
    QueryReady,
    ValidatedQuery,
    generate_and_validate_query,
    prepare_query,
)
from ui.state import (
    ASK_VALIDATED,
    ASK_OTHER,
    DATASET_CHANGED,
    NEW_ASK,
    PAGE_NEXT,
    PAGE_PREV,
    SUBMIT_FAIL,
    SUBMIT_OK,
    next_ui_state,
)

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


def _initial_ui_state() -> dict[str, Any]:
    return {"pending": None, "result": None, "error": None}


def _clear_expired_credentials() -> None:
    stored = st.session_state.get("db_creds")
    if not stored:
        return
    timeout = max(1, int(os.getenv("DB_IDLE_TIMEOUT_SECONDS", "1800")))
    now = time.time()
    if now - float(stored.get("last_used", now)) >= timeout:
        del st.session_state["db_creds"]
        st.session_state["connection_notice"] = "Your connection expired. Please connect again."
    elif now - float(stored.get("last_used", now)) >= 0:
        stored["last_used"] = now


def _execute_pending_query(timeout_seconds: int) -> None:
    state = st.session_state.get("ui_state") or _initial_ui_state()
    pending = state.get("pending")
    stored = st.session_state.get("db_creds")
    if pending is None or stored is None:
        return

    credentials = stored["credentials"]
    st.session_state["last_sql"] = pending["sql"]
    try:
        result = execute_validated(
            pending["sql"],
            credentials,
            stored_dialect=pending["dialect"],
            timeout_seconds=timeout_seconds,
        )
        log_query(
            tenant_id=pending["tenant_id"],
            dataset_id=pending["dataset_id"],
            sql=pending["sql"],
            row_count=result["row_count"],
            duration_ms=result["duration_ms"],
        )
        stored["last_used"] = time.time()
        st.session_state["ui_state"] = next_ui_state(
            state,
            SUBMIT_OK,
            {
                "columns": result["columns"],
                "rows": result["rows"],
                "row_count": result["row_count"],
                "duration_ms": result["duration_ms"],
            },
        )
    except Exception as error:
        LOGGER.warning("Query execution failed: %s", type(error).__name__)
        st.session_state.pop("db_creds", None)
        st.session_state["ui_state"] = next_ui_state(
            state,
            SUBMIT_FAIL,
            {"message": "The connection could not be used. Please connect again."},
        )


def _run_client_flow() -> None:
    _clear_expired_credentials()
    st.session_state.setdefault("tenant_id", os.getenv("TENANT_ID", "default"))
    st.session_state.setdefault("ui_state", _initial_ui_state())
    timeout_seconds = max(1, int(os.getenv("QUERY_TIMEOUT_SECONDS", "15")))
    page_size = min(500, max(1, int(os.getenv("PAGE_SIZE", "50"))))

    st.title("Natural Language to SQL")
    tenant_id = st.text_input("Tenant label", key="tenant_id")
    registry = DatasetRegistry(os.getenv("DATASET_STORAGE_PATH", "datasets"))

    with st.expander("Advanced"):
        dialect_choice = st.selectbox(
            "Dataset dialect override",
            ["Auto-detect", "SQLite", "MySQL", "PostgreSQL"],
        )
        st.caption(f"Embedding model: {os.getenv('EMBEDDING_MODEL', 'all-MiniLM-L6-v2')}")
        st.caption(f"Page size: {page_size}")
        st.caption(f"Query timeout: {timeout_seconds} seconds")
        st.caption(f"Last outcome: {st.session_state.get('last_outcome', '—')}")

    with st.form("dataset-upload"):
        uploaded_file = st.file_uploader("Upload a .sql file", type=["sql"])
        register = st.form_submit_button("Register dataset", type="primary")

    if register:
        if uploaded_file is None:
            st.warning("Choose a .sql file first.")
        elif not tenant_id.strip():
            st.warning("Enter a tenant label.")
        else:
            override = None if dialect_choice == "Auto-detect" else dialect_choice.casefold()
            try:
                result = registry.register(
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    tenant_id=tenant_id.strip(),
                    dialect_override=override,
                    max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "200")),
                    embedding_model_name=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                )
                st.session_state["selected_dataset_id"] = result["dataset_id"]
                try:
                    embedding_model = EmbeddingModel(
                        os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
                    )
                    qdrant_store = build_qdrant_store({})
                    try:
                        index_registered_dataset(
                            registry,
                            qdrant_store,
                            tenant_id.strip(),
                            result["dataset_id"],
                            result["dataset_hash"],
                            embedding_model,
                        )
                    finally:
                        qdrant_store.close()
                except Exception as error:
                    LOGGER.warning("Dataset indexing failed: %s", type(error).__name__)
                    st.warning("The dataset was saved but could not be made searchable yet.")
                else:
                    st.success("Dataset registered.")
            except UploadError:
                st.error("The file could not be registered. Check the file and try again.")
            except Exception as error:
                LOGGER.warning("Dataset registration failed: %s", type(error).__name__)
                st.error("The dataset could not be registered. Please try again.")

    if not tenant_id.strip():
        st.info("Enter your tenant label to view registered datasets.")
        return
    datasets = registry.list_datasets(tenant_id.strip())
    if not datasets:
        st.info("No datasets are registered yet.")
        return

    dataset_ids = [item["dataset_id"] for item in datasets]
    selected_id = st.selectbox(
        "Dataset",
        dataset_ids,
        index=(
            dataset_ids.index(st.session_state["selected_dataset_id"])
            if st.session_state.get("selected_dataset_id") in dataset_ids
            else 0
        ),
        format_func=lambda value: next(
            item["filename"] for item in datasets if item["dataset_id"] == value
        ),
    )
    if st.session_state.get("active_dataset_id") not in (None, selected_id):
        st.session_state["ui_state"] = next_ui_state(
            st.session_state["ui_state"], DATASET_CHANGED
        )
        st.session_state.pop("last_sql", None)
    st.session_state["active_dataset_id"] = selected_id
    st.session_state["selected_dataset_id"] = selected_id

    try:
        metadata = registry.load_schema(tenant_id.strip(), selected_id)
        value_documents = registry.load_value_documents(tenant_id.strip(), selected_id)
    except UploadError:
        st.error("The selected dataset could not be loaded. Please select another dataset.")
        return
    selected = next(item for item in datasets if item["dataset_id"] == selected_id)
    with st.expander("Advanced"):
        st.caption(f"Dialect: {metadata.dialect}")
        st.caption(f"Tables: {len(metadata.tables)}")
        st.caption(f"Master values: {len(value_documents)}")
        st.caption(f"Outcome: {st.session_state.get('last_outcome', '—')}")

    with st.form("question-form"):
        question = st.text_input(
            "Search", placeholder="Ask a question about your data", key="question_input"
        )
        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        st.session_state["ui_state"] = next_ui_state(
            st.session_state["ui_state"], NEW_ASK
        )
        st.session_state.pop("last_sql", None)
        if not question.strip():
            st.info("Enter a question to continue.")
        else:
            try:
                embedder = get_embedding_model()
                qdrant_store = build_qdrant_store({})
                try:
                    retrieval = prepare_query(
                        question=question,
                        metadata=metadata,
                        value_documents=value_documents,
                        embedder=embedder,
                        qdrant_store=qdrant_store,
                        tenant_id=tenant_id.strip(),
                        dataset_id=selected_id,
                        dataset_metadata_path=str(
                            registry.dataset_directory(tenant_id.strip(), selected_id)
                            / "dataset.json"
                        ),
                    )
                finally:
                    qdrant_store.close()
                if not isinstance(retrieval, QueryReady):
                    st.session_state["last_outcome"] = retrieval.status
                    st.info(retrieval.message)
                else:
                    validated = generate_and_validate_query(retrieval)
                    st.session_state["last_outcome"] = validated.status
                    if not isinstance(validated, ValidatedQuery):
                        st.info(validated.message)
                    else:
                        st.session_state["ui_state"] = next_ui_state(
                            st.session_state["ui_state"],
                            ASK_VALIDATED,
                            {
                                "tenant_id": tenant_id.strip(),
                                "dataset_id": selected_id,
                                "dialect": metadata.dialect,
                                "sql": validated.sql,
                                "question": question,
                            },
                        )
            except Exception as error:
                LOGGER.warning("Question processing failed: %s", type(error).__name__)
                st.session_state["last_outcome"] = "unavailable"
                st.info("I could not process that question right now. Please try again.")

    ui_state = st.session_state.get("ui_state") or _initial_ui_state()
    pending = ui_state.get("pending")
    sql_to_show = (pending or {}).get("sql") or st.session_state.get("last_sql")
    if sql_to_show:
        with st.expander("Show query", expanded=False):
            st.code(sql_to_show, language="sql")

    if ui_state.get("error"):
        st.warning(ui_state["error"])

    stored = st.session_state.get("db_creds")
    if stored:
        st.success("Connected")
        if st.button("Disconnect", icon=":material/link_off:"):
            st.session_state.pop("db_creds", None)
            st.session_state["connection_notice"] = "Disconnected. Connect again to run a query."
            st.rerun()
    elif pending is not None:
        notice = st.session_state.pop("connection_notice", None)
        if notice:
            st.info(notice)
        with st.form("db-credentials-form"):
            st.text_input("Host", value="localhost")
            st.number_input("Port", min_value=1, value=3306 if metadata.dialect == "mysql" else 5432)
            st.text_input("Username")
            st.text_input("Password", type="password")
            database = st.text_input(
                "Database", help="For SQLite, enter the path to the read-only database file."
            )
            connect = st.form_submit_button("Connect", type="primary")
        if connect:
            values = [widget.value for widget in st.session_state.values() if False]
            del values
            form_values = st.session_state
            host = next((value for key, value in form_values.items() if key.endswith("-Host")), "localhost")
            port = next((value for key, value in form_values.items() if key.endswith("-Port")), 1)
            username = next((value for key, value in form_values.items() if key.endswith("-Username")), "")
            password = next((value for key, value in form_values.items() if key.endswith("-Password")), "")
            dialect = "postgresql" if metadata.dialect == "postgres" else metadata.dialect
            credentials = DbCredentials(
                dialect=dialect,
                host="" if dialect == "sqlite" else host,
                port=None if dialect == "sqlite" else int(port),
                username="" if dialect == "sqlite" else username,
                password="" if dialect == "sqlite" else password,
                database=database,
            )
            try:
                test_connection(credentials, timeout_seconds)
                st.session_state["db_creds"] = {
                    "credentials": credentials,
                    "last_used": time.time(),
                }
                _execute_pending_query(timeout_seconds)
            except DbConnectionError:
                st.session_state.pop("db_creds", None)
                st.session_state["ui_state"] = next_ui_state(
                    ui_state,
                    SUBMIT_FAIL,
                    {"message": "The connection could not be verified. Check the details and try again."},
                )
            except Exception as error:
                LOGGER.warning("Connection verification failed: %s", type(error).__name__)
                st.session_state.pop("db_creds", None)
                st.session_state["ui_state"] = next_ui_state(
                    ui_state,
                    SUBMIT_FAIL,
                    {"message": "The connection could not be verified. Check the details and try again."},
                )
            st.rerun()

    if stored and pending is not None:
        with st.spinner("Running your query..."):
            _execute_pending_query(timeout_seconds)
        st.rerun()

    result = ui_state.get("result")
    if result is not None:
        rows = result["rows"]
        if not rows:
            st.info("No matching records found")
        else:
            current_page = int(result.get("page", 1))
            st.dataframe(page_rows(rows, current_page, page_size), alt="Matching records")
            previous, following = st.columns(2)
            with previous:
                if st.button("Previous", disabled=current_page <= 1):
                    st.session_state["ui_state"] = next_ui_state(
                        st.session_state["ui_state"], PAGE_PREV
                    )
                    st.rerun()
            with following:
                max_page = max(1, (len(rows) + page_size - 1) // page_size)
                if st.button("Next", disabled=current_page >= max_page):
                    st.session_state["ui_state"] = next_ui_state(
                        st.session_state["ui_state"], PAGE_NEXT, {"page_size": page_size}
                    )
                    st.rerun()


def main() -> None:
    _run_client_flow()


def _legacy_main() -> None:
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
        question = st.text_input("Enter your question", key="question_input")
        submitted = st.form_submit_button("Ask", type="primary")

        with st.expander("Advanced options"):
            st.caption(f"Outcome: {st.session_state.get('last_outcome', '—')}")
            st.caption(f"Dialect: {schema.dialect}")
            st.caption(f"Tables: {len(schema.tables)}")
            st.caption(f"Master values: {len(value_documents)}")
            st.caption(f"Embedder: {embedder.model_name}")
            st.caption(f"Dimension: {embedder.dim}")

    # ---- Ask handling ----
    ask_result: AskResult | None = None
    if submitted and question.strip():
        with st.spinner("Processing question..."):
            try:
                ask_result = ask_question(
                    question,
                    schema,
                    value_documents,
                    embedder,
                    qdrant_store,
                    tenant_id,
                    dataset_id,
                    str(st.session_state.get("vector_store_path", "datasets")),
                )
                if ask_result.outcome == "validated":
                    st.session_state.ui_state = next_ui_state(
                        st.session_state.get("ui_state"),
                        ASK_VALIDATED,
                        {
                            "tenant_id": tenant_id,
                            "dataset_id": dataset_id,
                            "dialect": ask_result.dialect or schema.dialect,
                            "sql": ask_result.sql,
                            "question": question,
                        },
                    )
                    st.success(ask_result.message)
                else:
                    st.session_state.ui_state = next_ui_state(
                        st.session_state.get("ui_state"), ASK_OTHER
                    )
                    _show_outcome_message(ask_result.outcome, ask_result.message)
                    st.session_state["last_outcome"] = ask_result.outcome
            except Exception as error:
                from db.credentials import _scrub_credentials

                LOGGER.exception("Question processing failed: %s", _scrub_credentials(str(error)))
                st.error("An unexpected error occurred. Please try again.")
    elif submitted and not question.strip():
        st.info("Please enter a question.")

    # ---- Render credentials form whenever pending exists (outside Ask branch) ----
    ui_state = st.session_state.get("ui_state") or _initial_ui_state()
    pending = ui_state.get("pending")
    if pending is not None:
        dialect = pending["dialect"]
        is_sqlite = dialect == "sqlite"
        default_port = 3306 if dialect == "mysql" else (5432 if dialect == "postgresql" else None)

        with st.form("db-credentials-form", clear_on_submit=True):
            st.caption(f"Dataset dialect: {dialect}")
            if is_sqlite:
                database = st.text_input("Database file path", value="", key="db_file_path")
                host = port = username = password = None
            else:
                c1, c2 = st.columns(2)
                with c1:
                    host = st.text_input("Host", value="localhost")
                    port = st.number_input("Port", value=default_port or 1, min_value=1)
                    username = st.text_input("Username", value="nls_ro")
                with c2:
                    password = st.text_input("Password", value="", type="password")
                    database = st.text_input("Database name", value="")
            submit = st.form_submit_button("Run query", type="primary")

        if submit:
            if is_sqlite:
                credentials = DbCredentials(
                    dialect=dialect,
                    host="",
                    port=None,
                    username="",
                    password="",
                    database=database,
                )
            else:
                credentials = DbCredentials(
                    dialect=dialect,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database=database,
                )
            try:
                result = execute_validated(
                    pending["sql"],
                    credentials,
                    stored_dialect=pending["dialect"],
                )
                log_query(
                    tenant_id=pending["tenant_id"],
                    dataset_id=pending["dataset_id"],
                    sql=pending["sql"],
                    row_count=result["row_count"],
                    duration_ms=result["duration_ms"],
                )
                st.session_state.ui_state = next_ui_state(
                    st.session_state.get("ui_state"),
                    SUBMIT_OK,
                    {
                        "columns": result["columns"],
                        "rows": result["rows"],
                        "row_count": result["row_count"],
                        "duration_ms": result["duration_ms"],
                    },
                )
            except DbConnectionError as e:
                st.session_state.ui_state = next_ui_state(
                    st.session_state.get("ui_state"),
                    SUBMIT_FAIL,
                    {"message": f"The query could not be run: {e}"},
                )
            except Exception as error:
                from db.credentials import _scrub_credentials

                st.session_state.ui_state = next_ui_state(
                    st.session_state.get("ui_state"),
                    SUBMIT_FAIL,
                    {"message": f"The query could not be run: {_scrub_credentials(str(error))}"},
                )
            st.rerun()

    # ---- Render results / errors from state ----
    result = ui_state.get("result")
    error = ui_state.get("error")
    if error:
        st.error(error)
    if result is not None:
        page_size = int(os.getenv("PAGE_SIZE", 50))
        page = int(result.get("page", 1))
        rows_shown = page_rows(result["rows"], page, page_size)
        st.success(f"Query returned {result['row_count']} row(s)")
        if rows_shown:
            st.dataframe(rows_shown, alt="Query result rows")
        else:
            st.info("No matching records found.")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Previous", disabled=page <= 1):
                st.session_state.ui_state = next_ui_state(
                    st.session_state.get("ui_state"), PAGE_PREV
                )
                st.rerun()
        with c2:
            st.caption(f"Page {page}")
        with c3:
            max_page = max(1, (result["row_count"] + page_size - 1) // page_size) if result["row_count"] > 0 else 1
            if st.button("Next", disabled=result["row_count"] <= page * page_size):
                st.session_state.ui_state = next_ui_state(
                    st.session_state.get("ui_state"), PAGE_NEXT, {"page_size": page_size}
                )
                st.rerun()
        with st.expander("Show query", expanded=False):
            if pending is not None and pending.get("sql"):
                st.code(pending["sql"], language="sql")
            else:
                st.info("No SQL was generated.")
    elif pending is not None and error is None:
        st.info("Enter credentials and click Run query to execute the validated SQL.")

    # ---- Dataset change clears pending/result ----
    prev_dataset = st.session_state.get("_prev_dataset_id")
    if prev_dataset is not None and prev_dataset != dataset_id:
        st.session_state.ui_state = next_ui_state(
            st.session_state.get("ui_state"), DATASET_CHANGED
        )
    st.session_state["_prev_dataset_id"] = dataset_id


def _show_outcome_message(outcome: str, message: str) -> None:
    """Render a non-validated outcome message."""
    if outcome == "unqueryable":
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


def _initial_ui_state() -> dict:
    return {"pending": None, "result": None, "error": None}


if __name__ == "__main__":
    main()
