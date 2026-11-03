# Runtime and Query Workflow

This document describes the workflow implemented by the current source code. It avoids treating observations from one database or one model run as universal behavior.

## 1. Startup

1. `app.py` imports `ui.app` and calls `main()`.
2. `ui.app:load_runtime()` calls `core.startup:init_app()` through Streamlit's `st.cache_resource`. The resulting engine, indexes, and pipeline are cached in the Streamlit process. Changing `.env` while the process is running does not invalidate this cache; restart the app or clear the runtime cache to switch connections.
3. `Settings.from_env()` loads `.env` without overriding values already present in the process environment. `DATABASE_URL` selects the SQLAlchemy dialect and driver. The model, embedding, retrieval, cardinality, timeout, retry, and row-limit settings are also loaded here.
4. `DatabaseAdapter` connects and checks the connection with `SELECT 1`.
5. On PostgreSQL, startup calls `ensure_pgvector()`. It creates the `vector` extension if needed, creates the `system_schema_embeddings`, `system_value_embeddings`, and `system_examples` tables, attempts HNSW index creation, and commits. This PostgreSQL-only setup runs again when `EmbeddingStore` is constructed; the DDL uses `IF NOT EXISTS`.
6. `introspect_catalog()` discovers tables, columns, keys, comments, and bounded sample values. `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` control the catalog. There is no populated global exclusion set, so pre-existing internal or legacy tables remain visible unless excluded. PostgreSQL `system_*` tables created before introspection can therefore appear in the catalog and retrieval context.
7. `EmbeddingStore` counts existing PostgreSQL schema vectors, then startup calls the schema- and value-embedding builders. Both sides of the current `cached_is_current` branch call these builders, which compare hashes, upsert changed entries, and prune stale entries. The status label is not evidence that startup skipped all indexing work.
8. `ValueIndex.build()` gathers bounded distinct values from text columns allowed by `config/value_resolution.yaml` and the configured cardinality threshold. It writes its values and vectors to `.vector_store/<database-namespace>/values.json`; this file is currently written, not restored, at startup.
9. Startup constructs the hybrid schema retriever, the Groq generator, the example store, and the query pipeline.

## 2. Persistence and Side Effects

PostgreSQL is the only dialect for which `EmbeddingStore` persists and searches vectors or verified examples. It stores schema vectors, value vectors, and question/SQL examples in the three `system_*` tables above. The namespace is derived from a credential-free form of the database URL, so separate database URLs do not share these records. On non-PostgreSQL dialects these `EmbeddingStore` operations are no-ops; schema retrieval falls back to lexical ranking and verified-example storage is unavailable.

`values.json` is namespaced by the same credential-free database identity and contains the runtime value-index values and vectors, but the current startup does not read it back. `CatalogStore` is a compatibility class and is not used by `core.startup:init_app()`; its current `save()` method does not persist catalogs. The root-level `schema_index.json` and `value_catalog.json` are not loaded by the current startup path.

**Important privilege mismatch:** query execution is restricted to validated `SELECT` statements and uses dialect-specific read-only or timeout controls where available. However, PostgreSQL startup creates database objects and writes embedding rows; saving a verified example also writes to PostgreSQL. Therefore the current PostgreSQL application cannot operate with a strictly read-only database account as its only role. The README's requirement that `DATABASE_URL` use a read-only account, and its statement that startup creates no target-database objects, do not match the implementation. To enforce a read-only application role, PostgreSQL provisioning and index/example writes must be moved out of this runtime or separately authorized.

Read-only execution controls differ by dialect: PostgreSQL sets a read-only transaction and statement timeout; MySQL requests a read-only transaction and configures a statement timeout where supported; SQLite enables `PRAGMA query_only` and a progress-handler deadline; SQL Server sets `READ COMMITTED` isolation but does not set a read-only transaction here. Database permissions remain the authoritative safety boundary.

## 3. Per-Question Flow

1. The UI accepts a question and calls `TextToSQLPipeline.run()`.
2. `ValueIndex.resolve_question()` searches configured low-cardinality text values. Ambiguous values return before SQL generation so the UI can ask for confirmation. Confirmed or skipped mentions are passed back into the pipeline.
3. For questions containing configured metric vocabulary, the pipeline appends the configured activity-expansion terms to the **schema retrieval query**. The original user question is retained for SQL generation.
4. `HybridSchemaRetriever.retrieve()` ranks tables using PostgreSQL vector similarity when available and lexical relevance, then expands directly related tables through foreign keys. It renders a compact DDL subset for the prompt.
5. `ExampleStore.retrieve()` gets examples from PostgreSQL and ranks them lexically. On non-PostgreSQL dialects it returns no examples.
6. `build_prompt()` supplies the dialect, original question, selected DDL, accepted value mappings, optional `hints.md`, retrieved examples, and any correction text to `GroqGenerator.generate()`.
7. `validate_sql()` parses the generated SQL with SQLGlot. It requires one `SELECT`, rejects comments and mutating statements, checks table and column references against both the catalog and retrieved-table allowlist, applies data-policy blocks, verifies string literals against indexed values, and adds or caps `LIMIT` at `MAX_ROWS`. It attempts `EXPLAIN` when the adapter supports it; unavailable plans do not replace database permissions or query validation.
8. The pipeline applies an additional check for activity/metric questions: filters on configured current-status or availability columns are rejected as proxies for historical activity. Configured metric-word literal errors and ordinary validation/execution errors can enter the bounded `MAX_RETRIES` correction loop. Ambiguous values still require user confirmation.
9. `DatabaseAdapter.run_readonly_query()` applies available dialect controls, executes the validated SQL, and fetches no more than `MAX_ROWS` rows.
10. The pipeline formats returned columns and values locally with `_build_answer_text()`. It does not call `GroqGenerator.summarize()` for query results.
11. The UI renders the answer, SQL, rows, errors, and run details. **This was correct** saves the question and SQL as a verified example where PostgreSQL example storage is enabled.

## 4. LLM and Data Boundary

The SQL-generation request can contain the user's question, the selected tables' compact DDL, accepted value mappings, `hints.md`, retrieved verified examples, and correction messages. The compact DDL contains names, types, primary keys, and foreign keys; introspection samples and the full distinct-value index are not included in that DDL. Credentials and `DATABASE_URL` are not placed in the prompt.

Query result rows are formatted in application code and are not sent to the LLM by the current pipeline. `GroqGenerator.summarize()` exists, but `TextToSQLPipeline.run()` does not call it. Resolved values, hints, and saved examples can still contain user or business data and are sent as part of SQL generation when relevant.

The sentence-transformer model runs locally after its model files are available. SQL generation itself requires the configured Groq API key. The configured database driver must be installed for the selected `DATABASE_URL`.

## 5. Configuration and Database Switching

- `DATABASE_URL` selects the target database. Install its SQLAlchemy driver and restart Streamlit or clear its cached runtime after changing the URL.
- `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` are comma-separated environment settings. Add internal, legacy, or sensitive tables to `EXCLUDED_TABLES`; the introspector does not automatically exclude arbitrary system tables.
- `VALUE_CARDINALITY_THRESHOLD` bounds distinct-value indexing. `config/value_resolution.yaml` controls eligible value columns, excluded columns/terms, matching thresholds, metric vocabulary, activity-query expansion, and status columns guarded for metric questions.
- `hints.md` is optional, global business context. Update or clear it when switching domains; status definitions, revenue rules, refunds, and other domain semantics are not inferred reliably from a schema alone.
- `MAX_ROWS`, `QUERY_TIMEOUT_SECONDS`, and `MAX_RETRIES` constrain execution and recovery. `SCHEMA_TOP_K` and `VALUE_TOP_K` control retrieval breadth.
- `config/data_policy.yaml` controls blocked and masked columns. Database grants should independently enforce access to sensitive fields.

## 6. Verification

Run the unit and integration suite with `python -m pytest tests/ -v`. The real-database laptop integration tests run only when the configured database exposes their required `orders`, `order_items`, and `products` fixture tables; otherwise they skip. Run `python eval/run_eval.py` to compare pipeline results with the configured cases in `eval/questions.json`. The starter fixture is empty until cases are added.

The Streamlit app is launched with `streamlit run app.py`. The sidebar's **Re-index schema** action clears the cached runtime and forces startup indexing again.