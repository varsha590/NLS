# Runtime and Query Workflow

This document describes the Phase 2 implementation. Persistent vectors, embedding cache, examples, and optional per-database hints live under the local namespace directory. The target database is never used as an index or example store.

## Startup

1. `app.py` enters `ui.app:main()`. `ui.app:load_runtime()` calls `core.startup:init_app()` through `st.cache_resource`; the runtime is shared by Streamlit sessions in the process.
2. `config.settings:Settings.from_env()` reads `DATABASE_URL`, the model and retrieval settings, and `EXAMPLE_CANDIDATE_LIMIT` (default 500). Database identity for local storage comes from `db.adapter:DatabaseAdapter.namespace()`, a SHA-256 prefix of the credential-free URL.
3. `core.startup:init_app()` creates `DatabaseAdapter` and checks connectivity with `SELECT 1`. It does not create database objects or write target data.
4. `catalog.introspect:introspect_catalog()` discovers tables, columns, keys, comments, and relationships with `sample_limit=0`. `ALLOWED_SCHEMAS` and `EXCLUDED_TABLES` filter the catalog. No row samples are collected.
5. `retrieval.embeddings:EmbeddingModel` loads the configured local model and reports its embedding dimension. `core.startup:_config_policy_hash()` hashes the active policy/config files and cardinality threshold.
6. `core.startup:_schema_records()` builds table, column, and relationship documents from catalog structure. `schema.documents:build_table_document()`, `build_column_document()`, and `build_relationship_document()` omit protected columns/references. No introspection sample values enter schema documents.
7. `retrieval.local_store:LocalVectorStore.__init__()` opens `.vector_store/<namespace>/`, checks the manifest and paired FAISS/metadata checksums, and loads only valid indexes. `LocalVectorStore.build_schema()` reuses cached embeddings for unchanged content and atomically writes the schema index/metadata pair.
8. `retrieval.value_index:ValueIndex.build()` rechecks bounded distinct counts at startup. `ENUM`/`SET` values come from reflected type metadata; ordinary eligible columns use bounded `SELECT DISTINCT`. Only columns classified `VALUE_LOW` are passed to `LocalVectorStore.build_values()`. `VALUE_HIGH`, `BLOCKED`, and `MASKED` values are not embedded or persisted. The content-hash/model embedding cache avoids re-embedding unchanged text.
9. `core.startup:init_app()` sets `index_complete` from the actual schema and value build results, creates `HybridSchemaRetriever` and `ExampleStore` over the same local namespace, and builds the pipeline. `force=True` clears this namespace's schema/value indexes and embedding cache before rebuilding; examples and hints are retained.

## Namespace Files

Files are scoped to one credential-free database namespace. FAISS row `i` corresponds to metadata row `i`; both sides are validated before use. Temporary files used for atomic replacement are transient.

| File | Contents |
|---|---|
| `schema.faiss` | `IndexFlatIP` over L2-normalized float32 table, column, and relationship vectors; exact cosine search. |
| `schema_meta.json` | One entry per schema vector: schema-qualified table key, column or null, metadata type, and content hash. Schema text is not copied into this metadata file. |
| `values.faiss` | `IndexFlatIP` over L2-normalized float32 vectors for VALUE_LOW values only. |
| `values_meta.json` | One entry per value vector: schema-qualified table key, column, value hash, and canonical VALUE_LOW value text. |
| `manifest.json` | Store format, embedding model name, model dimension, normalization version, config/policy hash, build time, and checksums for both index/metadata pairs. |
| `embed_cache.sqlite` | Parameterized content-hash/model-name cache of normalized float32 vectors and dimensions. |
| `examples.sqlite` | Verified question/SQL pairs with update timestamps; retrieval reads only the configured most-recent candidate limit. |
| `hints.md` | Optional per-database prompt guidance. If absent, the root `hints.md` is used. |

`retrieval.local_store:LocalVectorStore._write_part()` writes and fsyncs temporary index and metadata files, renames the pair, then atomically updates the manifest. `_load_part()` validates checksums, row counts, index type, and dimension. A damaged part is discarded and rebuilt without discarding the other valid index. Model, dimension, normalization, or policy/config mismatch invalidates the schema/value indexes. The per-namespace reentrant lock serializes writes and protects search reads while a replacement index is swapped in.

## Per-Question Flow

1. `ui.app:main()` submits a question to `pipeline.orchestrator:TextToSQLPipeline.run()`.
2. `retrieval.value_index:ValueIndex.resolve_question()` matches against its in-memory view of VALUE_LOW values. Vector scoring uses one `LocalVectorStore.search_values()` call per scored mention, with table/column filtering; high-cardinality values are not stored or searched in the local value index. Ambiguous values return for confirmation before SQL generation.
3. `TextToSQLPipeline.run()` obtains schema context from `retrieval.schema_retriever:HybridSchemaRetriever.retrieve()`. That method embeds the query locally and calls `LocalVectorStore.search_schema()`; semantic results are associated by schema-qualified table key and combined with lexical ranking. `compact_ddl()` renders the selected tables from the in-memory catalog and omits BLOCKED columns.
4. `retrieval.examples:ExampleStore.retrieve()` requests at most `EXAMPLE_CANDIDATE_LIMIT` recent pairs from `LocalVectorStore.get_examples()` and ranks that bounded set with the existing lexical scorer.
5. `pipeline.orchestrator:TextToSQLPipeline.run()` calls `llm.prompt_builder:build_prompt()`. It reads `.vector_store/<namespace>/hints.md` first and falls back to root `hints.md` only when the local file is absent. The prompt receives the question, selected DDL, allowed resolved values, hints, examples, and any correction text.
6. `llm.generator:GroqGenerator.generate()` returns SQL. `validation.validator:validate_sql()` checks one read-only SELECT against catalog and policy constraints, verifies indexed literals, and applies the row limit. It calls `db.adapter:DatabaseAdapter.explain()` when supported.
7. `db.adapter:DatabaseAdapter.run_readonly_query()` applies supported read-only/timeout session controls, executes the validated query, and fetches at most `MAX_ROWS` results. `pipeline.orchestrator:_build_answer_text()` formats results locally; query result rows are not sent to the LLM.
8. `ui.app:_render_result()` enables the verified-example action only after successful validation and execution. `ExampleStore.save()` writes to the namespace-local SQLite file and returns a boolean; the UI reports failure rather than claiming success.

## Read-Only Target Guarantee

`core.startup:init_app()`, catalog introspection, value classification, schema retrieval, and example persistence do not issue target-database DDL or DML. Target connections are used for connection checks, metadata inspection, bounded `SELECT`/`SELECT DISTINCT`, `EXPLAIN`, and supported read-only or timeout settings. SQLite also uses `PRAGMA query_only`; its inspector issues read-only metadata PRAGMAs. MySQL startup can run with a SELECT-only account. PostgreSQL uses only read-only transaction/session settings and `SELECT`/`EXPLAIN` statements in the application path. The before-cursor contract tests enforce this boundary for SQLite and optional MySQL runs; a source-level test checks the PostgreSQL path.

The configured database role must still be read-only. This permission boundary is authoritative even when application validation or session settings are bypassed.

## Re-index and Configuration

- `ui.app:_render_sidebar()` clears the cached runtime and sets `force_reindex`; the next `init_app(force=True)` resets only the current namespace's schema/value indexes and embedding cache. `reindex.py:main()` invokes the same forced build. Other database namespaces are untouched.
- `Settings.from_env()` reads `DATABASE_URL`, `EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `EXAMPLE_CANDIDATE_LIMIT`, `MAX_ROWS`, `QUERY_TIMEOUT_SECONDS`, `MAX_RETRIES`, `ALLOWED_SCHEMAS`, and `EXCLUDED_TABLES`.
- `config/data_policy.yaml` controls protected columns; `config/value_resolution.yaml` supplies matching and language configuration. Their content and the cardinality threshold participate in the manifest policy/config hash.
- The optional description utility still imports the legacy `CatalogStore` (`catalog/describe.py:describe_catalog()`); it is not part of application startup or indexing. `db/init_db.py` and `seed_library.py` are developer-only fixture utilities and are not imported by the application.
- The compatibility modules `sql/validator.py` and `sql/executor.py` remain for Phase 6; the main pipeline uses `validation/validator.py` and `DatabaseAdapter` directly.

## Changes in This Phase

Phase 2 moved schema/value vectors and verified examples out of the target database into namespace-local FAISS/SQLite files, added cache-aware atomic rebuilds and bounded example retrieval, removed the target-database vector persistence path, wired all active dialects to local search, and established statement-capture tests for the read-only contract.