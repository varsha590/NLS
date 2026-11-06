# NLS (Natural Language to SQL) - Restructuring Spec

Single source of truth for the restructuring. Read this first in any new session.

## Working rules (apply to every step)

- Inspect before changing. Prepare a file-by-file plan and STOP for approval.
- Do NOT edit, delete, stage, commit or push anything until the plan is approved.
- After each numbered implementation step, stop, show a diff summary and test output, and wait for my explicit approval. Approval is mine to give, not the agent's.
- Before deleting a file, list it with the reason and what imports/tests reference it. Never delete tests silently; migrate their coverage first.
- Do not claim a feature works unless it was tested. Do not commit or push.
- Do not blindly rewrite the project. Preserve working functionality.
- Treat `.env`, `test.db` and `.vector_store` as user data; do not delete them.
- Do not hardcode database/table/column names or company-specific logic. No YAML policy configs.

## Status

- Step 1 (validator): DONE and approved.
- Step 2 (ingestion, `schema.json`, local dataset metadata, Streamlit upload screen): DONE and approved.
- Step 3 (Qdrant indexing + retrieval): NEXT. Give the file-by-file plan first, then wait.
- Step 4 (query workflow, credentials form, execution): pending. Querying is unavailable in the UI until Step 4.
- Step 5 (cleanup, docs, dependencies): pending.

Known failing tests (both fail on the clean pre-Step-1 baseline, unrelated to the work so far):
- `tests/test_pipeline_sqlite.py::test_pipeline_retries_unverified_metric_word_as_measure`
- `tests/test_value_index_resolver.py::test_cue_followed_by_unknown_value_reports_one_not_found`
Fix or retire them in the cleanup step; do not leave them as permanent known failures.

## Goal

Simplify and restructure NLS around this flow:

1. User uploads a `.sql` dump (schema + master-table INSERTs only) or a SQLite `.db`.
2. The app parses it locally (never executes uploaded SQL), writes `schema.json`, and builds small embedding documents: tables, columns, relationships, and master values.
3. Documents are stored in Qdrant (Docker), filtered by tenant and dataset.
4. For a question: embed it, retrieve relevant tables/columns/relationships and matching master values, send only that context to Groq. Groq generates SQL only.
5. SQL is validated locally against the full `schema.json` (SQLGlot). Only after validation passes, ask for host/port/db/username/password and execute read-only against the real DB.
6. Example: master table has "electronics", user asks about "electronics" -> the matched value goes to the LLM so it writes a correct filter.

## 1. Remove unused code

- Audit structure, imports, dependencies and tests before deleting anything.
- Identify obsolete files: old classification framework, old local vector store (FAISS), duplicate validators, old config, unused scripts.
- Remove only genuinely unnecessary files; update imports and references after removal.
- Do not delete working SQL validation, execution, schema parsing or security functionality.
- Remove obsolete dependencies from `requirements.txt`.

## 2. Qdrant with Docker

- Replace FAISS/local vector store with Qdrant via `qdrant-client`. Check the INSTALLED client version and its current docs for the search API (e.g. `query_points`) before writing code.
- `docker-compose.yml`: qdrant image, port 6333, persistent volume, optional API key via env.
- Connection settings in environment variables.
- One collection, vector size 384, cosine. Payload indexes on `tenant_id` and `dataset_id`.
- Payload metadata: tenant_id, dataset_id, table name, column name, document type.
- EVERY search filters by both tenant_id and dataset_id.
- Deterministic point IDs (uuid5 of tenant + dataset + doc type + names) so re-indexing replaces points.
- Re-index: UPSERT the new points first, THEN delete stale points of that dataset by filter. Never delete first.
- Store embedding model name and dimension in dataset metadata; refuse to query if they changed.
- `tenant_id` comes from a `TENANT_ID` env var / Streamlit session default. Add a clear code comment and README note that real authentication is a remaining limitation.

## 3. Ingestion (implemented in Step 2; Step 3 wires it to Qdrant)

- `.sql`: parse with SQLGlot, extract tables, columns, types, PKs, FKs, relationships. NEVER execute uploaded SQL. Skip DELIMITER blocks, procedures, triggers, views, SET/LOCK without crashing. Extract only CREATE TABLE and FK-defining ALTER TABLE, plus literal INSERT ... VALUES for master values.
- `.db`: verify header `SQLite format 3\0`, open with sqlite3 URI `mode=ro`, never load extensions, run only schema reads plus bounded read-only `SELECT DISTINCT` for low-cardinality value documents.
- Persist complete `schema.json` per dataset including detected dialect (user override dropdown in Streamlit).
- Separate embedding documents for tables, columns, relationships, and values. Never embed the whole file as one document.
- Value documents: only low-cardinality columns (distinct count <= `LOW_CARDINALITY_MAX`); skip key columns, sensitive names, high-cardinality, and PII-flagged columns (email, phone, ID-like). A `.sql` with no INSERTs simply has no value documents.
- Upload limits: `MAX_UPLOAD_MB`, parse timeout (subprocess, killed on timeout, scrubbed environment), reject non-text `.sql`.
- Dataset hash for change detection = file bytes + dialect override + embedding model name. Unchanged hash skips re-index; any change triggers re-index.
- Support re-indexing when the schema changes.

## 4. Retrieval

- Search table, column, relationship (and value) vectors together; roll scores up to their tables; add FK neighbors with a hard cap on total tables.
- Send Groq only the selected tables' columns and relationships plus matching master values. Full `schema.json` stays local for validation.
- Resolve question values against stored master values: exact, case-insensitive match to the stored form first; embedding similarity only as a fallback for near-misses.
- Master values do go to Groq. This is a documented decision: master tables must hold non-sensitive reference data only.
- Tell Groq the stored dialect.

## 5. Validation (implemented in Step 1)

- SQLGlot `qualify`/scope with the full schema; qualified references always checked against the catalog; aliases only allowed in ORDER BY/GROUP BY/HAVING of the same SELECT scope.
- Single pure SELECT only (CTEs and subqueries allowed). Reject data-modifying CTEs, SELECT INTO, FOR UPDATE, multiple statements.
- Function denylist: pg_sleep, pg_read_file, load_extension, dblink, sleep, benchmark.
- Sensitive-column rule in code (one extensible constant, whole-token matching, applied in projection, WHERE, JOIN, GROUP BY, ORDER BY); reject SELECT * on tables with sensitive columns.
- No row limit; paginate results in the UI; keep timeout and read-only session.
- No EXPLAIN and no DB connection during validation (schema.json only).

## 6. Execution and credentials (Step 4)
- Ask for host, port, database name, username, password in an `st.form` ONLY after validation passes. No widget `key=` for credential fields (keys store values in `st.session_state`).
- Support sqlite (read-only file), mysql (pymysql), postgres (psycopg) via runtime-built URLs.
- Never store credentials in `.env`, session state after submission, logs, Qdrant, or prompts. Mask them in exception messages. Close the connection after use.
- Read-only transaction and query timeout (Postgres `SET TRANSACTION READ ONLY` + `statement_timeout`; MySQL `max_execution_time`; SQLite `mode=ro` + `PRAGMA query_only`). Paginate results in the UI. README must tell users to connect with a SELECT-only DB role.
- Show result rows in the UI. Never send rows to Groq. Any summary uses only column names and row count.
- Log each executed query: tenant, dataset, SQL with literals replaced by placeholders, timestamp, row count, duration. Never log credentials or row data.
- Show "no matching records found" for empty results.
- Explain clearly that a `.sql` dump gives schema metadata but is not a live database; execution needs a separate connection.

## 7. Tests

- Unit tests use Qdrant local/in-memory mode (no Docker). Real-Docker tests are marked `integration`, including one tenant/dataset isolation test (payload indexes are no-ops in local mode).
- Required: tenant/dataset isolation, re-index replaces old points, unchanged hash skips re-index, validator regression cases, no connection before execution, no credentials or rows in logs/prompts.
- Add a `conftest.py` with test-only defaults so the suite does not need a local `.env`.

## 8. Project quality

- Keep logic in a plain Python package with no Streamlit imports; Streamlit is a thin UI.
- Maintain `.env.example`; keep `.gitignore` covering uploads, dataset storage, Qdrant data, secrets.
- README: Docker setup, env vars, ingestion steps, query workflow, execution requirements, remaining limitations (including tenant auth).
- Embeddings: prefer `fastembed` (384-dim) over `sentence-transformers` unless the project already depends on the latter.
- Final UI must be client friendly, not developer friendly: show only what a
  client can use (upload, question box, results table, plain-language
  messages, credentials form after validation). Hide dialect override, model
  names, scores, flags, document counts and raw errors, or put them in a
  collapsed "Advanced" section. Generated SQL only in a collapsed "Show query".

## Cleanup list (Step 5, needs approval; list reason and references first)

- `classification_report.md`, `hints.md`
- `docs/fix_log.md`, `docs/flow.md`, `docs/gap_analysis.md` (rewrite flow.md for the new architecture; move still-open gaps into README "Remaining limitations"; archive history to `docs/legacy/` if kept)
- `test.db` (tracked in git, 0 bytes): untrack with `git rm --cached` and ignore
- `reindex.py`, `eval/`, `scripts/`
- `sql/validator.py` (compatibility wrapper) after migrating `rewrite_case_insensitive_comparisons` and its test; `validation/validator.py` is the live validator
- Old FAISS code, `data_polhwicy.yaml`, `value_resolution.yaml`, classification/report modules, after migrating their tests

## Final report must include

Final project tree, deleted files, modified files, Docker commands, environment variables, remaining limitations.