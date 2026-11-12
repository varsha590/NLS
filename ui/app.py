"""Streamlit interface for the database-agnostic text-to-SQL pipeline."""

from __future__ import annotations

import logging
import os
import re
import time
import traceback
from dataclasses import replace
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
from retrieval.dataset_indexer import index_registered_dataset
from retrieval.embeddings import EmbeddingModel
from retrieval.qdrant_store import QdrantVectorStore
from config.settings import Settings
from pipeline.query_workflow import (
    QueryReady,
    ValidatedQuery,
    generate_and_validate_query,
    prepare_query,
)
from ui.state import (
    ASK_VALIDATED,
    DATASET_CHANGED,
    NEW_ASK,
    PAGE_NEXT,
    PAGE_PREV,
    SUBMIT_FAIL,
    SUBMIT_OK,
    next_ui_state,
)
from db.credentials import _scrub_credentials

LOGGER = logging.getLogger(__name__)

st.set_page_config(
    page_title="Natural Language to SQL ",
    page_icon=":material/search:",
    layout="wide",
)


def _safe_exception_chain(error: BaseException) -> str:
    api_key = os.getenv("QDRANT_API_KEY", "")

    def scrub_exception(current: BaseException | None, seen: set[int]) -> None:
        if current is None or id(current) in seen:
            return
        seen.add(id(current))
        message = _scrub_credentials(str(current))
        if api_key:
            message = message.replace(api_key, "***")
        message = re.sub(
            r"(?i)(?:['\"]?api[-_]key['\"]?\s*[:=]\s*)(?:'[^']*'|\"[^\"]*\"|[^,}\]\s]+)",
            "[redacted header]",
            message,
        )
        message = re.sub(r"(?i)api[-_]key", "[redacted header]", message)
        current.args = (message,)
        scrub_exception(current.__cause__, seen)
        scrub_exception(current.__context__, seen)

    scrub_exception(error, set())
    chain = "".join(
        traceback.format_exception(
            type(error), error, error.__traceback__, chain=True
        )
    )
    safe = _scrub_credentials(chain)
    if api_key:
        safe = safe.replace(api_key, "***")
    safe = re.sub(
        r"(?i)(?:['\"]?api[-_]key['\"]?\s*[:=]\s*)(?:'[^']*'|\"[^\"]*\"|[^,}\]\s]+)",
        "[redacted header]",
        safe,
    )
    return re.sub(r"(?i)api[-_]key", "[redacted header]", safe)


@st.cache_resource
def get_embedding_model(model_name: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")):
    """Cache the embedding model (same one used for indexing)."""
    return EmbeddingModel(model_name)


@st.cache_resource
def _cached_qdrant_store(url: str, collection_name: str, tenant_id: str | None = None, dataset_id: str | None = None) -> QdrantVectorStore:
    settings = replace(
        Settings.from_env(),
        qdrant_url=url,
        qdrant_collection=collection_name,
    )
    store = QdrantVectorStore(settings=settings)
    if tenant_id and dataset_id:
        store.tenant_id = tenant_id
        store.dataset_id = dataset_id
    return store


def build_qdrant_store(tenant_id: str | None = None, dataset_id: str | None = None) -> QdrantVectorStore:
    """Build a Qdrant store optionally scoped by tenant_id and dataset_id."""
    settings = Settings.from_env()
    return _cached_qdrant_store(settings.qdrant_url, settings.qdrant_collection, tenant_id, dataset_id)


def _index_dataset(
    registry: DatasetRegistry,
    tenant_id: str,
    dataset: dict[str, Any],
) -> int:
    dataset_hash = dataset.get("dataset_hash") or dataset.get("file_sha256")
    if not isinstance(dataset_hash, str) or not dataset_hash:
        raise UploadError("Dataset metadata is missing its content hash.")
    return index_registered_dataset(
        registry,
        build_qdrant_store(tenant_id, str(dataset["dataset_id"])),
        tenant_id,
        str(dataset["dataset_id"]),
        dataset_hash,
        get_embedding_model(),
    )


def _initial_ui_state() -> dict[str, Any]:
    return {"pending": None, "result": None, "error": None, "previous_tenant_id": None}


def _execution_dialect(dialect: str) -> str:
    return "postgresql" if dialect.casefold() in {"postgres", "postgresql"} else dialect


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
            stored_dialect=_execution_dialect(pending["dialect"]),
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
    timeout_seconds = max(1, int(os.getenv("QUERY_TIMEOUT_SECONDS", "15")))
    page_size = min(500, max(1, int(os.getenv("PAGE_SIZE", "50"))))

    st.title("Natural Language to SQL")

    initial = _initial_ui_state()
    st.session_state.setdefault("ui_state", initial)
    ui_state = st.session_state["ui_state"]

    tenant_id = st.text_input(
        "Tenant label",
        key="tenant_id",
        label_visibility="collapsed",
        disabled=ui_state.get("pending") is not None,
    )

    # Nothing shown by default: only the tenant label input.
    if not tenant_id or not tenant_id.strip():
        st.info("Enter a tenant label to continue.")
        return

    tenant_id = tenant_id.strip()
    if len(tenant_id) > 64:
        st.warning("Tenant label must be at most 64 characters.")
        return

    # Tenant change resets every tenant/dataset-scoped piece of session state.
    if st.session_state.get("previous_tenant_id") != tenant_id:
        st.session_state["previous_tenant_id"] = tenant_id
        st.session_state["selected_dataset_id"] = None
        st.session_state["active_dataset_id"] = None
        st.session_state["last_sql"] = None
        st.session_state["last_outcome"] = None
        st.session_state["db_creds"] = None
        st.session_state["ui_state"] = next_ui_state(ui_state, DATASET_CHANGED)

    registry = DatasetRegistry(os.getenv("DATASET_STORAGE_PATH", "datasets"))

    datasets = registry.list_datasets(tenant_id)
    if not datasets:
        st.info("No datasets yet, upload a .sql")
        with st.form("dataset-upload"):
            uploaded_file = st.file_uploader("Upload a .sql file", type=["sql"])
            register = st.form_submit_button("Register dataset", type="primary")
        if register:
            if uploaded_file is None:
                st.warning("Choose a .sql file first.")
            else:
                try:
                    result = registry.register(
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        tenant_id=tenant_id,
                        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "200")),
                        embedding_model_name=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
                    )
                    st.session_state["selected_dataset_id"] = result["dataset_id"]
                    if result.get("indexed") is not True:
                        try:
                            _index_dataset(registry, tenant_id, result)
                        except Exception as error:
                            LOGGER.exception("Dataset indexing failed: %s", type(error).__name__)
                            st.warning("Indexing failed, please retry")
                        else:
                            st.success("Dataset registered.")
                    else:
                        st.success("Dataset is already searchable.")
                except UploadError as error:
                    st.error(str(error))
                except Exception as error:
                    LOGGER.warning("Dataset registration failed: %s", type(error).__name__)
                    st.error("The dataset could not be registered. Please try again.")
        return

    # Datasets found: picker lists only this tenant's datasets.
    dataset_ids = [item["dataset_id"] for item in datasets]
    current_selection = st.session_state.get("selected_dataset_id")
    default_index = (
        dataset_ids.index(current_selection) if current_selection in dataset_ids else 0
    )
    selected_id = st.selectbox(
        "Dataset",
        dataset_ids,
        index=default_index,
        format_func=lambda value: next(
            (item.get("filename") or value for item in datasets if item["dataset_id"] == value),
            value,
        ),
    )

    if st.session_state.get("active_dataset_id") not in (None, selected_id):
        st.session_state["ui_state"] = next_ui_state(
            st.session_state["ui_state"], DATASET_CHANGED
        )
        st.session_state.pop("last_sql", None)
    st.session_state["active_dataset_id"] = selected_id
    st.session_state["selected_dataset_id"] = selected_id
    selected = next(item for item in datasets if item["dataset_id"] == selected_id)

    ui_state = st.session_state.get("ui_state") or _initial_ui_state()

    if selected.get("indexed") is not True:
        st.info("This dataset is still being prepared. Click Re-index.")
        if st.button("Re-index dataset", key="reindex-selected-dataset"):
            try:
                _index_dataset(registry, tenant_id, selected)
            except Exception as error:
                LOGGER.exception("Dataset re-indexing failed: %s", type(error).__name__)
                st.warning("Indexing failed, please retry")
            else:
                st.rerun()
        return

    try:
        metadata = registry.load_schema(tenant_id, selected_id)
        value_documents = registry.load_value_documents(tenant_id, selected_id)
    except UploadError:
        st.error("The selected dataset could not be loaded. Please select another dataset.")
        return

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
                qdrant_store = build_qdrant_store(tenant_id, selected_id)
                retrieval = prepare_query(
                    question=question,
                    metadata=metadata,
                    value_documents=value_documents,
                    embedder=embedder,
                    qdrant_store=qdrant_store,
                    tenant_id=tenant_id,
                    dataset_id=selected_id,
                    dataset_metadata_path=str(
                        registry.dataset_directory(tenant_id, selected_id) / "dataset.json"
                    ),
                    settings=Settings.from_env(),
                )
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
                                "tenant_id": tenant_id,
                                "dataset_id": selected_id,
                                "dialect": metadata.dialect,
                                "sql": validated.sql,
                                "question": question,
                            },
                        )
            except Exception as error:
                LOGGER.exception("Question processing failed: %s", type(error).__name__)
                st.session_state["last_outcome"] = "unavailable"
                st.info("I could not process that question right now. Please try again.")

    ui_state = st.session_state.get("ui_state") or _initial_ui_state()
    pending = ui_state.get("pending")

    # SQL preview + download render exactly once per run, before credentials.
    if pending is not None and pending.get("sql"):
        st.info("Your query is ready.")
        st.code(pending["sql"], language="sql")
        st.download_button(
            "Download SQL",
            data=pending["sql"],
            file_name="query.sql",
            mime="text/plain",
            key="download-query-sql",
        )

    if ui_state.get("error"):
        st.warning(ui_state["error"])

    stored = st.session_state.get("db_creds")
    if stored:
        st.success("Connected")
        if st.button("Disconnect", key="disconnect-db", icon=":material/link_off:"):
            st.session_state.pop("db_creds", None)
            st.session_state["connection_notice"] = "Disconnected. Connect again to run a query."
            st.rerun()
    elif pending is not None:
        notice = st.session_state.pop("connection_notice", None)
        if notice:
            st.info(notice)
        with st.expander(
            "Run this query on your database (optional)",
            expanded=False,
            key="query-execution-expander",
        ):
            with st.form("db-credentials-form"):
                host = st.text_input("Host", value="localhost", key="db-host")
                port = st.number_input(
                    "Port",
                    min_value=1,
                    value=(
                        3306 if metadata.dialect == "mysql"
                        else 5432 if metadata.dialect in {"postgres", "postgresql"}
                        else 1
                    ),
                    key="db-port",
                )
                username = st.text_input("Username", key="db-username")
                password = st.text_input("Password", type="password", key="db-password")
                database = st.text_input(
                    "Database",
                    help="For SQLite, enter the path to the read-only database file.",
                    key="db-database",
                )
                connect = st.form_submit_button("Connect", type="primary")
        if connect:
            dialect = _execution_dialect(metadata.dialect)
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

    if stored and pending is not None and ui_state.get("result") is None:
        with st.spinner("Running your query..."):
            _execute_pending_query(timeout_seconds)
        st.rerun()

    ui_state = st.session_state.get("ui_state") or _initial_ui_state()
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
                if st.button("Previous", key="page-prev", disabled=current_page <= 1):
                    st.session_state["ui_state"] = next_ui_state(
                        st.session_state["ui_state"], PAGE_PREV
                    )
                    st.rerun()
            with following:
                max_page = max(1, (len(rows) + page_size - 1) // page_size)
                if st.button("Next", key="page-next", disabled=current_page >= max_page):
                    st.session_state["ui_state"] = next_ui_state(
                        st.session_state["ui_state"], PAGE_NEXT, {"page_size": page_size}
                    )
                    st.rerun()


def main() -> None:
    _run_client_flow()


if __name__ == "__main__":
    main()
