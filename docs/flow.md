# Client Flow

1. The client enters a tenant label and uploads a `.sql` file. The app parses and stores its schema and eligible reference values locally, then indexes the dataset for retrieval. Registered datasets persist, so returning clients select an existing dataset instead of uploading again.
2. After dataset selection, the client connects once per session with host, port, username, password, and database name. The app verifies read-only access with `SELECT 1` and rejects a dialect mismatch against the uploaded `.sql`. On success, the form collapses to **Connected to &lt;host&gt;/&lt;db&gt;** with a **Disconnect** button; the question box stays disabled until then.
3. The client submits a question in the search field. Validated SQL executes automatically against the session connection with no second credentials prompt.
4. The app retrieves dataset-scoped schema and value context, sends only that context and the question to the configured language model, generates SQL, and validates the SQL locally against the stored schema.
5. Validated SQL remains available only inside the collapsed **Show query** expander.
6. Credentials live only in `st.session_state` as a `DbCredentials` object (password masked in `str`/`repr`), expire after `DB_IDLE_TIMEOUT_SECONDS` of inactivity (default 1800 seconds), and are cleared on **Disconnect**, tenant change, and dataset change. They are not written to `.env`, files, logs, prompts, Qdrant, or dataset storage. Query logs replace SQL literals with placeholders; SQL is omitted if safe masking fails.
7. Execution is read-only and bounded by `QUERY_TIMEOUT_SECONDS` (default 15). SQLite files open with URI `mode=ro` and query-only protection; MySQL uses `MAX_EXECUTION_TIME` and a read-only transaction; PostgreSQL uses a read-only transaction and `statement_timeout`.
8. The app fetches the complete result set once, keeps result rows in session state, and paginates those rows in the UI using `PAGE_SIZE` (default 50, maximum 500). An empty result displays **No matching records found**.

The UI keeps dialect, model, counts, timeout settings, and outcome details inside the collapsed **Advanced** section. Technical exceptions and stack traces are not shown to clients. Tests mock retrieval, generation, connection checks, and execution as appropriate; they do not call the hosted language model.
