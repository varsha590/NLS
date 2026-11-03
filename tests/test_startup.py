"""Startup tests for database-independent local indexing."""

import sqlalchemy as sa

from config.settings import Settings
from core import startup
from db.adapter import DatabaseAdapter


class FakeEmbeddingModel:
    """Deterministic embedding model for startup tests."""

    model_name = "fake-model"
    dim = 4

    def __init__(self, model_name):
        self.model_name = model_name

    def embed(self, texts):
        import numpy as np

        return np.ones((len(texts), 4), dtype=float)


def _settings(tmp_path):
    return Settings(
        database_url="sqlite:///:memory:",
        groq_api_key="",
        llm_model="mock-model",
        embedding_model="fake-model",
        vector_store_path=str(tmp_path),
        schema_top_k=4,
        value_top_k=3,
        max_rows=20,
        query_timeout_seconds=5,
        max_retries=1,
        allowed_schemas=(),
        excluded_tables=(),
        value_cardinality_threshold=10,
    )


def _configure_startup(tmp_path, monkeypatch, engine):
    monkeypatch.setattr(startup.Settings, "from_env", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        startup,
        "DatabaseAdapter",
        lambda database_url, timeout: DatabaseAdapter(database_url, timeout, engine=engine),
    )
    monkeypatch.setattr(startup, "EmbeddingModel", FakeEmbeddingModel)
    startup._runtime.clear()


def test_init_app_indexes_sqlite_catalog_locally_and_reuses_cache(tmp_path, monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "notes",
        metadata,
        sa.Column("note_id", sa.Integer, primary_key=True),
        sa.Column("label", sa.String),
    )
    metadata.create_all(engine)
    _configure_startup(tmp_path, monkeypatch, engine)

    first = startup.init_app()
    first_status = first["catalog_status"]
    second = startup.init_app()

    assert first_status == "indexed"
    assert second["catalog_status"] == "cached"
    assert second["adapter"].get_dialect() == "sqlite"
    assert second["indexed_tables"] == 1
    assert not sa.inspect(engine).has_table("schema_embeddings")


def test_force_reindex_rebuilds_local_catalog(tmp_path, monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("records", metadata, sa.Column("record_id", sa.Integer))
    metadata.create_all(engine)
    _configure_startup(tmp_path, monkeypatch, engine)

    startup.init_app()
    refreshed = startup.init_app(force=True)

    assert refreshed["catalog_status"] == "indexed"
