# Runtime and Query Workflow

This document describes the Phase 3 implementation. Schema/value vectors, classification metadata, the embedding cache, examples, and optional per-database hints live under the local namespace directory. The target database is read-only and is never used as an index or example store.

## Startup

1. `app.py` enters `ui.app:main()`. `ui.app:load_runtime()` calls `core.startup:init_app()` through `st.cache_resource`; the runtime is shared by Streamlit sessions in the process.
2. `config.settings:Settings.from_env()` reads the database/model/retrieval settings, `INDEX_REFRESH_TTL_HOURS` (24 by default, 0 means scan every startup), `INDEX_SCAN_WORKERS` (1 by default, capped at 8), and `EMBED_CACHE_MAX_ENTRIES` (250000 by default). `db.adapter:DatabaseAdapter.namespace()` derives local identity from the credential-free URL.
3. `core.startup:init_app()` creates `DatabaseAdapter`, checks connectivity with `SELECT 1`, loads `EmbeddingModel`, then constructs `retrieval.local_store:LocalVectorStore` before introspection so the manifest is read first. It never creates or writes target objects.
4. `catalog.introspect:introspect_catalog()` uses SQLAlchemy `get_multi_columns`, `get_multi_pk_constraint`, `get_multi_foreign_keys`, `get_multi_unique_constraints`, and `get_multi_table_comment` where supported, with per-table inspector fallbacks. It records columns, types, nullability, keys, comments, relationships, and ENUM/SET options. It issues no data-table SELECTs and collects no row samples.
5. `core.startup:_table_fingerprint()` hashes each table's structural metadata; `core.startup:_schema_fingerprints()` hashes the sorted table-fingerprint map globally. `core.startup:_config_policy_hash()` hashes the active policy/config files and cardinality threshold.
6. `core.startup:_scan_eligible_tables()` identifies tables with non-ENUM/SET text columns that may need scans. `retrieval.local_store:LocalVectorStore.fast_path_valid()` checks manifest format/model/dimension/normalization/policy, global schema fingerprint, FAISS/metadata integrity, classification-cache checksum, and per-table refresh timestamps.
7. On the fast path, `retrieval.value_index:ValueIndex.load_cached()` restores resolver values/classes from disk. Startup performs metadata inspection only: zero data-table scans, zero stats queries, zero embedding calls, and no index rewrites.
8. Otherwise, `core.startup:init_app()` compares per-table fingerprints and the TTL. `retrieval.value_index:ValueIndex.build_incremental()` reuses fresh table classifications and scans changed/stale tables only. It uses one bounded distinct-value query per eligible non-ENUM/SET column for value collection, count, shape check, and classification. Default scans reuse one read-only connection; optional worker threads use bounded read-only connections. ENUM/SET options come from `ColumnInfo.enum_options` and need no data scan.
9. `retrieval.local_store:LocalVectorStore.build_schema()` and `build_values()` reconcile desired metadata, reuse the content/model embedding cache, prune dropped keys, and write only changed index parts. `LocalVectorStore.save_index_state()` atomically saves fingerprints, per-table `last_value_scan_at`, and a checksum-protected classification cache containing classes, reasons, fingerprints, and counts only. A table scan failure preserves that table's last-known-good entries and marks the runtime incomplete.
10. `core.startup:init_app()` creates `HybridSchemaRetriever`, `ExampleStore`, and `TextToSQLPipeline`, and returns count/time-only `index_metrics`. `ui.app:_render_sidebar()` displays index age and stage statuses. `force=True` bypasses TTL without deleting last-known-good files before rebuild.

## Startup Decision Table

| Condition | Path | Work performed |
|---|---|---|
| Manifest, model/dimension/normalization/policy, checksums, global schema fingerprint, classification cache, and TTL all match | Fast load | Load FAISS, metadata, classification cache, and VALUE_LOW values. No data-table statements, statistics queries, embedding calls, or index writes. |
| Table added, removed, renamed, or structurally changed | Per-table rebuild | Rebuild schema records and process only changed tables; reconcile away dropped table/column/value keys. |
| A table's value timestamp is past `INDEX_REFRESH_TTL_HOURS` | Stale-value refresh | Rescan eligible candidate columns in stale tables only; content hashes reuse unchanged vectors. |
| Policy/config hash changes | Reclassification | Reclassify under current policy and reconcile affected records; unchanged content hashes reuse cached embeddings. |
| Embedding model, dimension, or normalization changes | Vector rebuild | Re-embed schema/value content from valid metadata; do not rescan values solely for vector incompatibility. |
| A FAISS part is missing/corrupt but its metadata is valid | Part rebuild | Rebuild only that vector part from validated metadata and the embedding cache. |
| Metadata/classification cache is missing/corrupt | Metadata rebuild | Recompute affected classifications and scan eligible columns when required; preserve independently valid index parts. |
| Force re-index (`--dry-run` excluded) | Full refresh | Ignore TTL and process all tables while preserving the previous valid files until replacements succeed. |

## Namespace Files

Files are scoped to one credential-free database namespace. FAISS row `i` corresponds to metadata row `i`; both sides are validated before use. Temporary files used for atomic replacement are transient.

| File | Contents |
|---|---|
| `schema.faiss` | `IndexFlatIP` over L2-normalized float32 table, column, and relationship vectors; exact cosine search. |
| `schema_meta.json` | One entry per schema vector: schema-qualified table key, column or null, metadata type, and content hash. Schema text is not copied into this metadata file. |
| `values.faiss` | `IndexFlatIP` over L2-normalized float32 vectors for VALUE_LOW values only. |
| `values_meta.json` | One entry per value vector: schema-qualified table key, column, value hash, and canonical VALUE_LOW value text. |
| `manifest.json` | Store format, embedding model name, model dimension, normalization version, config/policy hash, global/per-table schema fingerprints, per-table `last_value_scan_at`, build time, and checksums for both index/metadata pairs and the classification cache. |
| `classification_cache.json` | Per-table/per-column schema fingerprints, class/reason, distinct count, non-null count, and average text length. Never contains row values. |
| `embed_cache.sqlite` | Parameterized content-hash/model-name cache of normalized float32 vectors and dimensions. |
| `examples.sqlite` | Verified question/SQL pairs with update timestamps; retrieval reads only the configured most-recent candidate limit. |
| `hints.md` | Optional per-database prompt guidance. If absent, the root `hints.md` is used. |

`retrieval.local_store:LocalVectorStore._write_part()` writes and fsyncs temporary index and metadata files, renames the pair, then updates checksums. `_load_part()` validates checksums, row counts, index type, and dimension while retaining valid metadata if only a vector file is invalid. The per-namespace reentrant lock serializes writes and protects search reads while a replacement index is swapped in. The embedding cache is garbage-collected in batches above `EMBED_CACHE_MAX_ENTRIES`, deleting only hashes no longer referenced by active schema/value parts.

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

`core.startup:init_app()`, catalog introspection, value classification, schema retrieval, and example persistence do not issue target-database DDL or DML. Target connections are used for connection checks, metadata inspection, one bounded scan statement per eligible candidate column when a rebuild/refresh requires it, `EXPLAIN`, and supported read-only or timeout settings. The unchanged fast path issues no data-table statements. SQLite also uses `PRAGMA query_only`; its inspector issues read-only metadata PRAGMAs. MySQL startup can run with the SELECT-only account. PostgreSQL uses read-only transaction/session settings and `SELECT`/`EXPLAIN` statements in the application path. Statement-listener tests cover the no-scan fast path and read-only contract for SQLite and optional MySQL; a source-level test checks PostgreSQL.

The configured database role must still be read-only. This permission boundary is authoritative even when application validation or session settings are bypassed.

## Re-index and Configuration

- `ui.app:_render_sidebar()` clears the cached runtime and sets `force_reindex`; the next `core.startup:init_app(force=True)` ignores TTL and rebuilds the current namespace without deleting last-known-good files first. `reindex.py:main()` invokes the same forced build. Other database namespaces are untouched.
- `reindex.py:create_dry_run_plan()` compares read-only schema metadata with local fingerprints and prints counts plus a rough estimate; `reindex.py:main()` accepts `--dry-run` without scanning table values or changing the store.
- `scripts.store_report:format_store_report()` prints per-table/column classes and stored-value/vector counts plus model, dimension, build time, and last scan timestamps; it never formats value text.
- `Settings.from_env()` reads `DATABASE_URL`, `EMBEDDING_MODEL`, `VECTOR_STORE_PATH`, `SCHEMA_TOP_K`, `VALUE_TOP_K`, `VALUE_CARDINALITY_THRESHOLD`, `EXAMPLE_CANDIDATE_LIMIT`, `INDEX_REFRESH_TTL_HOURS`, `INDEX_SCAN_WORKERS`, `EMBED_CACHE_MAX_ENTRIES`, `MAX_ROWS`, `QUERY_TIMEOUT_SECONDS`, `MAX_RETRIES`, `ALLOWED_SCHEMAS`, and `EXCLUDED_TABLES`.
- `config/data_policy.yaml` controls protected columns; `config/value_resolution.yaml` supplies matching and language configuration. Their content and the cardinality threshold participate in the manifest policy/config hash.
- The optional description utility still imports the legacy `CatalogStore` (`catalog/describe.py:describe_catalog()`); it is not part of application startup or indexing. `db/init_db.py` and `seed_library.py` are developer-only fixture utilities and are not imported by the application.
- The compatibility modules `sql/validator.py` and `sql/executor.py` remain for Phase 6; the main pipeline uses `validation/validator.py` and `DatabaseAdapter` directly.

## Changes in This Phase

Phase 3 adds manifest-first startup, per-table/global structural fingerprints, a checksummed classification cache, TTL-based per-table value refresh, one bounded scan query per eligible column, incremental vector reconciliation, failure-preserving table updates, stage metrics, force/dry-run re-indexing, and a counts-only store report. Phase 2's namespace-local storage and read-only target boundary remain in force.