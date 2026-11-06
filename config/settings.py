"""Environment-backed application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

class SettingsError(ValueError):
    """Raised when required environment-backed configuration is missing."""


def _csv_setting(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    """Validated runtime settings loaded from the process environment."""

    groq_api_key: str
    llm_model: str
    embedding_model: str
    vector_store_path: str
    schema_top_k: int
    value_top_k: int
    query_timeout_seconds: int
    max_retries: int
    allowed_schemas: tuple[str, ...]
    excluded_tables: tuple[str, ...]
    value_cardinality_threshold: int
    example_candidate_limit: int = 500
    index_refresh_ttl_hours: float = 24.0
    index_scan_workers: int = 1
    embed_cache_max_entries: int = 250000
    value_phrase_span_limit: int = 40
    value_top_k_per_span: int = 5
    value_high_cache_max_values: int = 20000
    value_high_cache_total_values: int = 200000
    value_high_db_lookup_limit: int = 20
    send_high_cardinality_values_to_llm: bool = False
    qdrant_url: str = field(default="http://127.0.0.1:6333", repr=False)
    qdrant_api_key: str = field(default="", repr=False)
    qdrant_collection: str = "nls_documents"
    dominance_ratio: float = 2.0
    ubiquitous_column_ratio: float = 0.5
    ignored_columns: tuple[str, ...] = ()
    context_top_tables: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings without reading files or using in-code model defaults."""
        llm_model = os.getenv("LLM_MODEL") or os.getenv("GROQ_MODEL") or ""
        required = {
            "LLM_MODEL (or legacy GROQ_MODEL)": llm_model,
            "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL"),
            "VECTOR_STORE_PATH": os.getenv("VECTOR_STORE_PATH"),
            "SCHEMA_TOP_K": os.getenv("SCHEMA_TOP_K"),
            "VALUE_TOP_K": os.getenv("VALUE_TOP_K"),
            "VALUE_CARDINALITY_THRESHOLD": os.getenv("VALUE_CARDINALITY_THRESHOLD"),
            "QUERY_TIMEOUT_SECONDS": os.getenv("QUERY_TIMEOUT_SECONDS"),
            "MAX_RETRIES": os.getenv("MAX_RETRIES"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise SettingsError(
                "Missing required environment settings: " + ", ".join(missing)
            )
        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            llm_model=llm_model,
            embedding_model=os.environ["EMBEDDING_MODEL"],
            vector_store_path=os.environ["VECTOR_STORE_PATH"],
            schema_top_k=max(1, int(os.environ["SCHEMA_TOP_K"])),
            value_top_k=max(1, int(os.environ["VALUE_TOP_K"])),
            query_timeout_seconds=max(1, int(os.environ["QUERY_TIMEOUT_SECONDS"])),
            max_retries=max(0, int(os.environ["MAX_RETRIES"])),
            allowed_schemas=_csv_setting("ALLOWED_SCHEMAS"),
            excluded_tables=_csv_setting("EXCLUDED_TABLES"),
            value_cardinality_threshold=max(
                1, int(os.environ["VALUE_CARDINALITY_THRESHOLD"])
            ),
            example_candidate_limit=max(
                1, int(os.getenv("EXAMPLE_CANDIDATE_LIMIT", "500"))
            ),
            index_refresh_ttl_hours=max(
                0.0, float(os.getenv("INDEX_REFRESH_TTL_HOURS", "24"))
            ),
            index_scan_workers=min(
                8, max(1, int(os.getenv("INDEX_SCAN_WORKERS", "1")))
            ),
            embed_cache_max_entries=max(
                1, int(os.getenv("EMBED_CACHE_MAX_ENTRIES", "250000"))
            ),
            value_phrase_span_limit=max(
                1, int(os.getenv("VALUE_PHRASE_SPAN_LIMIT", "40"))
            ),
            value_top_k_per_span=max(
                1, int(os.getenv("VALUE_TOP_K_PER_SPAN", "5"))
            ),
            value_high_cache_max_values=max(
                1, int(os.getenv("VALUE_HIGH_CACHE_MAX_VALUES", "20000"))
            ),
            value_high_cache_total_values=max(
                1, int(os.getenv("VALUE_HIGH_CACHE_TOTAL_VALUES", "200000"))
            ),
            value_high_db_lookup_limit=max(
                1, int(os.getenv("VALUE_HIGH_DB_LOOKUP_LIMIT", "20"))
            ),
            send_high_cardinality_values_to_llm=(
                os.getenv("SEND_HIGH_CARDINALITY_VALUES_TO_LLM", "false").casefold()
                in {"1", "true", "yes", "on"}
            ),
            qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "nls_documents"),
            dominance_ratio=max(0.0, float(os.getenv("DOMINANCE_RATIO", "2.0"))),
            ubiquitous_column_ratio=min(
                1.0,
                max(0.0, float(os.getenv("UBIQUITOUS_COLUMN_RATIO", "0.5"))),
            ),
            ignored_columns=_csv_setting("IGNORED_COLUMNS"),
            context_top_tables=max(1, int(os.getenv("CONTEXT_TOP_TABLES", "3"))),
        )