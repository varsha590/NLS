"""Streamlit interface for the database-agnostic text-to-SQL pipeline."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from core.startup import init_app

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
    st.sidebar.caption(f"Schema index: {runtime['catalog_status']}")
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

    if result.get("rows"):
        st.dataframe(result["rows"], alt="Query result rows")
    elif result.get("sql") and not result.get("errors"):
        st.info("No rows matched the question.")
    for error in result.get("errors", []):
        if "No matching value found" in error or "Ambiguous value" in error:
            continue
        st.error(error)

    if result.get("sql"):
        if st.button("This was correct", icon=":material/thumb_up:", key="save-example"):
            runtime["examples"].save(question, result["sql"])
            st.success("Saved as a verified example for this database.")
    if result.get("timings"):
        with st.expander("Run details"):
            st.write(f"Tables used: {', '.join(result.get('tables_used', [])) or 'None'}")
            st.write(f"Retries: {result.get('retries', 0)}")
            st.json(result["timings"])


def main() -> None:
    """Render the question interface and process submitted queries."""
    try:
        force = st.session_state.pop("force_reindex", False)
        with st.spinner("Setting up database connection, embedding model, and schema index..."):
            runtime = load_runtime(force=force)
    except Exception as error:
        LOGGER.exception("Application startup failed")
        st.error(f"Startup failed: {error}", title="Setup error")
        if st.button("Retry setup", icon=":material/refresh:", key="retry-setup"):
            load_runtime.clear()
            st.rerun()
        return

    _render_sidebar(runtime)
    st.title("Natural Language to SQL")
    st.caption("Ask a question about the connected database.")

    with st.form("question-form"):
        question = st.text_input(
            "Question",
            placeholder="Ask a question about your data...",
            type="search",
            key="question_input",
        )
        submitted = st.form_submit_button("Search", type="primary")

    if submitted:
        normalized_question = question.strip()
        if not normalized_question:
            st.warning("Enter a question before searching.")
        else:
            # Clear skipped mentions if question changed
            if st.session_state.get("last_question", "") != normalized_question:
                st.session_state.skipped_mentions = set()
            with st.spinner("Retrieving schema and running a read-only query..."):
                confirmed = []
                for sm in st.session_state.get("skipped_mentions", set()):
                    confirmed.append({"mention": sm, "skip": True})
                if confirmed:
                    result = runtime["pipeline"].run(normalized_question, confirmed_values=confirmed).to_dict()
                else:
                    result = runtime["pipeline"].run(normalized_question).to_dict()
            st.session_state.last_question = normalized_question
            st.session_state.last_result = result

    last_result = st.session_state.get("last_result")
    last_question = st.session_state.get("last_question", "")
    if last_result:
        _render_result(last_result, last_question, runtime)