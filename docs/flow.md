# Client Flow

1. The client enters a tenant label and uploads a `.sql` file. The app parses and stores its schema and eligible reference values locally, then indexes the dataset for retrieval. Registered datasets persist, so returning clients select an existing dataset instead of uploading again.
2. The client submits a question in the search field.
3. The app retrieves dataset-scoped schema and value context, sends only that context and the question to the configured language model, generates SQL, and validates the SQL locally against the stored schema.
4. Only validated SQL is shown, inside the collapsed **Show query** expander. It is rendered before any database connection fields.
5. Without an active connection, the app asks for host, port, username, password, and database, then checks the connection. A successful check stores credentials in the current Streamlit session and runs the pending query. A failed check clears stored credentials and shows a friendly message. With an active connection, a validated query runs directly. **Disconnect** deletes the session credentials and returns to the connection form.
6. Credentials have a `last_used` timestamp and expire after `DB_IDLE_TIMEOUT_SECONDS` of inactivity (default 1800 seconds). They are not written to `.env`, logs, prompts, dataset storage, or vector storage. Query logs replace SQL literals with placeholders; SQL is omitted if safe masking fails.
7. Execution is read-only and bounded by `QUERY_TIMEOUT_SECONDS` (default 15). SQLite files open with URI `mode=ro` and query-only protection; MySQL uses `MAX_EXECUTION_TIME` and a read-only transaction; PostgreSQL uses a read-only transaction and `statement_timeout`.
8. The app fetches the complete result set once, keeps result rows in session state, and paginates those rows in the UI using `PAGE_SIZE` (default 50, maximum 500). An empty result displays **No matching records found**.

The UI keeps dialect, model, counts, timeout settings, and outcome details inside the collapsed **Advanced** section. Technical exceptions and stack traces are not shown to clients. Tests mock retrieval, generation, connection checks, and execution as appropriate; they do not call the hosted language model.
