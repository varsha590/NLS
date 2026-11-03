# Natural Language to SQL

A Streamlit text-to-SQL application using SQLAlchemy, local sentence-transformer embeddings, FAISS, Groq, and SQLGlot. Schema and value vectors and verified examples are stored in local namespace files; the target database is read-only.

## Configure a database

Use Python 3.10 or newer. Copy `.env.example` to `.env`, set `DATABASE_URL` to a read-only account, add `GROQ_API_KEY`, and install the SQLAlchemy driver matching the URL. SQLite requires no external server:

```env
DATABASE_URL=sqlite:///./example.db
```

At startup the application reads the local manifest before schema inspection. It bulk-reflects metadata where supported and fingerprints each table. When fingerprints, settings, local files, and refresh timestamps match, it loads the schema/value indexes and classification cache without scanning data tables or calling the embedding model. Otherwise it scans only changed or stale tables, with one bounded query per eligible non-ENUM/SET column. It does not create, alter, seed, or write target database objects, and it collects no introspection samples. Schema vectors, VALUE_LOW value vectors, count-only classifications, embedding cache, and verified examples live in `.vector_store/<namespace>/`, where the namespace is a hash of the credential-free database URL.

The store uses exact cosine search over L2-normalized float32 vectors. The embedding dimension is read from the selected model. The manifest tracks model/dimension/normalization/policy compatibility, global and per-table schema fingerprints, checksums, and `last_value_scan_at` timestamps. The classification cache stores class/reason and counts only. Unchanged content reuses cached embeddings; model/dimension changes re-embed from valid local metadata without value rescans. Only VALUE_LOW canonical values are stored in the value index; BLOCKED, MASKED, and VALUE_HIGH values are not embedded or persisted. Failed table scans preserve that table's last-known-good local entries and surface an incomplete index state.

`INDEX_REFRESH_TTL_HOURS` defaults to 24; set it to `0` to rescan eligible values at every startup. `INDEX_SCAN_WORKERS` defaults to 1 and is capped at 8. `EMBED_CACHE_MAX_ENTRIES` defaults to 250000 and controls batched collection of unreferenced embedding-cache rows. Use **Re-index schema** in the sidebar or run `python reindex.py` to force a full rebuild that ignores the refresh window; valid files remain available until replacement parts succeed. `python reindex.py --dry-run` prints metadata-only changed table/column counts, scan counts, an embedding estimate, and a rough duration. `python scripts/store_report.py` prints local classes and value/vector counts only, never value text. Verified examples and hints are retained. To reset a namespace completely, stop the app and delete only its `.vector_store/<namespace>/` directory.

`EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `EXAMPLE_CANDIDATE_LIMIT`, `INDEX_REFRESH_TTL_HOURS`, `INDEX_SCAN_WORKERS`, `EMBED_CACHE_MAX_ENTRIES`, `MAX_ROWS`, `QUERY_TIMEOUT_SECONDS`, and `MAX_RETRIES` configure indexing, retrieval, and execution. `EXAMPLE_CANDIDATE_LIMIT` defaults to 500 most recently saved examples before lexical ranking. `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` are optional comma-separated lists.

The sidebar shows index age and per-stage status; each query's **Run details** includes the same counts and timings. These diagnostics contain metadata and aggregates only, never row values.

## Security boundary

**The account in `DATABASE_URL` must be read-only.** Startup and query execution use only metadata reads, `SELECT`, `EXPLAIN`, and supported read-only or timeout session settings. Database permissions remain the authoritative boundary; application validation is an additional layer. Credentials are excluded from local namespaces and masked in displayed URLs.

The application no longer provisions or uses PostgreSQL vector tables. If an older PostgreSQL database still contains application-created `system_*` tables, review and drop them manually with an administrator after confirming they are no longer needed. The app does not drop them.

## Hints and examples

Optional database-specific guidance can be placed at `.vector_store/<namespace>/hints.md`. If that file is absent, the prompt builder falls back to the repository's root `hints.md`. Keep both files free of row data and credentials. After reviewing a successful query, **This was correct** saves the question and SQL to the namespace's local `examples.sqlite`; the UI reports failure if persistence fails.

Table comments are read as schema metadata. `catalog.describe.describe_catalog`, `db/init_db.py`, and `seed_library.py` are developer utilities; application startup does not import or run them. The legacy `CatalogStore` is used only by the optional description utility and is not the application index store.

## Install and run

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# Set DATABASE_URL to a read-only account and configure GROQ_API_KEY.
streamlit run app.py
```

Optional drivers are documented in `requirements.txt`. For example:

```bash
python -m pip install 'psycopg[binary]'  # PostgreSQL
python -m pip install pymysql             # MySQL
python -m pip install pyodbc              # SQL Server; also needs Microsoft's ODBC driver
```

## Tests and evaluation

```bash
python -m pytest tests/ -v
python eval/run_eval.py
streamlit run app.py
```

The SQLite pipeline tests use a mocked LLM. Optional MySQL read-only integration tests use `NLS_READONLY_MYSQL_URL` and skip when the SELECT-only database is unavailable. The evaluation fixture is populated separately in `eval/questions.json`.

## Read-only database role

Create a read-only role with grants appropriate to the schema. Run provisioning manually; the application never runs these statements.

```sql
-- Replace placeholders for your environment.
CREATE ROLE <read_only_role> LOGIN PASSWORD 'replace_me';
GRANT CONNECT ON DATABASE <database_name> TO <read_only_role>;
GRANT USAGE ON SCHEMA <schema_name> TO <read_only_role>;
GRANT SELECT ON ALL TABLES IN SCHEMA <schema_name> TO <read_only_role>;
```