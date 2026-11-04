"""Streamlit interface for the database-agnostic text-to-SQL pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any

import streamlit as st

from core.startup import init_app
from ingestion.datasets import DatasetRegistry, UploadError

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


def main() -> None:
    """Register a dataset and inspect its stored schema without DB connections."""
    st.title("Natural Language to SQL")
    st.subheader("Register a dataset")
    st.caption(
        "A .sql upload provides schema metadata and optional master values; it does not create a live database. "
        "Execution will require a separate database connection."
    )

    # Tenant IDs currently scope local data only; they are not user authentication.
    st.session_state.setdefault("tenant_id", os.getenv("TENANT_ID", "default"))
    tenant_id = st.text_input("Tenant ID", key="tenant_id")
    registry = DatasetRegistry(os.getenv("DATASET_STORAGE_PATH", "datasets"))
    max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "25"))

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
                )
                st.session_state["selected_dataset_id"] = result["dataset_id"]
                message = (
                    "Dataset is unchanged; existing schema and values were kept."
                    if result["status"] == "unchanged"
                    else "Dataset schema registered."
                )
                st.success(message)
                for warning in result.get("warnings", []):
                    st.warning(warning)
            except UploadError as error:
                st.error(str(error), title="Upload rejected")

    st.caption(f"Maximum upload size: {max_upload_mb} MB")
    datasets = registry.list_datasets(tenant_id.strip()) if tenant_id.strip() else []
    if not datasets:
        st.info("No datasets are registered for this tenant yet.")
        return

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