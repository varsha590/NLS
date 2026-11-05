"""Environment settings must not be overridden by in-code model or URL defaults."""

import pytest

from config import settings as settings_module
from config.settings import Settings, SettingsError


def _set_required_environment(monkeypatch):
    values = {
        "DATABASE_URL": "sqlite:///environment-configured.db",
        "GROQ_API_KEY": "test-key",
        "LLM_MODEL": "configured-llm",
        "EMBEDDING_MODEL": "configured-embedder",
        "VECTOR_STORE_PATH": ".test-vector-store",
        "SCHEMA_TOP_K": "4",
        "VALUE_TOP_K": "3",
        "VALUE_CARDINALITY_THRESHOLD": "12",
"QUERY_TIMEOUT_SECONDS": "6",
        "MAX_RETRIES": "2",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setattr(settings_module, "load_dotenv", lambda **kwargs: None)


def test_settings_uses_environment_values_without_hidden_defaults(monkeypatch):
    _set_required_environment(monkeypatch)

    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///environment-configured.db"
    assert settings.llm_model == "configured-llm"
    assert settings.embedding_model == "configured-embedder"
    assert settings.schema_top_k == 4
    


def test_legacy_groq_model_is_environment_only_migration_alias(monkeypatch):
    _set_required_environment(monkeypatch)
    monkeypatch.delenv("LLM_MODEL")
    monkeypatch.setenv("GROQ_MODEL", "legacy-env-model")

    assert Settings.from_env().llm_model == "legacy-env-model"


def test_missing_groq_key_is_not_replaced_with_an_in_code_value(monkeypatch):
    _set_required_environment(monkeypatch)
    monkeypatch.delenv("GROQ_API_KEY")

    assert Settings.from_env().groq_api_key == ""


def test_missing_database_or_model_configuration_fails_fast(monkeypatch):
    _set_required_environment(monkeypatch)
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("LLM_MODEL")
    monkeypatch.delenv("GROQ_MODEL", raising=False)

    with pytest.raises(SettingsError, match="DATABASE_URL.*LLM_MODEL"):
        Settings.from_env()


def test_phase3_index_settings_have_safe_defaults_and_environment_overrides(monkeypatch):
    _set_required_environment(monkeypatch)
    monkeypatch.delenv("INDEX_REFRESH_TTL_HOURS", raising=False)
    monkeypatch.delenv("INDEX_SCAN_WORKERS", raising=False)
    monkeypatch.delenv("EMBED_CACHE_MAX_ENTRIES", raising=False)

    defaults = Settings.from_env()

    monkeypatch.setenv("INDEX_REFRESH_TTL_HOURS", "0")
    monkeypatch.setenv("INDEX_SCAN_WORKERS", "3")
    monkeypatch.setenv("EMBED_CACHE_MAX_ENTRIES", "5000")
    overrides = Settings.from_env()

    assert defaults.index_refresh_ttl_hours == 24
    assert defaults.index_scan_workers == 1
    assert defaults.embed_cache_max_entries == 250000
    assert overrides.index_refresh_ttl_hours == 0
    assert overrides.index_scan_workers == 3
    assert overrides.embed_cache_max_entries == 5000