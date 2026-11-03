# Runtime and Query Report

This report describes the code currently in the workspace and the configured PostgreSQL database observed on 2026-10-30. It does not change application code.

## 1. Startup and persistence

### Startup order

1. `app.py` imports `ui.app` and calls `main()`.
2. `ui/app.py:load_runtime()` calls `core/startup.py:init_app()` through `st.cache_resource`. Streamlit caches the runtime in process memory.
3. `config/settings.py:Settings.from_env()` loads `.env` with `python-dotenv`. The actual runtime used PostgreSQL, model `openai/gpt-oss-120b`, and the local all-MiniLM-L6-v2 embedding model.
4. `db/adapter.py:DatabaseAdapter` creates the SQLAlchemy engine and checks connectivity with `SELECT 1`.
5. `catalog/introspect.py:introspect_catalog()` uses `sqlalchemy.inspect()` to list tables, columns, PKs, FKs, and comments; it also runs bounded `DISTINCT` queries for up to five sample values per column. This is read-only introspection.
6. `core/startup.py:init_app()` hashes the normalized catalog and compares it with `CatalogStore`. It loads or computes schema-document embeddings, builds the retrieval objects, indexes distinct text values, and constructs the pipeline and local example store.

### Database writes and existing database objects

**The current startup code creates no target-database tables, extensions, or indexes and does not seed data.** Its database work is connection checking, introspection, bounded sample reads, distinct text-value reads, and later read-only queries. `db/init_db.py` is now a deprecated compatibility module: `init_db()` does not run DDL and `seed_data()` refuses writes. `schema/value_catalog.py:ensure_trgm_indexes()` is a compatibility no-op.

Table descriptions are taken from the database's own table comment when one is present. If no comment exists, the fallback is a neutral `"Table {name}."` string. There is no hard-coded domain phrase in the metadata. Business-relevance hints in `TableInfo.to_schema_doc()` are derived dynamically from the table's foreign-key relationships and are only emitted when FK relationships exist; there is no hard-coded domain assumption.

The configured database nevertheless contains artifacts left by the former PostgreSQL implementation. They explain the current count of ten indexed tables:

| Table | Classification |
|---|---|
| `categories` | Domain data |
| `customers` | Domain data |
| `departments` | Domain data |
| `employees` | Domain data |
| `order_items` | Domain data |
| `orders` | Domain data |
| `payments` | Domain data |
| `products` | Domain data |
| `schema_embeddings` | **Internal legacy schema-vector table; no longer used by the current local-vector path** |
| `value_catalog` | **Internal legacy distinct-value table; no longer used by the current local-value path** |

Thus the current sidebar count of 10 is eight domain tables plus two legacy internal tables. The current introspector does not automatically exclude those legacy names, so they can be retrieved and can pollute value matching. They are present in this database; they are not created by current startup.

The live PostgreSQL inspection also found extensions `plpgsql` and `pg_trgm`. `plpgsql` is a PostgreSQL installation extension; `pg_trgm` and the following indexes are legacy objects, not provisioned by current startup:

- `categories`: `categories_category_name_key`, `idx_categories_category_name_trgm`, `idx_categories_name_trgm`
- `customers`: `idx_customers_city_trgm`
- `departments`: `departments_department_name_key`, `idx_departments_department_name_trgm`, `idx_departments_name_trgm`
- `products`: `idx_products_name_trgm`, `idx_products_product_name_trgm`
- `value_catalog`: `uq_value_catalog_table_col`

The live inspector found no non-constraint indexes on `employees`, `orders`, `order_items`, `payments`, or `schema_embeddings`.

### Local files and caches

- `.vector_store/<database-namespace>/catalog.json` stores the normalized catalog, schema hash, embedding-model name, and schema vectors. The namespace hashes a credential-free URL.
- `.vector_store/<database-namespace>/values.json` stores low-cardinality distinct text values and their vectors. Current startup rebuilds these values from the connected database on each process initialization and rewrites this file; it does not restore the value index from this file yet.
- `.vector_store/<database-namespace>/examples.json` is created when a user saves a verified example. No examples file existed in the inspected namespace during this report.
- `description-progress.json` is optional progress for `catalog.describe`; description generation is not run automatically during startup.
- `st.cache_resource` holds the initialized runtime in Streamlit process memory. Sentence Transformer weights are also cached by the model library outside the project directory.
- Root-level `schema_index.json` and `value_catalog.json` are legacy files. Current startup uses the namespaced `.vector_store` files, not these root files.
- `.env` contains settings/secrets and is excluded by `.gitignore`.

No Chroma or FAISS server is used; local JSON plus NumPy vectors provide persistence and similarity scoring.

## 2. Per-question execution order

| Order | File and function | Work |
|---|---|---|
| 1 | `ui/app.py:main()` | Collects the question and calls the cached runtime pipeline on submit. |
| 2 | `pipeline/orchestrator.py:TextToSQLPipeline.run()` | Starts timings and asks `ValueIndex.resolve_question()` to find likely value phrases. |
| 3 | `retrieval/value_index.py:ValueIndex.resolve_question()` / `resolve()` | Searches indexed distinct text values. Exact case-insensitive matches score 1.0; otherwise RapidFuzz WRatio is combined with local vector cosine similarity for indexed low-cardinality values. Weak/close matches become candidates. |
| 4 | `pipeline/orchestrator.py:run()` | Returns early with `ambiguous_values` if any uncertain value remains; the UI can ask the user to confirm it. |
| 5 | `retrieval/schema_retriever.py:HybridSchemaRetriever.retrieve()` | Combines embedding and lexical similarity, then adds foreign-key-related tables. `compact_ddl()` formats the selected subset. |
| 6 | `retrieval/examples.py:ExampleStore.retrieve()` | Retrieves similar verified question/SQL pairs from the current database namespace. |
| 7 | `llm/prompt_builder.py:build_prompt()` | Builds the system/user messages from dialect, selected DDL, resolved values, optional hints, examples, and any correction error. |
| 8 | `llm/generator.py:GroqGenerator.generate()` | Sends those messages to Groq and removes Markdown fences from the response. |
| 9 | `validation/validator.py:validate_sql()` | Parses with the active dialect; requires one SELECT; rejects comments, disallowed statements, unknown tables/columns, and enforces/caps LIMIT. |
| 10 | `db/adapter.py:DatabaseAdapter.explain()` | Runs EXPLAIN where supported; unsupported EXPLAIN falls back without blocking the query. |
| 11 | `db/adapter.py:DatabaseAdapter.run_readonly_query()` | Applies supported read-only/timeout controls and executes through SQLAlchemy, returning at most `MAX_ROWS`. |
| 12 | `llm/generator.py:GroqGenerator.summarize()` | If execution succeeds, sends the question and at most the first 20 result rows for a concise answer. |
| 13 | `ui/app.py:_render_result()` | Renders answer, SQL, rows, errors, timing, value confirmation, and the verified-example button. |

Validation or execution failures are returned to the generation loop as correction text, up to `MAX_RETRIES` retries. Value ambiguity is handled before generation and does not enter the retry loop.

## 3. LLM payload and data boundary

The prompt builder includes only the selected tables' compact DDL, accepted value hints, optional `hints.md`, and retrieved verified examples. It does **not** put sample values from introspection or the full distinct-value catalog into the SQL-generation prompt. An ambiguous candidate list is shown in the UI and is not sent until a user confirms a value.

The following was captured from the example question `What was revenue by electronics category in 2025?` with `Electronics` explicitly confirmed. It is the actual message pair passed to the Groq client; the API did not return generated SQL in this run.

**System message**

```text
You generate SQL for the postgresql dialect. Return SQL only. Generate one read-only SELECT statement. Use only the tables and columns in the supplied schema. Use full table names or consistent aliases, and never invent identifiers. Use resolved values exactly as supplied.
```

**User message**

```text
Question:
What was revenue by electronics category in 2025?

Schema:
TABLE schema_embeddings (id VARCHAR PRIMARY KEY, table_name VARCHAR, description TEXT, relationships JSON, business_relevance TEXT, embedding VARCHAR, created_at TIMESTAMP)
TABLE categories (category_id INTEGER PRIMARY KEY, category_name VARCHAR(100), description VARCHAR(255), created_at TIMESTAMP)
TABLE products (product_id INTEGER PRIMARY KEY, product_name VARCHAR(100), category_id INTEGER REFERENCES categories(category_id), price DOUBLE PRECISION, created_at TIMESTAMP)
TABLE departments (department_id INTEGER PRIMARY KEY, department_name VARCHAR(100), description VARCHAR(255), created_at TIMESTAMP)
TABLE employees (employee_id INTEGER PRIMARY KEY, employee_name VARCHAR(100), department_id INTEGER REFERENCES departments(department_id), salary DOUBLE PRECISION, hire_date TIMESTAMP, created_at TIMESTAMP)
TABLE payments (payment_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), amount DOUBLE PRECISION, payment_status VARCHAR(50), payment_date TIMESTAMP, created_at TIMESTAMP)
TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(customer_id), order_date TIMESTAMP, status VARCHAR(50), created_at TIMESTAMP)
TABLE order_items (order_item_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(order_id), product_id INTEGER REFERENCES products(product_id), quantity INTEGER, unit_price DOUBLE PRECISION, created_at TIMESTAMP)
TABLE customers (customer_id INTEGER PRIMARY KEY, customer_name VARCHAR(100), email VARCHAR(200), city VARCHAR(100), created_at TIMESTAMP)

Resolved values:
- electronics -> categories.category_name = Electronics

Domain hints:
None

Verified examples:
None
```

The example prompt contains the legacy `schema_embeddings` definition because that old internal table is currently visible to introspection/retrieval. It does not include `value_catalog` for this particular retrieval.

**Not sent:** `DATABASE_URL`, database credentials, `GROQ_API_KEY`, local embedding vectors, the complete catalog, or complete result sets. Table/column names and only the schema subset selected for a question are sent. Relevant resolved values are sent verbatim, so any sensitive value a user explicitly asks to resolve can become part of the prompt. After SQL execution, the separate summarization call sends the question and up to 20 result rows; therefore result data is not wholly kept local. This report's manual diagnostics did not send their result rows to Groq.

## 4. Business definitions and value matching

There is no `hints.md` in the workspace at report time. `llm/prompt_builder.py:build_prompt()` reads that optional root file, but no current revenue definition is configured there or in the active schema context. Consequently, “revenue” is undefined for the LLM. Add a domain definition to `hints.md` before relying on revenue answers; for example, explicitly state whether revenue is `SUM(quantity * unit_price)`, which order/payment statuses count, and how refunds are handled.

Value matching is implemented in `retrieval/value_index.py`, with large-column substring search delegated to `db/adapter.py:DatabaseAdapter.search_values()`. Distinct values for text columns below the configured cardinality threshold are stored with local embeddings. RapidFuzz WRatio is the dominant signal; vector cosine contributes a smaller ranking signal. Exact case-insensitive matches receive confidence 1.0. A match is accepted at confidence at least 0.88 and a lead of at least 0.08; lower/close candidates from 0.65 may be returned for UI confirmation. High-cardinality columns are searched using reflected SQLAlchemy expressions and a bound case-insensitive `LIKE` pattern, then reranked. The current broad phrase search can mistake fragments of questions or values from internal tables for candidate values; this occurred in the six diagnostic runs below.

## 5. Why ten tables are indexed

The configured live PostgreSQL database has eight domain tables plus the two legacy internal tables listed in section 1. The current code no longer needs `schema_embeddings` or `value_catalog`, but because neither name is in `EXCLUDED_TABLES` and the current catalog does not apply an automatic internal-table exclusion, both are counted and can be retrieved. This is why the sidebar reports ten. The prior prompt example selected nine of those ten; the exact set varies by question.

**Action required when switching databases:** audit the target database for legacy, internal, or system tables and add their names to `EXCLUDED_TABLES` in `.env`. This prevents unrelated tables from appearing in schema retrieval results and polluting value matching. For the current PostgreSQL setup, adding `schema_embeddings,value_catalog` to `EXCLUDED_TABLES` would reduce the indexed count from ten to the correct eight domain tables.

## 6. Database-specific versus generic

- `db/adapter.py` owns connection creation, dialect identification, the SQLAlchemy-to-SQLGlot `mssql`/`tsql` mapping, read-only/timeout controls, EXPLAIN, and reflected fallback value search. PostgreSQL, MySQL, SQLite, and SQL Server-specific execution details belong here.
- `schema/metadata.py` produces table descriptions from the database's own table comments (`TableInfo.description = table_comment or f"Table {name}."`) and derives business-relevance hints from FK relationships only. It contains no hard-coded domain names, table names, or column assumptions; it works correctly with any database.
- `catalog/introspect.py`, `catalog/store.py`, `retrieval/schema_retriever.py`, `retrieval/value_index.py`, `retrieval/examples.py`, `llm/prompt_builder.py`, `llm/generator.py`, `validation/validator.py`, and `pipeline/orchestrator.py` use SQLAlchemy inspection, local data structures, and the dialect supplied by the adapter. They do not assume any specific domain table names.
- A matching SQLAlchemy driver must be installed for the chosen URL. No application code changes are required when changing `DATABASE_URL`.

## Six live query diagnostics

The six questions below were run against the configured PostgreSQL database. The normal conversational pipeline did **not** produce SQL: its value resolver classified broad question fragments as ambiguous, and, when run with value resolution bypassed for diagnostic purposes, Groq returned the generic `The language model is temporarily unavailable.` after four attempts per question. A Groq key was configured, but the application intentionally suppresses provider details, so the exact provider-side cause was not observable here.

To still verify the live data, the SQL below was written as a read-only diagnostic equivalent from the inspected schema and run through `DatabaseAdapter.run_readonly_query()`. These are **not LLM-generated SQL** and must not be mistaken for successful natural-language pipeline outputs. The revenue queries assume gross line revenue `SUM(quantity * unit_price)` across all statuses unless the query explicitly filters a year; that is only a diagnostic assumption, not a configured business definition. Value hints shown are the active resolver's output, including false positives where present.

### 1. Revenue by Electronics category in 2025

Retrieved: `schema_embeddings`, `categories`, `products`, `departments`, `employees`, `payments`, `orders`, `order_items`, `customers`.

Resolver: accepted `electronics -> categories.category_name = Electronics`; also incorrectly accepted `category -> value_catalog.column_name = category_name` and returned unrelated ambiguous phrases. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT c.category_name, SUM(oi.quantity * oi.unit_price) AS gross_line_revenue
FROM categories AS c
JOIN products AS p ON p.category_id = c.category_id
JOIN order_items AS oi ON oi.product_id = p.product_id
JOIN orders AS o ON o.order_id = oi.order_id
WHERE LOWER(c.category_name) = LOWER('Electronics')
  AND o.order_date >= DATE '2025-01-01'
  AND o.order_date < DATE '2026-01-01'
GROUP BY c.category_name
LIMIT 100
```

Result: `Electronics`, gross line revenue `3610.0` (1 row).

### 2. Product category with highest revenue

Retrieved: `schema_embeddings`, `products`, `categories`, `order_items`, `customers`, `value_catalog`, `employees`, `departments`, `orders`.

Resolver: no useful value hint; it incorrectly accepted `category -> value_catalog.column_name = category_name` and returned ambiguous phrase matches. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT c.category_name, SUM(oi.quantity * oi.unit_price) AS gross_line_revenue
FROM categories AS c
JOIN products AS p ON p.category_id = c.category_id
JOIN order_items AS oi ON oi.product_id = p.product_id
GROUP BY c.category_name
ORDER BY gross_line_revenue DESC
LIMIT 100
```

Result: Electronics `5410.0`; Home & Garden `500.0`; Clothing `405.0`; Books `245.0`; Sports & Outdoors `200.0` (5 rows).

### 3. Number of orders for each customer

Retrieved: `schema_embeddings`, `orders`, `customers`, `order_items`, `value_catalog`, `departments`, `payments`, `employees`, `products`.

Resolver: no accepted value hints; returned ambiguous question fragments. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT c.customer_name, COUNT(o.order_id) AS order_count
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.customer_name
ORDER BY c.customer_name
LIMIT 100
```

Result: Alice Retail `3`; Bob Wholesale `3`; Carol Shop `2`; Dave Distributors `2`; Eve Enterprises `2` (5 rows).

### 4. Department with highest average employee salary

Retrieved: `employees`, `departments`, `schema_embeddings`, `value_catalog`, `payments`, `order_items`, `orders`, `customers`, `products`.

Resolver: no accepted value hints; returned ambiguous question fragments. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT d.department_name, AVG(e.salary) AS average_salary
FROM departments AS d
JOIN employees AS e ON e.department_id = d.department_id
GROUP BY d.department_id, d.department_name
ORDER BY average_salary DESC
LIMIT 100
```

Result: Engineering `116666.67`; Finance `112500.0`; Sales `88500.0`; Marketing `79500.0`; Human Resources `65000.0` (5 rows). Engineering is highest.

### 5. Monthly revenue for 2025

Retrieved: `orders`, `payments`, `employees`, `schema_embeddings`, `departments`, `customers`, `products`, `categories`.

Resolver: no accepted value hints; returned ambiguous phrase fragments, including descriptions. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT DATE_TRUNC('month', o.order_date) AS revenue_month,
       SUM(oi.quantity * oi.unit_price) AS gross_line_revenue
FROM orders AS o
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE o.order_date >= DATE '2025-01-01'
  AND o.order_date < DATE '2026-01-01'
GROUP BY DATE_TRUNC('month', o.order_date)
ORDER BY revenue_month
LIMIT 100
```

Result: March 2025 `200.0`; April 2025 `2040.0`; May 2025 `2720.0` (3 rows).

### 6. Products that have never been ordered

Retrieved: `products`, `order_items`, `schema_embeddings`, `orders`, `customers`, `categories`, `value_catalog`, `payments`.

Resolver: no accepted value hints; returned ambiguous product/order phrase fragments. Production pipeline: paused before generation.

Diagnostic SQL:

```sql
SELECT p.product_id, p.product_name
FROM products AS p
WHERE NOT EXISTS (
    SELECT 1
    FROM order_items AS oi
    WHERE oi.product_id = p.product_id
)
ORDER BY p.product_name
LIMIT 100
```

Result: no rows; every product in the current database has at least one order item.

## Run notes

The diagnostic SELECTs above were run on the live database with `MAX_ROWS=100` via the SQLAlchemy adapter. The report does not modify the database. The SQL-generation failure and false-positive resolver behavior are current observed limitations, not successful pipeline results.
