# Natural Language to SQL

A Streamlit text-to-SQL app using local sentence-transformer embeddings, Qdrant, Groq, SQLGlot, and SQLAlchemy. The current flow is: register a `.sql` schema → select the dataset → connect once to the live database → ask a question → review the validated SQL → see executed results.

## Current client flow

1. **Enter a tenant label.** The label scopes local dataset files and Qdrant points. It is not authentication; tenant and dataset IDs are allowlisted to `A-Za-z0-9_-` with a 64-character maximum.
2. **Register a dataset.** If the tenant has no datasets, the app asks for a `.sql` upload. The file is parsed in a timed child process and is never executed. `CREATE TABLE`, foreign-key `ALTER TABLE`, and literal multi-row `INSERT ... VALUES` statements are extracted; low-cardinality literal values are persisted only after key-column, sensitive-name, and PII-shape checks. The resulting `schema.json`, `value_documents.json`, and `dataset.json` are stored under the tenant's dataset directory, then schema/column/relationship/value documents are embedded into tenant- and dataset-scoped Qdrant points.
3. **Select the dataset.** Returning clients pick an existing dataset by filename. Changing the tenant or dataset clears the DB connection and any pending question/result state. If a dataset is not indexed, the app shows **Re-index dataset**; a failed re-index leaves it unindexed so it can be retried.
4. **Connect once per session.** After the dataset metadata loads, a form asks for Host, Port, Username, Password, and Database. For SQLite, only the Database path is used and it is opened read-only; the other fields are ignored. The app rejects a dialect that does not match the uploaded `.sql` and verifies access with a read-only `SELECT 1`. On success it shows `Connected to <host>/<db>` and enables the question box. Credentials are held only in `st.session_state` as a `DbCredentials` object (password masked in `str`/`repr`), expire after `DB_IDLE_TIMEOUT_SECONDS` of inactivity (default 1800), and are cleared by **Disconnect**, tenant change, or dataset change.
5. **Ask a question.** The app embeds the question, matches registered low-cardinality values, retrieves tenant/dataset-scoped schema context from Qdrant, and may ask the client to clarify the table when matches are ambiguous. Only the question and local schema context are sent to Groq; credentials and query result rows are never sent. Generated SQL is validated locally with SQLGlot against the stored `schema.json`: one read-only `SELECT`, no live database inspection, and no `EXPLAIN`. One retry with sanitized feedback is allowed after a validation failure.
6. **Review and execute.** Validated SQL appears once in the collapsed **Show query** expander with a **Download SQL** button. It then executes automatically against the session connection with read-only settings; the connection is closed afterward. Rows are fetched once and paginated with **Previous**/**Next** using `PAGE_SIZE` (default 50, maximum 500); an empty result shows **No matching records found**. The query log records tenant, dataset, row count, duration, and SQL with all literals replaced by `?`; it never records credentials or row data.

The Streamlit file uploader currently exposes `.sql` only. `DatasetRegistry.register()` also supports SQLite `.db` files programmatically via read-only inspection and bounded `SELECT DISTINCT` scans, but the UI does not offer that path.

## Configure the app

Use Python 3.10 or newer. Copy `.env.example` to `.env`, set `GROQ_API_KEY`, and install the SQLAlchemy driver matching the dialect. SQLite needs no external server. `Settings.from_env()` also requires `LLM_MODEL`, `EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `QUERY_TIMEOUT_SECONDS`, and `MAX_RETRIES`; the example file supplies all of them.

- Upload: `DATASET_STORAGE_PATH` (default `datasets`), `MAX_UPLOAD_MB` (code default 200 MB; `.env.example` sets 500), `SQL_PARSE_TIMEOUT_SECONDS` (code default 10 seconds; `.env.example` sets 1000), `LOW_CARDINALITY_MAX` (default 50). `TENANT_ID` is only a programmatic fallback; the UI tenant label wins.
- Retrieval/index: `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, `EMBEDDING_MODEL` (384-dimensional sentence-transformer), `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `EXAMPLE_CANDIDATE_LIMIT` (default 500). Optional comma-separated lists: `ALLOWED_SCHEMAS`, `EXCLUDED_TABLES`.
- Execution/session: `QUERY_TIMEOUT_SECONDS` (default 15), `DB_IDLE_TIMEOUT_SECONDS` (default 1800), `PAGE_SIZE` (default 50, capped at 500).

The SQL parser runs with an allowlisted environment (`PATH`, locale settings, temp directories) so database URLs, API keys, and other secrets are not passed into the child process. MySQL `INSERT IGNORE` and version comments are tolerated. PostgreSQL `COPY FROM stdin` blocks are skipped, not imported. Procedure, trigger, view, `DELIMITER`, `SET`, and `LOCK` statements are ignored. Qdrant uses cosine search over the embedding model's 384-dimensional vectors; every read and write carries a mandatory `tenant_id` + `dataset_id` filter, so one tenant cannot read another tenant's points.

## Security boundary

Registration and validation never connect to the target database, run DDL, or execute uploaded SQL. There is no startup scan of the live database; schema and value context come from the registered dataset files. The application does not create, alter, seed, or write target database objects.

Credentials are supplied only at runtime through the connection form. They are never written to `.env`, files, logs, Qdrant, dataset storage, or prompts. The connection layer sets `SET TRANSACTION READ ONLY` plus `statement_timeout` for PostgreSQL, `MAX_EXECUTION_TIME` plus `SET TRANSACTION READ ONLY` for MySQL, and `mode=ro` plus `PRAGMA query_only=ON` for SQLite. Database permissions remain the authoritative boundary; application validation is an additional layer.

Result sets are fetched fully into memory for pagination, so very large results can consume significant memory. Keep `PAGE_SIZE` small.

The application does not provision or use PostgreSQL vector tables. If an older PostgreSQL database still contains application-created `system_*` tables, review and drop them manually with an administrator after confirming they are no longer needed. The app does not drop them.

## Install and run

```bash
python -m pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

Optional drivers are documented in `requirements.txt`. For example:

```bash
python -m pip install 'psycopg[binary]'  # PostgreSQL
python -m pip install pymysql             # MySQL
python -m pip install pyodbc              # SQL Server; also needs Microsoft's ODBC driver
```

## Tests

```bash
python -m pytest tests/ -v
```

Tests use a mocked LLM and do not call Groq. Optional MySQL read-only integration tests use `NLS_READONLY_MYSQL_URL` and skip when the SELECT-only database is unavailable.

## Remaining limitations

- Tenant labels and dataset IDs are scopes, not authentication. Anyone who can run the app can select another tenant or dataset visible to it.
- A `.sql` upload provides schema and reference-value metadata only; it is not a live database and cannot execute queries.
- The UI registers `.sql` files only; SQLite `.db` registration is available through `DatasetRegistry` API, not the UI.
- There is no live `EXPLAIN` or database-backed validation before execution; validation is against the uploaded schema only.
- Qdrant data and dataset files are stored locally; this is not a hosted multi-tenant deployment.
- PostgreSQL `COPY FROM stdin` data is skipped during upload, so reference values from that form are not indexed.
- Result sets are fetched fully into memory for pagination; very large results can consume significant memory.

## Read-only database role

Create a read-only role with grants appropriate to the schema. Run provisioning manually; the application never runs these statements.

```sql
-- Replace placeholders for your environment.
CREATE ROLE <read_only_role> LOGIN PASSWORD 'replace_me';
GRANT CONNECT ON DATABASE <database_name> TO <read_only_role>;
GRANT USAGE ON SCHEMA <schema_name> TO <read_only_role>;
GRANT SELECT ON ALL TABLES IN SCHEMA <schema_name> TO <read_only_role>;
```
