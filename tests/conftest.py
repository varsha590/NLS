"""Non-secret defaults for tests that exercise environment-backed settings."""

from __future__ import annotations

import os


_TEST_DEFAULTS = {
    "DATABASE_URL": "sqlite:///:memory:",
    "LLM_MODEL": "test-model",
    "EMBEDDING_MODEL": "test-embedding-model",
    "VECTOR_STORE_PATH": ".test-vector-store",
    "SCHEMA_TOP_K": "8",
    "VALUE_TOP_K": "5",
    "VALUE_CARDINALITY_THRESHOLD": "50",
    
    "QUERY_TIMEOUT_SECONDS": "15",
    "MAX_RETRIES": "0",
    "QDRANT_URL": "http://127.0.0.1:6333",
    "QDRANT_COLLECTION": "nls_test_documents",
}

for _name, _value in _TEST_DEFAULTS.items():
    os.environ.setdefault(_name, _value)