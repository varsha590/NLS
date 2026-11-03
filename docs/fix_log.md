# Fix Log: Natural Language to SQL Pipeline

## Phase 0: Independent Quick Bug Fixes

### What Changed

1. **0a. Unchanged-Vector Preservation & Missing Vector Repair**
   - File: `db/adapter.py` (`upsert_schema`, `upsert_value`, `build_schema_embeddings`, `build_value_embeddings`)
   - Replaced unconditional `embedding = EXCLUDED.embedding` updates with `COALESCE(system_..._embeddings.embedding, EXCLUDED.embedding)` when `embedding` is `None`, preserving existing vectors for unchanged items.
   - Updated `get_all_schema_embeddings` and `get_all_value_embeddings` to detect rows with `embedding IS NULL` (`vector_missing`).
   - `build_schema_embeddings` and `build_value_embeddings` now re-embed rows where content hash matches but the stored vector is NULL/missing.

2. **0b. ValueIndex High-Cardinality Call Fix**
   - File: `retrieval/value_index.py` (`_score_candidates`)
   - Fixed high-cardinality resolution path: replaced non-existent `self.adapter.search_values(...)` with `self.embedding_store.search_values(...)` using the embedded mention vector, preventing `AttributeError`.

3. **0c. Schema Retriever Key Association & Schema-Qualified Persistence**
   - Files: `db/adapter.py`, `retrieval/schema_retriever.py`
   - Schema and value embedding builder persistence preserves the schema-qualified table name (`table_info.name`, e.g. `schema.table`).
   - Removed positional fallback (`semantic_results[index]`) in `HybridSchemaRetriever.retrieve`. Semantic similarity scores are strictly associated by table name key, supporting multi-schema databases with same-named tables without cross-assignment.

4. **0d. Missing EmbeddingModel Import & Duplicate Cleanup**
   - Files: `retrieval/schema_retriever.py`, `db/adapter.py`
   - Added `from retrieval.embeddings import EmbeddingModel` to top of `retrieval/schema_retriever.py` to fix `NameError` in `retrieve_schema()`.
   - Removed duplicate `schema.documents` import in `db/adapter.py`.

5. **0e. Example Save Gating & Error Result Scrubbing**
   - Files: `pipeline/orchestrator.py`, `db/adapter.py`, `retrieval/examples.py`, `ui/app.py`
   - `upsert_example` and `ExampleStore.save` now return boolean status.
   - In `TextToSQLPipeline.run`, `result.sql` is cleared (`result.sql = ""`) on both `ValidationError` and `DatabaseUnavailableError`.
   - In `ui/app.py`, the "This was correct" action is rendered only when query execution completed without errors and returned rows. A warning is surfaced if persistence returns `False`.

6. **0f. Redact Raw Values from Logging Extras**
   - File: `db/adapter.py` (`upsert_value`)
   - In the SQLAlchemy error handler, raw column values are excluded from `extra` (logs `table` and `column` only).

7. **0g. Restrict Literal Validation to Used Tables**
   - File: `validation/validator.py` (`_check_and_rewrite_literals`, `validate_sql`)
   - Unqualified column lookup during literal safety checks is now scoped to `used_tables` instead of the entire database catalog, preventing false positives from same-named columns in unreferenced tables.

8. **0h. Visible Index Build Error State**
   - Files: `db/adapter.py`, `core/startup.py`, `ui/app.py`
   - `build_schema_embeddings` and `build_value_embeddings` return boolean status (`False` on build failure).
   - `init_app` tracks `index_complete` and sets `catalog_status: "incomplete"` if an error occurred.
   - UI displays an `index incomplete` warning in the sidebar when indexing is partial.

### Tests Added

Added `tests/test_phase0_fixes.py` covering:
- `test_0a_upsert_schema_and_value_preserve_existing_vectors`: Verifies `COALESCE` update SQL on `embedding=None`.
- `test_0a_build_schema_embeddings_repairs_missing_vectors`: Verifies rows with matching hash but missing vectors are re-embedded.
- `test_0b_value_index_high_cardinality_calls_embedding_store_without_attribute_error`: Verifies high-cardinality candidate scoring calls `embedding_store.search_values`.
- `test_0c_schema_retriever_multi_schema_same_table_name`: Verifies same-named tables across schemas receive distinct scores and no positional leakage.
- `test_0d_retrieve_schema_imports_embedding_model`: Verifies `retrieve_schema` executes with imported `EmbeddingModel`.
- `test_0e_validation_error_clears_result_sql`: Verifies `result.sql` cleared on `ValidationError`.
- `test_0e_execution_failure_clears_result_sql`: Verifies `result.sql` cleared on execution failure.
- `test_0e_upsert_example_reports_failure_to_caller`: Verifies `save()` reports failure when persistence is unavailable.
- `test_0f_upsert_value_does_not_log_raw_value`: Verifies raw values are omitted from logging extras on error.
- `test_0g_literal_validation_restricts_to_used_tables`: Verifies literal resolution only checks tables in the query.
- `test_0h_partial_index_surfaces_incomplete_state`: Verifies `catalog_status == "incomplete"` on build errors.

All 54 unit and regression tests pass (2 integration tests skipped pending live laptop fixture schema).

### Unverified Items

- Real PostgreSQL `pgvector` index behavior in production (tested via statement inspection/mocks as target database has no live PostgreSQL server; PostgreSQL-specific writes will be completely removed in favor of local FAISS in Phase 2).

