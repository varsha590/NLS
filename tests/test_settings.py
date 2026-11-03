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
        "MAX_ROWS": "30",
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
    assert settings.max_rows == 30


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