"""Target-database read-only contract tests for startup and pipeline execution."""

from __future__ import annotations

import os
import re

import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from config.settings import Settings
from core import startup
from db.adapter import DatabaseAdapter


class ContractEmbedder:
    model_name = "contract-embedder"
    dim = 4

    def __init__(self, model_name: str):
        self.model_name = model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for index, character in enumerate(text.encode("utf-8")):
                matrix[row, index % self.dim] += character + 1
        return matrix


class CountGenerator:
    def __init__(self, sql: str = "SELECT COUNT(*) AS result_count FROM synthetic_records"):
        self.sql = sql

    def generate(self, messages: list[dict[str, str]]) -> str:
        return self.sql


def _settings(database_url: str, vector_path) -> Settings:
    return Settings(
        database_url=database_url,
        groq_api_key="",
        llm_model="contract-model",
        embedding_model="contract-embedder",
        vector_store_path=str(vector_path),
        schema_top_k=4,
        value_top_k=3,
        query_timeout_seconds=5,
        max_retries=0,
        allowed_schemas=(),
        excluded_tables=(),
        value_cardinality_threshold=10,
        example_candidate_limit=500,
    )


def _install_startup_fakes(monkeypatch, database_url, vector_path, engine):
    monkeypatch.setattr(startup.Settings, "from_env", lambda: _settings(database_url, vector_path))
    monkeypatch.setattr(
        startup,
        "DatabaseAdapter",
        lambda url, timeout: DatabaseAdapter(url, timeout, engine=engine),
    )
    monkeypatch.setattr(startup, "EmbeddingModel", ContractEmbedder)
    monkeypatch.setattr(startup, "GroqGenerator", lambda *args: CountGenerator())
    startup._runtime.clear()


def _assert_allowed(statements: list[str], dialect: str) -> None:
    for statement in statements:
        normalized = statement.strip().upper()
        if not normalized:
            continue
        first_word = normalized.split(None, 1)[0].rstrip(";(")
        allowed = first_word in {
            "SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "ROLLBACK", "COMMIT", "BEGIN"
        }
        if first_word == "START" and normalized.startswith("START TRANSACTION"):
            allowed = True
        if first_word == "SET":
            allowed = any(
                marker in normalized
                for marker in ("READ ONLY", "READ_ONLY", "STATEMENT_TIMEOUT", "MAX_EXECUTION_TIME")
            )
        if first_word == "PRAGMA":
            pragma_name = normalized.split(None, 1)[1].split("=", 1)[0].split("(", 1)[0].strip().rsplit(".", 1)[-1]
            allowed = pragma_name in {
                "QUERY_ONLY",
                "TABLE_INFO",
                "TABLE_XINFO",
                "FOREIGN_KEY_LIST",
                "INDEX_LIST",
                "INDEX_INFO",
                "INDEX_XINFO",
                "DATABASE_LIST",
                "TABLE_LIST",
            }
        assert allowed, f"Unexpected {dialect} statement verb: {first_word}"


def _capture_question(engine, runtime):
    table_info = next(iter(runtime["metadata"].tables.values()))
    quote = engine.dialect.identifier_preparer.quote
    table_sql = quote(table_info.name.rsplit(".", 1)[-1])
    if table_info.schema:
        table_sql = f"{quote(table_info.schema)}.{table_sql}"
    runtime["pipeline"].generator = CountGenerator(
        f"SELECT COUNT(*) AS result_count FROM {table_sql}"
    )
    result = runtime["pipeline"].run(f"count all {table_info.name}")
    assert not result.errors
    assert result.sql


def test_sqlite_startup_and_full_question_use_readonly_target_statements(
    tmp_path, monkeypatch
):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    table = sa.Table(
        "synthetic_records",
        metadata,
        sa.Column("synthetic_key", sa.Integer, primary_key=True),
        sa.Column("generic_label", sa.String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{"synthetic_key": 1, "generic_label": "sentinel"}])

    statements: list[str] = []
    sa.event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    _install_startup_fakes(monkeypatch, "sqlite:///:memory:", tmp_path, engine)
    runtime = startup.init_app(force=True)
    _capture_question(engine, runtime)

    _assert_allowed(statements, "sqlite")


def test_mysql_readonly_user_startup_and_question_use_readonly_statements(
    tmp_path, monkeypatch
):
    database_url = os.getenv("NLS_READONLY_MYSQL_URL") or os.getenv("DATABASE_URL", "")
    if not database_url or make_url(database_url).get_backend_name() != "mysql":
        pytest.skip("Set NLS_READONLY_MYSQL_URL to the SELECT-only hiresanta URL.")
    if make_url(database_url).username != "nls_ro":
        pytest.skip("MySQL contract test requires the nls_ro account.")

    engine = sa.create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        inspector = sa.inspect(engine)
        if not inspector.get_table_names():
            pytest.skip("MySQL fixture database has no tables.")
    except sa.exc.SQLAlchemyError:
        engine.dispose()
        pytest.skip("SELECT-only MySQL database is unavailable.")

    statements: list[str] = []
    sa.event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, params, context, many: statements.append(statement))
    _install_startup_fakes(monkeypatch, database_url, tmp_path, engine)
    runtime = startup.init_app(force=True)
    _capture_question(engine, runtime)

    _assert_allowed(statements, "mysql")
    engine.dispose()


def test_postgresql_runtime_source_has_no_target_write_or_pgvector_sql():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = ("core/startup.py", "db/adapter.py")
    source = "\n".join((root / path).read_text(encoding="utf-8") for path in paths)
    forbidden = re.compile(
        r"CREATE\s+(?:EXTENSION|TABLE|INDEX)|\bHNSW\b|<=>|::\s*vector|CAST\s*\([^)]*\s+AS\s+vector",
        re.IGNORECASE,
    )
    assert forbidden.search(source) is None