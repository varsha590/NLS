# Natural Language to SQL

A modular text-to-SQL application built with Streamlit, SQLAlchemy, local sentence-transformer embeddings, Groq, and SQLGlot. The connected database dialect is detected from SQLAlchemy; schema and vector indexes are stored locally, not in the target database.

## Configure a database

Use Python 3.10 or newer. Copy `.env.example` to `.env`, set `DATABASE_URL`, and install the optional SQLAlchemy driver matching that URL. To switch between PostgreSQL, MySQL, SQLite, or SQL Server, change `DATABASE_URL` and install the corresponding driver; no application code or dialect setting needs to change.

SQLite requires no external server or driver:

```env
DATABASE_URL=sqlite:///./example.db
```

On first start, the app introspects the configured schema, samples up to five values from each column, builds local embeddings, and stores the catalog under a credential-free database namespace inside `VECTOR_STORE_PATH`. A schema hash and embedding-model name determine whether the index can be reused. Use **Re-index schema** in the sidebar or run `python reindex.py` to refresh it. The application does not create, alter, or seed target database tables.

Table descriptions used for schema retrieval are taken from the database's own table comments where present. If a table has no comment, a neutral fallback description is generated. Business-relevance hints in schema documents are derived automatically from the table's foreign-key relationships; no domain-specific text is hard-coded. To provide richer descriptions, add comments directly to your database tables or run `catalog.describe.describe_catalog` to generate them with an LLM.

`GROQ_API_KEY` enables SQL generation. `LLM_MODEL` selects the Groq model. `EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `MAX_ROWS`, `QUERY_TIMEOUT_SECONDS`, and `MAX_RETRIES` configure retrieval and execution. `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` are optional comma-separated lists. Use `EXCLUDED_TABLES` to hide internal, legacy, or system tables that should not be visible to the LLM.

## Security boundary

**The database account in `DATABASE_URL` MUST be read-only.** This is the primary security boundary. SQL validation is a second layer: it permits one SELECT, checks referenced tables and columns against the catalog, and adds or caps a row limit. Where supported, the adapter also starts a read-only transaction and sets a statement timeout. Application validation is not a substitute for database permissions. Credentials are excluded from local index namespaces and masked in displayed URLs.

## Domain hints and verified examples

Add optional business definitions and vocabulary to a root-level `hints.md`; the prompt builder includes it when present. Because `hints.md` is a single global file, its content should match the connected database's domain. When switching databases, update or clear `hints.md` so that stale domain context from a previous database does not mislead the LLM. After reviewing an answer, use **This was correct** to save its question and SQL as a verified example. Examples are stored locally per database namespace and are not shared across databases. Optional LLM descriptions can be generated with `catalog.describe.describe_catalog`; completion keys can be persisted through `CatalogStore` so interrupted work can resume.

## Install and run

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DATABASE_URL and GROQ_API_KEY.
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
python -m pytest tests/test_validator.py tests/test_pipeline_sqlite.py -v
python eval/run_eval.py
streamlit run app.py
```

## Read-only database role (recommended for production)

Create a read-only role with column-level grants that exclude blocked columns.
Run manually; the app never executes this automatically.

```sql
-- PostgreSQL example (replace <your_role>, <your_database>, and column names to match your schema)
CREATE ROLE <your_role> LOGIN PASSWORD 'change_me';
GRANT CONNECT ON DATABASE <your_database> TO <your_role>;
GRANT USAGE ON SCHEMA public TO <your_role>;
-- Grant SELECT on all tables, then revoke blocked columns
GRANT SELECT ON ALL TABLES IN SCHEMA public TO <your_role>;
-- Revoke access to sensitive columns (adjust to your schema)
REVOKE SELECT (sensitive_column) ON your_table FROM <your_role>;
-- Repeat for any other blocked columns listed in config/data_policy.yaml
```

The app reads the connection user from the `DATABASE_URL` environment variable.

The SQLite pipeline test uses a mocked LLM and requires neither Groq credentials nor a separate database. Add objects to `eval/questions.json` with `question` and read-only `expected_sql` fields; the eval runner validates both generated and expected queries, then compares unordered result sets on the configured database. The starter eval file is empty and reports that evaluation cases need to be added.
