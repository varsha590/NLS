# Natural Language to SQL Gap Analysis

Static source review only. No application, test, SQL, or database operation was run. No database row values were inspected or reproduced. The current pre-existing worktree modification to `config/value_resolution.yaml` was preserved; this report describes the file as read during this review.

## 1. Summary Table

| Question | Verdict | Severity | One-line gap |
|---|---|---|---|
| 1. Index once, reload later | NOT MET | High | Startup always invokes both builders; `values.json` is written but never loaded. |
| 2. Preserve unchanged vectors | NOT MET | High | Unchanged rows are upserted with `embedding=None`, replacing stored vectors with NULL. |
| 3. Hash/change handling | PARTIAL | High | Per-item hashes and stale-row pruning exist only for PostgreSQL, but cache validity is not a gate and model/schema-wide invalidation is incomplete. |
| 4. Index/metadata disagreement | NOT MET | High | Missing local cache is silently rebuilt; missing or NULL database vectors are not reconciled against hashes. |
| 5. YAML settings | NOT MET | High | Resolver configuration includes a database-oriented hand-authored name allowlist and domain vocabulary, not just small overrides. |
| 6. Unconfigured column default | NOT MET | High | Data policy defaults to allow; indexing has separate and inconsistent defaults. |
| 7. Automatic eligibility | NOT MET | High | Runtime eligibility is text type plus a hand-authored name allowlist; no runtime distinct-count classifier or sensitive default-deny exists. |
| 8. Domain-specific content | NOT MET | Medium | Cue aliases, name lists, status fields, and activity expansion terms encode particular business semantics. |
| 9. Data reaching Groq | NOT MET | High | Prompt includes schema names, mappings, hints, examples, and corrections; sensitive values can enter mappings and corrections. |
| 10. Blocked columns before SQL | NOT MET | High | Block policy is applied during final SQL validation, not consistently during schema/value indexing or DDL construction. |
| 11. Writes to target DB | NOT MET | High | PostgreSQL startup creates extension/tables/indexes and persists vectors/examples; pruning also deletes rows. |
| 12. Dialect portability | NOT MET | High | Persistent vector paths are PostgreSQL-only; ILIKE and raw PostgreSQL vector SQL do not port to MySQL/SQLite. |
| 13. Startup cost | NOT MET | High | Distinct scans repeat per column and per indexing path; upserts open a connection per item. |
| 14. Retrieval at 100+ tables | PARTIAL | High | Top-k limits initial selection, but one-hop FK expansion is uncapped and semantic scores can be assigned to the wrong table. |
| 15. Memory/disk and FAISS | NOT MET | High | No FAISS index exists; vectors are held in PostgreSQL or JSON/in-memory structures, with no persisted-index reload path. |
| 16. Per-question latency | NOT MET | High | Candidate scoring can issue one vector-search DB call per candidate per phrase span, in addition to retries and EXPLAIN. |
| 17. Connection and complexity risks | NOT MET | High | Per-value upserts each check out a connection; candidate matching contains quadratic work and per-row deletes. |
| 18. Other correctness bugs | NOT MET | High | Retrieval, high-cardinality fallback, masking, error handling, and compatibility paths have verified defects. |
| 19. Tests and evaluation | NOT MET | Medium | Tests are mostly SQLite/unit coverage; `eval/questions.json` is empty and PostgreSQL/MySQL persistence is untested. |

## 2. Detailed Findings

### A. Indexing Lifecycle

#### 1. Is there a real index-once/reload-later path?

**Verdict: NOT MET.** `init_app()` counts PostgreSQL schema rows and sets `cached_is_current` from `schema_count > 0`, but both branches call `build_schema_embeddings()` and `build_value_embeddings()` ([core/startup.py:init_app:47](../core/startup.py#L47), [core/startup.py:init_app:54](../core/startup.py#L54), [core/startup.py:init_app:58](../core/startup.py#L58)). Those builders still scan current data and compare hashes. `ValueIndex.build()` clears its in-memory state, re-queries eligible columns, re-embeds them, then writes `values.json` ([retrieval/value_index.py:build:196](../retrieval/value_index.py#L196), [retrieval/value_index.py:build:260](../retrieval/value_index.py#L260)). No code path reads that file back; the only `storage_path` operation in `ValueIndex` is `write_text`.

`_catalog_fingerprints` only affects the display status (`previously_indexed`); it is not used to skip indexing. On SQLite/MySQL, `EmbeddingStore` indexing methods return without persistence, so the “cached” status is not evidence that an index was reloaded ([db/adapter.py:build_schema_embeddings:689](../db/adapter.py#L689), [db/adapter.py:build_value_embeddings:801](../db/adapter.py#L801)).

#### 2. Are unchanged stored embeddings preserved?

**Verdict: NOT MET.** Schema and value builders correctly compare item hashes and omit unchanged items from `to_embed` ([db/adapter.py:build_schema_embeddings:756](../db/adapter.py#L756), [db/adapter.py:build_value_embeddings:867](../db/adapter.py#L867)). However, they then upsert *all* rows. For an unchanged key `embed_map.get(key)` returns `None` ([db/adapter.py:build_schema_embeddings:780](../db/adapter.py#L780), [db/adapter.py:build_value_embeddings:887](../db/adapter.py#L887)); the conflict clauses assign `embedding = EXCLUDED.embedding` ([db/adapter.py:upsert_schema:299](../db/adapter.py#L299), [db/adapter.py:upsert_value:343](../db/adapter.py#L343)). Thus unchanged vectors are overwritten with NULL. The same issue applies to both schema and value vectors.

#### 3. How does change detection work?

**Verdict: PARTIAL.** Schema document hashes are SHA-256 over generated table, column, and relationship text; value hashes are SHA-256 over each distinct value ([db/adapter.py:build_schema_embeddings:711](../db/adapter.py#L711), [db/adapter.py:build_schema_embeddings:725](../db/adapter.py#L725), [db/adapter.py:build_value_embeddings:849](../db/adapter.py#L849)). Schema documents include introspection sample values ([schema/documents.py:build_table_document:12](../schema/documents.py#L12), [schema/documents.py:build_column_document:24](../schema/documents.py#L24)), so sample changes can invalidate embeddings even though those samples are not part of the final compact DDL.

For PostgreSQL, new/changed item hashes are embedded and stale schema/value keys are pruned. A table or column addition creates new keys; renames behave as add-plus-stale-delete; drops are removed by pruning. A changed value is added under a new value key and an old value is pruned. These operations are part of builders called on every startup, not a cheap whole-catalog skip ([db/adapter.py:prune_schema:577](../db/adapter.py#L577), [db/adapter.py:prune_values:617](../db/adapter.py#L617)). On other dialects the builders and pruning are no-ops.

Hashes do not include the embedding model identifier. A model change with unchanged content therefore does not cause re-embedding. Schema `cached_is_current` does not compare the current schema fingerprint with persisted state; it only checks for any schema row. Values have no per-column aggregate fingerprint to permit skipping distinct scans.

#### 4. What if index and metadata disagree or are missing?

**Verdict: NOT MET.** A missing `values.json` is not distinguished from a valid persisted cache: it is ignored and rebuilt from database scans. A PostgreSQL missing schema table/vector row causes fresh embedding if its hash is absent; however, if the hash exists but the vector is NULL/missing, the hash comparison treats the item as unchanged and the `None` upsert preserves the disagreement rather than repairing it ([db/adapter.py:build_schema_embeddings:756](../db/adapter.py#L756), [db/adapter.py:upsert_schema:299](../db/adapter.py#L299)). Value index metadata has no manifest recording schema hash, model, dimension, or per-column checksums. JSON write/read corruption is not a startup validation case because startup never reads the JSON file.

### B. Column Classification and YAML

#### 5. Every YAML setting and whether it is database-specific

**Verdict: NOT MET.** Current `value_resolution.yaml` contains these active keys ([config/value_resolution.yaml:1](../config/value_resolution.yaml#L1), [config/value_resolution.yaml:11](../config/value_resolution.yaml#L11), [config/value_resolution.yaml:351](../config/value_resolution.yaml#L351), [config/value_resolution.yaml:386](../config/value_resolution.yaml#L386), [config/value_resolution.yaml:410](../config/value_resolution.yaml#L410)):

| Setting | Current content/purpose | Hand-written per database, or derivable? |
|---|---|---|
| `thresholds.accept_score`, `ambiguous_gap`, `min_score`, `max_candidates` | Global matching thresholds: 0.88, 0.08, 0.65, 5 | Could be global/tuned from evaluation, not intrinsically per-database. |
| `value_column_patterns.suffixes` | `_status`, `_type`, `_category`, `_genre`, `_language`, `_format`, `_condition`, `_role` | Candidate patterns could be generic defaults; the right semantics are schema/domain-dependent. Also bypassed whenever the nonempty allowlist is set. |
| `value_column_patterns.exact_names` | `city`, `country`, `state`, `region`, `status`, `category`, `genre`, `language`, `format`, `condition`, `role`, `position`, `nationality`, `location` | Could be generic name-pattern defaults, but requires policy decisions; not inferred from distinct counts. Bypassed by the active allowlist. |
| `excluded_column_names` | Explicit exclusions include metadata columns plus email/phone/address/postal identifiers, ISBN, notes, embedding and relationship names | Sensitive-name denies should be derived automatically and overridable; the current exact-name list is manually maintained and incomplete. |
| `metric_value_names` | Aggregation terms plus sales/purchase/buy vocabulary | Mostly generic metric vocabulary, though transaction vocabulary is domain-shaped; it is manually curated. |
| `cued_metric_terms` | Empty mapping | Domain-specific overrides; currently no entries. |
| `excluded_terms` | Large static stop-word, date/time, and query-vocabulary list; current file also includes `name` and `email` | Generic language exclusions can be shared, but schema/domain terms should be derived or be small overrides. This is not a per-column list. |
| `cue_aliases` | category, publisher, branch, city, country, role, language with manually supplied synonyms | Domain-specific content; incorrect assumptions for another database. |
| `value_column_allowlist` | `category_name`, `publisher_name`, `branch_name`, `author_name`, `city`, `country`, `state`, `region`, `status`, `category`, `genre`, `language`, `format`, `condition`, `role`, `position`, `nationality`, `membership_type`, `location`, `name` | Must currently be curated to make these columns eligible. It is the opposite of automatic classification and applies by unqualified column name across tables. |
| `status_filter_column_names` | `status`, `availability`, `inventory_status`, `stock_status` | Can partly be inferred by name pattern, but whether a field means current-state versus event history is domain-specific. |
| `activity_query_expansion` | `event`, `events`, `transaction`, `transactions`, `purchase`, `purchases`, `sale`, `sales`, `quantity`, `amount` | Domain-specific semantic expansion; manually curated. |

Current `data_policy.yaml` settings are `columns` (one explicit table-column rule, `customers.email: block`), `default_mask: "partial"`, `auto_block_patterns` (`email`, `phone`, `contact`, `mobile`, `address`, `password`, `ssn`, `aadhaar`, `pan`, `token`, `secret`), and `value_index.allowed_name_columns: []` ([config/data_policy.yaml:1](../config/data_policy.yaml#L1), [config/data_policy.yaml:3](../config/data_policy.yaml#L3), [config/data_policy.yaml:4](../config/data_policy.yaml#L4), [config/data_policy.yaml:16](../config/data_policy.yaml#L16)). The auto-block patterns are a small configurable list but omit common identifier forms such as generic `id`/`*_id`; `default_mask` and `value_index.allowed_name_columns` are not consulted by the runtime policy/index code.

#### 6. Default for a column in neither file

**Verdict: NOT MET.** `classify_column()` returns `allow` after explicit and substring auto-block checks ([config/data_policy.py:29](../config/data_policy.py#L29), [config/data_policy.py:40](../config/data_policy.py#L40)). This is allow-by-default, not deny-by-default. Value-index behavior is different: `ValueIndex._is_value_column()` rejects columns absent from the nonempty `value_column_allowlist`, but `EmbeddingStore.build_value_embeddings()` has its own type-only eligibility and does not consult the YAML allowlist or data policy ([retrieval/value_index.py:_is_value_column:167](../retrieval/value_index.py#L167), [db/adapter.py:build_value_embeddings:826](../db/adapter.py#L826), [db/adapter.py:_is_value_column:908](../db/adapter.py#L908)).

#### 7. Automatic eligibility by type, cardinality, and names?

**Verdict: NOT MET.** The active `ValueIndex` checks for a text-like SQL type and membership in the hand-authored allowlist. Although it can record a column as high-cardinality after fetching `threshold + 1`, that is a cap for the resolver path, not a general classifier of all text columns ([retrieval/value_index.py:_is_value_column:167](../retrieval/value_index.py#L167), [retrieval/value_index.py:build:212](../retrieval/value_index.py#L212), [retrieval/value_index.py:build:227](../retrieval/value_index.py#L227)). `schema/value_catalog.classify_value_tiers()` can classify all text columns by distinct count, but it is a separate helper and is not called from `core/startup.init_app()` ([schema/value_catalog.py:classify_value_tiers:44](../schema/value_catalog.py#L44), [core/startup.py:init_app:24](../core/startup.py#L24)). Missing pieces include automatic name-pattern classification, deny-first sensitivity rules covering IDs and indirect identifiers, and a single shared eligibility policy across both embedding builders and resolver.

#### 8. Domain-specific YAML content

**Verdict: NOT MET.** `cue_aliases` names concepts such as publishers, branches, and library locations; `value_column_allowlist` encodes entity names and library-oriented roles; `status_filter_column_names` assumes specific current-state fields; `activity_query_expansion` pushes event/transaction/purchase vocabulary into retrieval ([config/value_resolution.yaml:351](../config/value_resolution.yaml#L351), [config/value_resolution.yaml:386](../config/value_resolution.yaml#L386), [config/value_resolution.yaml:410](../config/value_resolution.yaml#L410), [config/value_resolution.yaml:416](../config/value_resolution.yaml#L416)). `metric_value_names` includes transaction-domain terms as well as generic aggregation words. These entries are not inferred from another database’s schema or business rules. `hints.md` is currently only a commented placeholder, but the prompt builder will include its contents when supplied ([hints.md](../hints.md), [llm/prompt_builder.py:18](../llm/prompt_builder.py#L18)).

### C. Privacy and Data Boundary

#### 9. Paths to the Groq prompt and sensitive data exposure

**Verdict: NOT MET.** The pipeline passes the original user question, retrieved compact DDL, resolved values, retrieved examples, and correction text to `build_prompt()`; the prompt builder reads `hints.md` and assembles all of those fields into the user message ([pipeline/orchestrator.py:179](../pipeline/orchestrator.py#L179), [llm/prompt_builder.py:9](../llm/prompt_builder.py#L9), [llm/prompt_builder.py:18](../llm/prompt_builder.py#L18), [llm/prompt_builder.py:25](../llm/prompt_builder.py#L25)).

- **DDL/schema:** compact DDL includes names, types, key and reference details. It omits sample values, but does not remove blocked columns before rendering ([retrieval/schema_retriever.py:compact_ddl:127](../retrieval/schema_retriever.py#L127)). Thus sensitive column names and relationships can reach Groq.
- **Resolved value mappings:** the prompt includes the original mention and canonical database value. The active allowlist includes generic `name`; no data-policy check is made before a match is attached. Sensitive values in such an eligible column can therefore reach Groq ([retrieval/value_index.py:_is_value_column:167](../retrieval/value_index.py#L167), [pipeline/orchestrator.py:run:145](../pipeline/orchestrator.py#L145), [llm/prompt_builder.py:22](../llm/prompt_builder.py#L22)).
- **Hints:** arbitrary `hints.md` text is included as-is when present ([llm/prompt_builder.py:18](../llm/prompt_builder.py#L18)).
- **Examples:** saved user questions and SQL are retrieved and included in prompts; the PostgreSQL store fetches all examples before in-process ranking ([retrieval/examples.py:save:18](../retrieval/examples.py#L18), [retrieval/examples.py:retrieve:22](../retrieval/examples.py#L22), [db/adapter.py:get_examples:397](../db/adapter.py#L397)).
- **Corrections:** validation, generation, and execution errors can be fed back as `correction`. Some validation/value errors include the rejected literal or closest candidates ([pipeline/orchestrator.py:179](../pipeline/orchestrator.py#L179), [pipeline/orchestrator.py:213](../pipeline/orchestrator.py#L213), [llm/prompt_builder.py:34](../llm/prompt_builder.py#L34)).
- **Result rows:** the normal pipeline formats results locally; it does not call `GroqGenerator.summarize()`. The summarizer itself sends only question, column names, and row count, not row contents ([pipeline/orchestrator.py:_build_answer_text:25](../pipeline/orchestrator.py#L25), [llm/generator.py:summarize:56](../llm/generator.py#L56)).

Independently of the prompt path, schema introspection samples every column, schema embedding documents include samples, and the PostgreSQL value builder copies distinct strings from every textual column below its cardinality cap into `system_value_embeddings`. Those paths do not apply `data_policy` ([catalog/introspect.py:introspect_catalog:86](../catalog/introspect.py#L86), [schema/documents.py:build_table_document:12](../schema/documents.py#L12), [db/adapter.py:build_value_embeddings:826](../db/adapter.py#L826)). No sample values were inspected or reproduced for this report.

#### 10. Are blocked columns excluded before indexing?

**Verdict: NOT MET.** The data policy is called in final SQL validation to reject explicit references and `SELECT *` over tables containing blocked fields ([validation/validator.py:422](../validation/validator.py#L422), [validation/validator.py:465](../validation/validator.py#L465)). It is not consulted by catalog introspection, schema embedding, PostgreSQL value embedding, `ValueIndex`, or compact DDL. The local resolver has its own name exclusion list, which is not the same as policy and does not govern the PostgreSQL all-text value builder. This means blocked values can be sampled/indexed and stored even when a later SQL statement is rejected.

PostgreSQL’s internal tables are created before `introspect_catalog()` runs ([core/startup.py:init_app:36](../core/startup.py#L36)). The global `EXCLUDED_SCHEMA_OBJECTS` set is empty ([schema/metadata.py:10](../schema/metadata.py#L10)), and introspection only filters the configured `EXCLUDED_TABLES`; consequently these internal tables can enter the metadata/retriever catalog. The schema embedding builder skips `system_*`, but the retriever is built from all introspected metadata, so the skip does not remove them from compact DDL candidates.

### D. Database Read-Only Safety and Dialects

#### 11. Target-database writes and move-to-local gap

**Verdict: NOT MET.** PostgreSQL startup calls `ensure_pgvector()` before introspection, and `EmbeddingStore.__init__()` calls it again ([core/startup.py:init_app:36](../core/startup.py#L36), [db/adapter.py:EmbeddingStore.__init__:273](../db/adapter.py#L273)). Each call attempts `CREATE EXTENSION vector`, creates three `system_*` tables, attempts two HNSW indexes, and commits ([db/adapter.py:ensure_pgvector:81](../db/adapter.py#L81), [db/adapter.py:ensure_pgvector:91](../db/adapter.py#L91), [db/adapter.py:ensure_pgvector:94](../db/adapter.py#L94), [db/adapter.py:ensure_pgvector:110](../db/adapter.py#L110), [db/adapter.py:ensure_pgvector:125](../db/adapter.py#L125), [db/adapter.py:ensure_pgvector:139](../db/adapter.py#L139)).

Runtime writes also include schema/value embedding upserts, pruning deletes, and verified-example upserts ([db/adapter.py:upsert_schema:279](../db/adapter.py#L279), [db/adapter.py:upsert_value:324](../db/adapter.py#L324), [db/adapter.py:upsert_example:366](../db/adapter.py#L366), [db/adapter.py:prune_schema:577](../db/adapter.py#L577), [db/adapter.py:prune_values:617](../db/adapter.py#L617)). The normal question UI may save examples ([ui/app.py:_render_result:117](../ui/app.py#L117)). These are guarded to PostgreSQL; MySQL/SQLite do not receive equivalent persistent indexes. The separate `seed_library.py` utility also creates/inserts/truncates fixture tables, but it is not called by application startup ([seed_library.py:146](../seed_library.py#L146), [seed_library.py:158](../seed_library.py#L158)).

To meet the local-storage boundary, the vector/index, manifest/metadata, and examples stores must all be local; startup must not call DDL/upsert/prune against the target; and the active runtime role must be demonstrably read-only. Currently the README’s read-only-account guidance conflicts with startup writes ([README.md](../README.md#L28)).

#### 12. Dialect-specific features

**Verdict: NOT MET.** `vector` extension/type, `<=>` cosine SQL, `CAST(... AS vector)`, HNSW operator classes, and the associated PostgreSQL upserts are PostgreSQL-specific ([db/adapter.py:ensure_pgvector:91](../db/adapter.py#L91), [db/adapter.py:search_schema:411](../db/adapter.py#L411), [db/adapter.py:search_values:458](../db/adapter.py#L458), [db/adapter.py:upsert_value:339](../db/adapter.py#L339)). The methods short-circuit for non-PostgreSQL dialects, so they do not translate: schema vector search and examples disappear, and SQLite/MySQL do not get a persistent value vector store. `pg_trgm` is not an active runtime dependency: `ensure_trgm_indexes()` is a compatibility no-op ([schema/value_catalog.py:ensure_trgm_indexes:90](../schema/value_catalog.py#L90)).

The validator recognizes `ILIKE` expression nodes, but does not normalize that operator for MySQL/SQLite; generated `ILIKE` SQL is not portable there ([validation/validator.py:178](../validation/validator.py#L178)). Read-only controls are also uneven: SQLite uses `PRAGMA query_only`, MySQL attempts read-only transaction setup, PostgreSQL sets read-only, while the MSSQL branch sets `READ COMMITTED`, which is not read-only ([db/adapter.py:_set_read_only:173](../db/adapter.py#L173), [db/adapter.py:run_readonly_query:197](../db/adapter.py#L197)).

### E. Scale: 100–300 Tables

#### 13. Startup cost and loop structure

**Verdict: NOT MET.** Let $T$ be included tables, $C$ all columns, $C_t$ textual columns, $E$ resolver-eligible columns, $V_s$ schema embedding rows, and $V$ distinct values accepted by the PostgreSQL type-only value builder. `introspect_catalog()` loops schemas → tables → columns and issues one bounded `SELECT DISTINCT ... LIMIT 5` plus a connection checkout for each column. It also makes inspector calls/reflection per table ([catalog/introspect.py:introspect_catalog:35](../catalog/introspect.py#L35), [catalog/introspect.py:introspect_catalog:86](../catalog/introspect.py#L86)).

Then `EmbeddingStore.build_value_embeddings()` loops tables → text columns and issues one distinct query per eligible text column, capped at threshold + 1; it embeds changed values in a batch but upserts each value separately ([db/adapter.py:build_value_embeddings:814](../db/adapter.py#L814), [db/adapter.py:build_value_embeddings:826](../db/adapter.py#L826), [db/adapter.py:build_value_embeddings:875](../db/adapter.py#L875), [db/adapter.py:build_value_embeddings:887](../db/adapter.py#L887)). `ValueIndex.build()` repeats a distinct query for each resolver-eligible column, batches its embeddings per column, then upserts every value again and loads vectors per column ([retrieval/value_index.py:build:202](../retrieval/value_index.py#L202), [retrieval/value_index.py:build:212](../retrieval/value_index.py#L212), [retrieval/value_index.py:build:238](../retrieval/value_index.py#L238)).

**Illustrative source-count scenario, not measured runtime:** assume 30 columns/table and all columns textual. At 120 tables, introspection has 3,600 distinct-sample queries; at 300, 9,000. PostgreSQL adds up to 3,600/9,000 type-only value scans. `ValueIndex` adds $E$ scans, where $0 \le E \le C_t$; the theoretical all-eligible totals are 10,800 and 27,000 distinct queries respectively, before inspector/reflection work, hash fetches, schema embedding calls, and other metadata operations. In practice `E` is narrowed by the active allowlist, but the store-level value builder is not.

Schema embeddings are approximately one row per table + one per column + one per FK. Each schema/value upsert calls `connect()` separately; thus connection-pool checkouts scale approximately with $V_s + 2V$ value upserts across the two PostgreSQL value-building paths, plus per-column lookups and fixed operations. These are checkouts, not necessarily new physical TCP connections. `cached_is_current` does not remove any of these loops.

#### 14. Retrieval precision and prompt size

**Verdict: PARTIAL.** The retriever lexically scores every table, sorts them, selects at most `min(top_k, 20)`, and then appends every directly referenced FK neighbor of those selected tables. It does not recursively expand the new neighbors, but it imposes no post-expansion cap ([retrieval/schema_retriever.py:retrieve:58](../retrieval/schema_retriever.py#L58), [retrieval/schema_retriever.py:retrieve:81](../retrieval/schema_retriever.py#L81)). A hub table can therefore add many/all remaining tables to the prompt at either 120 or 300 tables. Additionally, when a table has no semantic result, the fallback uses `semantic_results[index]` by table-document position even though results are similarity-ranked, assigning another table’s score ([retrieval/schema_retriever.py:retrieve:92](../retrieval/schema_retriever.py#L92)).

**Prompt-token estimate (assumptions explicit):** DDL includes every column of each selected/expanded table. With 30 columns/table and a rough 5–10 tokenizer tokens per column plus table/relationship syntax, an 8-table selection with no significant FK expansion is roughly 1,200–3,000 tokens; a 20-table selection is roughly 3,000–7,000. If FK expansion reaches all tables, the same assumption yields roughly 18,000–40,000 tokens at 120 tables and 45,000–100,000 at 300. These are order-of-magnitude estimates, not measured tokenizer output. Hints, user text, value mappings, examples, and correction text add unbounded extra tokens; there is no final prompt-size budget. Schema top-k is environment-configured and capped at 20 in the retriever.

#### 15. Vector memory and disk

**Verdict: NOT MET.** There is no FAISS import, index build, serialization, or reload in application source. PostgreSQL stores 384-dimensional vectors; the configured embedding model dimension is not checked against the hard-coded `VECTOR(384)` column ([db/adapter.py:ensure_pgvector:94](../db/adapter.py#L94), [retrieval/embeddings.py:EmbeddingModel:16](../retrieval/embeddings.py#L16)). Local `values.json` stores values and, when available, Python-list vector data, but is rewritten and never loaded ([retrieval/value_index.py:build:260](../retrieval/value_index.py#L260)). With startup’s `EmbeddingStore` passed on SQLite/MySQL, the store methods return empty results; the local branch that embeds values without a store is not used.

For $N$ vectors of dimension 384 as float32, raw vector storage is $N \times 384 \times 4 = 1{,}536N$ bytes: about 1.46 MiB for 1,000, 146 MiB for 100,000, and 1.43 GiB for 1,000,000, excluding IDs, metadata, index overhead, Python object overhead, and duplicated copies. JSON decimal arrays are larger than packed float32. A flat exact FAISS index can be reasonable for small/moderate $N$, but the code has no FAISS index at any scale, and repeated per-candidate remote vector queries dominate before a local flat index’s compute cost is considered.

#### 16. Per-question latency and calls

**Verdict: NOT MET.** On a non-ambiguous question, the pipeline resolves values, retrieves schema once, retrieves examples once, then performs up to `max_retries + 1` generate/validate/execute attempts ([pipeline/orchestrator.py:run:123](../pipeline/orchestrator.py#L123), [pipeline/orchestrator.py:run:171](../pipeline/orchestrator.py#L171), [pipeline/orchestrator.py:run:177](../pipeline/orchestrator.py#L177)). Schema retrieval embeds the question once and performs one PostgreSQL schema vector search. Each validation that reaches `adapter.explain()` adds one DB call; each execution attempt adds one query/connection. Groq calls are bounded by retries + 1; answer synthesis is local, with no second LLM call.

The expensive path is value scoring: for every candidate phrase span it embeds the span, iterates every candidate value, and may perform `EmbeddingStore.search_values(..., top_k=1)` for each candidate. For $P$ scored spans and $U$ candidate values this can approach $P \times U$ vector-search DB calls/checkouts, not one lookup per question. `top_k=1` limits returned rows, not the number of searches. Non-PostgreSQL stores return no vector matches, but the local candidate loop still runs.

#### 17. Connections, quadratic work, and deletes

**Verdict: NOT MET.** Each `upsert_schema()` and `upsert_value()` opens and closes its own connection; build loops call them per item ([db/adapter.py:upsert_schema:288](../db/adapter.py#L288), [db/adapter.py:upsert_value:333](../db/adapter.py#L333), [db/adapter.py:build_value_embeddings:887](../db/adapter.py#L887)). Pruning uses one connection per prune method, but issues one `DELETE` statement per stale row ([db/adapter.py:prune_schema:586](../db/adapter.py#L586), [db/adapter.py:prune_values:626](../db/adapter.py#L626)); it is not one connection per deleted row.

`_score_candidates()` calls `indexed_values.index(value)` inside the candidate loop, giving quadratic lookup work for a column with $N$ values, and repeats a vector DB query for each candidate ([retrieval/value_index.py:_score_candidates:297](../retrieval/value_index.py#L297), [retrieval/value_index.py:_score_candidates:329](../retrieval/value_index.py#L329)). Phrase generation considers up to six-token spans with nested loops, so span count grows linearly with question length at a bounded six spans per start token; combined candidate scoring still multiplies that by $U$. High-volume per-item upserts and delete statements are additional linear statement overhead.

### F. Correctness Bugs

#### 18. Verified issues outside the design questions

**Verdict: NOT MET.** These are statically verified from current source; whether every branch is activated in a given deployment may depend on data/configuration.

- **Unchanged-vector NULL overwrite:** hash-identical entries are still upserted with `None`, and the conflict clause assigns the incoming embedding. See Q2 evidence above.
- **Wrong semantic score association:** ranked vector search rows are indexed by table-document position when a name does not match ([retrieval/schema_retriever.py:retrieve:92](../retrieval/schema_retriever.py#L92)).
- **Schema-qualified names are discarded in persisted embedding keys:** schema embedding construction stores `table_info.name.rsplit(".", 1)[-1]`, while the metadata/retriever may use `schema.table`; semantic results then fail the table-name lookup and can enter the incorrect positional fallback ([db/adapter.py:build_schema_embeddings:702](../db/adapter.py#L702), [retrieval/schema_retriever.py:retrieve:85](../retrieval/schema_retriever.py#L85), [retrieval/schema_retriever.py:retrieve:92](../retrieval/schema_retriever.py#L92)). This affects multi-schema catalogs and can also create collisions for identically named tables in different schemas.
- **High-cardinality fallback calls a missing method:** resolver calls `self.adapter.search_values(...)` for a high-cardinality column ([retrieval/value_index.py:_score_candidates:309](../retrieval/value_index.py#L309)); `DatabaseAdapter` has no such method. Its similarly named method belongs to `EmbeddingStore` and searches PostgreSQL vectors, not database-side distinct values. The large-column resolution path can therefore raise `AttributeError` rather than perform the intended lookup.
- **All-text PostgreSQL value indexing bypasses policy:** the store-level `_is_value_column()` tests type only ([db/adapter.py:_is_value_column:908](../db/adapter.py#L908)); `_is_schema_value()` returns false for nonempty values, and the builder does not call `data_policy`. On an upsert exception, `upsert_value()` places the raw value in logging `extra` ([db/adapter.py:upsert_value:360](../db/adapter.py#L360)). This is a potential sensitive-data logging route; it was not triggered during this static review.
- **Index errors can be swallowed:** per-item upserts catch SQLAlchemy errors and roll back; builders also catch SQLAlchemy errors, then startup continues to construct and return a runtime ([db/adapter.py:upsert_schema:318](../db/adapter.py#L318), [db/adapter.py:build_schema_embeddings:792](../db/adapter.py#L792), [db/adapter.py:build_value_embeddings:902](../db/adapter.py#L902), [core/startup.py:init_app:56](../core/startup.py#L56)). The UI can report readiness with partial/missing indexes.
- **Activity guard is broad:** any configured status column found in a metric query’s `WHERE` triggers rejection, without proving it is being used as a proxy ([pipeline/orchestrator.py:_uses_status_as_activity_proxy:102](../pipeline/orchestrator.py#L102)).
- **Unvalidated SQL can remain saveable:** `result.sql` is set before validation; the `ValidationError` branch records the error but does not clear it ([pipeline/orchestrator.py:193](../pipeline/orchestrator.py#L193), [pipeline/orchestrator.py:213](../pipeline/orchestrator.py#L213)). The UI shows the “correct” save action whenever SQL is present ([ui/app.py:117](../ui/app.py#L117)). Execution failures also leave SQL present. Further, `upsert_example()` catches write failures and returns normally, so the UI can report save success when persistence failed ([db/adapter.py:upsert_example:390](../db/adapter.py#L390), [ui/app.py:119](../ui/app.py#L119)).
- **Wrong table for an unqualified literal:** literal validation scans the full catalog and accepts the first matching column, rather than restricting the search to tables used by the query ([validation/validator.py:222](../validation/validator.py#L222), [validation/validator.py:284](../validation/validator.py#L284)).
- **Policy masking is incomplete:** `default_mask` is not read by `classify_column()`, which defaults to allow. The import fallback in validator returns `False` for `is_blocked`, i.e. fail-open if the import fails ([config/data_policy.py:29](../config/data_policy.py#L29), [config/data_policy.py:40](../config/data_policy.py#L40), [validation/validator.py:17](../validation/validator.py#L17)). Runtime activation of that import fallback is unverified. Pipeline output masking checks aliases/output names against every retrieved table, not a resolved source-column mapping; same-named fields can be misclassified ([pipeline/orchestrator.py:279](../pipeline/orchestrator.py#L279), [pipeline/orchestrator.py:283](../pipeline/orchestrator.py#L283)).
- **Compatibility helper has a missing import:** `retrieve_schema()` constructs `EmbeddingModel` on its no-indexer branch, but the module does not import it ([retrieval/schema_retriever.py:146](../retrieval/schema_retriever.py#L146), [retrieval/schema_retriever.py:167](../retrieval/schema_retriever.py#L167)).
- **Legacy validator is weaker:** the metadata-free `sql.validator.validate_sql()` path uses `parse_one()`, checks only the parsed expression type, and applies a limit; it does not perform the catalog, multi-statement, or mutation checks of the main validator ([sql/validator.py:81](../sql/validator.py#L81), [sql/validator.py:93](../sql/validator.py#L93)). `sql.executor.execute_sql()` passes SQL to the adapter without validating it itself ([sql/executor.py:14](../sql/executor.py#L14), [sql/executor.py:36](../sql/executor.py#L36)).
- **Duplicate import:** `schema.documents` helpers are imported at module top and again after `DatabaseAdapter.explain()` ([db/adapter.py:14](../db/adapter.py#L14), [db/adapter.py:268](../db/adapter.py#L268)). This is harmless but dead duplication.

No additional runtime claims are made where activation could not be established statically; those remain unverified.

### G. Tests and Evaluation

#### 19. Coverage and minimum proof set

**Verdict: NOT MET.** The SQLite startup tests check a cached status label and force-reindex label, not persisted index reload, skipped embedding calls, or unchanged vector preservation ([tests/test_startup.py:53](../tests/test_startup.py#L53), [tests/test_startup.py:76](../tests/test_startup.py#L76)). SQLite adapter/value tests cover read query bounds, schema samples, local distinct values, URL namespace, and basic resolver behavior. Resolver tests cover candidate matching, ambiguity, cues, and overlap; validator tests cover SELECT limits, rejected mutations/multiple statements/comments, and column errors. They do not prove PostgreSQL index durability, MySQL behavior, policy isolation during indexing, FAISS consistency, or query-call bounds.

`eval/questions.json` is empty. The evaluation runner exits before calling `init_app()` when there are no cases ([eval/questions.json](../eval/questions.json), [eval/run_eval.py:27](../eval/run_eval.py#L27), [eval/run_eval.py:29](../eval/run_eval.py#L29)). Real-database tests are explicitly environment-gated and limited to named fixture tables ([tests/test_integration_real_db.py:30](../tests/test_integration_real_db.py#L30)). No tests were run for this report.

Minimum test set to prove the requested design:

1. Persist/load a local index across process-like instances; assert no second distinct scan or re-embedding when content/model are unchanged; assert only changed values are embedded after mutation.
2. Verify schema/table/column add, rename, and drop behavior; corrupt/missing metadata and FAISS files; NULL/missing vectors; model/dimension change; and atomic consistency/rebuild behavior.
3. Exercise automatic text/type/cardinality/name classification with sensitive-pattern cases; assert default-deny and that the same exclusions apply to schema embeddings, value vectors, resolver, DDL, hints/examples/mappings, and logs.
4. Prove high-cardinality lookup sequence (exact, case-insensitive, fuzzy), bounded DB queries, correct handling of missing columns/values, and no indexing of full high-cardinality corpora.
5. Run adapter contract tests for PostgreSQL, MySQL, and SQLite that fail on any target DDL/DML, extension, index, or table creation and verify read-only execution controls.
6. Add scale fixtures at 120 and 300 tables, including a high-degree FK hub and duplicate column names; assert bounded prompt tables/tokens and stable table ranking.
7. Add per-question instrumentation assertions for embedding, DB-search, EXPLAIN, execution, and Groq call maxima; test retries and save-example eligibility after validation/execution/persistence failures.
8. Populate the eval fixture with representative joins, dates, aggregates, exact/fuzzy values, high-cardinality entities, sensitive-field denials, and dialect-specific expected results.

## 3. Scale Risks Ranked

| Rank | Risk | At 120 tables | At 300 tables |
|---|---|---|---|
| 1 | Repeated startup distinct scans | With 30 columns/table (illustrative), 3,600 introspection sample queries, up to 3,600 PostgreSQL type-only value scans, plus $E$ eligible-column scans. | Under the same assumption, 9,000 + 9,000 + $E$ scans. At the theoretical $E=C_t$, totals are 10,800 and 27,000 distinct queries. |
| 2 | Per-item PostgreSQL writes | $V_s$ schema upserts plus up to two value upserts per accepted distinct value; each upsert checks out its own connection. | Same linear formula, with greater absolute count; if 9,000 text columns each had 500 distinct values (illustrative cap, actual env setting may differ), the store-level path could process up to 4.5 million values. |
| 3 | Query-time value scoring | $P \times U$ candidate vector searches in the worst scored path, plus span embeddings and linear candidate/index lookups. | Candidate population $U$ grows with total indexed values; the nested DB search and repeated `.index()` can dominate latency even when schema retrieval is fast. |
| 4 | FK expansion/prompt growth | Initial top-k is capped at 20, but direct neighbors can push prompt toward all 120 tables. | Same uncapped expansion can approach all 300 tables; with 30 columns/table, rough DDL size can reach 45k–100k tokens under assumptions in Q14. |
| 5 | Vector memory/storage | $N$ vectors require about $1{,}536N$ raw bytes at 384 float32 dimensions; local JSON overhead is larger. | Same formula; for $N=100k$ about 146 MiB raw, for $N=1M$ about 1.43 GiB before overhead/copies. Flat FAISS is absent, so current search call count rather than FAISS scan cost is the issue. |

These are source-derived counts and explicit scenarios, not measurements of the target database. Actual table width, text-column count, distinct counts, FK degree, configured threshold/top-k, model dimension, and network latency are unknown. “Connection” counts refer to SQLAlchemy connection checkouts; pool reuse means they are not necessarily new physical connections.

## 4. Proposed Work Breakdown

Dependency order; sizes are rough engineering estimates, not implementation instructions.

| Order | Work item | Size | Main files |
|---|---|---|---|
| 1 | Decide privacy contract: deny/allow/mask precedence, sensitive patterns, whether entity names may enter prompts, whether examples/hints are trusted, and what local persistence may contain. | M | `config/data_policy.yaml`, `config/data_policy.py`, `README.md`, `docs/flow.md` |
| 2 | Unify schema and value eligibility around automatic type/cardinality/name classification with sensitive default-deny and small explicit overrides. Remove competing type-only versus allowlist decisions. | L | `config/data_policy.py`, `config/data_policy.yaml`, `config/value_resolution.yaml`, `retrieval/value_index.py`, `db/adapter.py`, `catalog/introspect.py`, `schema/value_catalog.py` |
| 3 | Establish local index ownership and metadata contract: namespace, schema/value/model hashes, embedding dimension, atomic FAISS+metadata persistence, load/reconcile/rebuild rules, and example persistence. | L | `core/startup.py`, `db/adapter.py`, `retrieval/value_index.py`, `retrieval/schema_retriever.py`, `retrieval/examples.py`, `config/settings.py` |
| 4 | Make indexing incremental at the column/item boundary and preserve unchanged vectors; avoid duplicate scans, embeddings, and per-item connection setup; reconcile additions/renames/drops. | L | `core/startup.py`, `catalog/introspect.py`, `db/adapter.py`, `retrieval/value_index.py`, `schema/documents.py` |
| 5 | Implement high-cardinality query-time lookup with exact/case-insensitive/fuzzy ordering and bounded DB calls; do not materialize/embed full columns. | M | `retrieval/value_index.py`, `db/adapter.py`, `validation/validator.py` |
| 6 | Bound and correct retrieval: associate semantic scores by key, cap FK expansion, exclude protected/internal schema details, and enforce prompt token budget. | M | `retrieval/schema_retriever.py`, `schema/metadata.py`, `catalog/introspect.py`, `llm/prompt_builder.py`, `pipeline/orchestrator.py` |
| 7 | Remove target-database DDL/DML paths and make read-only controls and SQL operators portable across PostgreSQL, MySQL, and SQLite. | L | `db/adapter.py`, `retrieval/examples.py`, `core/startup.py`, `validation/validator.py`, `sql/executor.py`, `README.md` |
| 8 | Repair correctness/error paths and gate “verified” example saves on successful validation and execution; remove compatibility paths that bypass checks or fail. | M | `pipeline/orchestrator.py`, `ui/app.py`, `retrieval/schema_retriever.py`, `validation/validator.py`, `sql/validator.py`, `sql/executor.py` |
| 9 | Add lifecycle, privacy, dialect, 120/300-table, operation-count, and populated evaluation coverage. | L | `tests/`, `eval/questions.json`, `eval/run_eval.py` |

## 5. Open Questions and Assumptions

- Should sensitive names (including customer/person names) ever be sent as resolved literals to Groq, or should the LLM receive only opaque placeholders and bind parameters?
- Should schema comments and user-maintained hints be treated as trusted prompt content? What size and review/approval controls should apply to saved examples and correction messages?
- Which text columns are semantically eligible by default, and which name patterns must be denied (IDs, emails, phone numbers, addresses, tokens, free-form notes, and indirect identifiers)?
- Is a local FAISS index required for both schema and value vectors, and should verified examples also be local? What are expected maximum indexed value counts and acceptable disk/memory budgets?
- What exact hash inputs should invalidate an index: database identity, schema, value set, filters/policy version, embedding model/revision, vector dimension, and normalization version?
- Is the app expected to support MariaDB separately from MySQL? Which exact PostgreSQL/MySQL/SQLite versions and read-only transaction semantics must be certified?
- What are representative table widths, eligible low-cardinality columns, distinct-value thresholds, FK degree, `SCHEMA_TOP_K`, and acceptable prompt token/latency budgets? The numeric scale examples above use an illustrative 30 columns/table and 384-dimensional float32 vectors.
- The active worktree contained a pre-existing modification to `config/value_resolution.yaml`; no edits were made to it. Its current settings, including generic `name` eligibility, were treated as the review subject.
- This review is static. Runtime activation of import-fallback behavior and actual execution latency remain unverified; no database values were queried or reported.