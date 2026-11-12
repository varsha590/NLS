# Natural Language to SQL

## Current status

The dataset-backed workflow is available in Streamlit: register a dataset, ask a question, validate the generated SQL locally, then execute it read-only against a database connection. Dataset registration accepts `.sql` schema dumps and SQLite `.db` uploads. SQL files are parsed, never executed; SQLite uploads are inspected read-only. A `.sql` upload provides schema metadata but does not create a live database, so query execution still needs a separate read-only connection.

For `.sql` files, the current parser extracts `CREATE TABLE`, foreign-key `ALTER TABLE`, and literal multi-row `INSERT ... VALUES` statements. MySQL `INSERT IGNORE` and version comments are tolerated. PostgreSQL `COPY FROM stdin` blocks are skipped, not imported. Procedure, trigger, view, `DELIMITER`, `SET`, and `LOCK` statements are ignored. Low-cardinality literal insert values are persisted only after sensitive-name and PII-shape checks. SQLite `.db` files use read-only inspection plus bounded `SELECT DISTINCT` scans (`LOW_CARDINALITY_MAX + 1` maximum rows per eligible text column); high-cardinality, key, sensitive, and PII-shaped values are not stored.

Upload configuration: `TENANT_ID` (default tenant scope, not authentication), `DATASET_STORAGE_PATH` (default `datasets`), `MAX_UPLOAD_MB` (default 25), `SQL_PARSE_TIMEOUT_SECONDS` (default 10), and `LOW_CARDINALITY_MAX` (default 50). The SQL parser runs in a timed child process with a restricted environment that excludes database URLs, API keys, and other unapproved variables.

A Streamlit text-to-SQL application using SQLAlchemy, local sentence-transformer embeddings, Qdrant, Groq, and SQLGlot. Schema and value vectors and verified examples are stored in Qdrant; the target database is read-only.

## Configure a database

Use Python 3.10 or newer. Copy `.env.example` to `.env`, add `GROQ_API_KEY`, and install the SQLAlchemy driver matching the dialect. SQLite requires no external server:

At startup the application reads the Qdrant collection before schema inspection. It bulk-reflects metadata where supported and fingerprints each table. When fingerprints, settings, and refresh timestamps match, it loads the cached schema/value index without scanning data tables or calling the embedding model. Otherwise it scans only changed or stale tables, with one bounded query per eligible non-ENUM/SET column. It does not create, alter, seed, or write target database objects, and it collects no introspection samples. Schema vectors, VALUE_LOW value vectors, count-only classifications, and verified examples live in Qdrant, scoped per tenant and dataset.

Qdrant uses cosine search over the embedding model's vectors (384 dimensions for the default model). Every read and write carries a mandatory `tenant_id` + `dataset_id` filter, so one tenant can never read another tenant's points. The manifest tracks model/dimension/policy compatibility, global and per-table schema fingerprints, and `last_value_scan_at` timestamps. The classification cache stores class/reason and counts only. Unchanged content reuses cached embeddings; model/dimension changes re-embed from valid local metadata without value rescans. Only VALUE_LOW canonical values are stored in the value index; BLOCKED, MASKED, and VALUE_HIGH values are not embedded or persisted. Failed table scans preserve that table's last-known-good entries and surface an incomplete index state.

`INDEX_REFRESH_TTL_HOURS` defaults to 24; set it to `0` to rescan eligible values at every startup. `INDEX_SCAN_WORKERS` defaults to 1 and is capped at 8. `EMBED_CACHE_MAX_ENTRIES` defaults to 250000. Use **Re-index dataset** in the sidebar to force a full rebuild that ignores the refresh window. Verified examples and hints are retained. To reset a namespace completely, stop the app and delete its dataset directory under `datasets/`.

`EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `EXAMPLE_CANDIDATE_LIMIT`, `INDEX_REFRESH_TTL_HOURS`, `INDEX_SCAN_WORKERS`, `EMBED_CACHE_MAX_ENTRIES`, `QUERY_TIMEOUT_SECONDS`, and `MAX_RETRIES` configure indexing, retrieval, and execution. `EXAMPLE_CANDIDATE_LIMIT` defaults to 500 most recently saved examples before lexical ranking. `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` are optional comma-separated lists.

The sidebar shows index age and per-stage status; each query's **Run details** includes the same counts and timings. These diagnostics contain metadata and aggregates only, never row values.

## Security boundary

**Credentials must be supplied at runtime** via the connection form. Startup and query execution use only metadata reads, `SELECT`, `EXPLAIN`, and supported read-only or timeout session settings. Database permissions remain the authoritative boundary; application validation is an additional layer. Credentials are excluded from local namespaces and masked in displayed URLs.

The result set is held in memory for paging very large results use a lot of memory. Keep PAGE_SIZE small (default 50, max 500) to avoid excessive memory usage.

The application no longer provisions or uses PostgreSQL vector tables. If an older PostgreSQL database still contains application-created `system_*` tables, review and drop them manually with an administrator after confirming they are no longer needed. The app does not drop them.

## Hints and examples

Optional dataset-specific guidance can be placed at `.vector_store/<namespace>/hints.md`. Keep hints free of row data and credentials. After reviewing a successful query, **This was correct** saves the question and SQL to the namespace's local `examples.sqlite`; the UI reports failure if persistence fails.

Table comments are read as schema metadata. `catalog.describe.describe_catalog` and `db/init_db.py` are developer utilities; application startup does not import or run them. The legacy `CatalogStore` is used only by the optional description utility and is not the application index store.

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
streamlit run app.py
```

The SQLite pipeline tests use a mocked LLM. Optional MySQL read-only integration tests use `NLS_READONLY_MYSQL_URL` and skip when the SELECT-only database is unavailable.

## Remaining limitations

- `TENANT_ID` and dataset IDs are scopes, not authentication. Anyone who can run the app can select another tenant or dataset visible to it.
- A `.sql` upload provides schema and reference-value metadata only; it is not a live database and cannot execute queries.
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