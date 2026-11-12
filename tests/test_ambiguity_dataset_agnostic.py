"""Dataset-agnostic ambiguity and context-size tests.

Two unrelated synthetic schemas prove the behavior is derived from schema data,
not from any one client's table or column names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config.settings import Settings
from retrieval.qdrant_retriever import (
    _dataset_ubiquitous_columns,
    _normalize_tokens,
    retrieve,
)
from schema.context import build_query_context
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo


def _table(name: str, columns: list[str]) -> TableInfo:
    return TableInfo(
        name,
        "",
        [ColumnInfo(column, "TEXT") for column in columns],
        [],
        [],
    )


def _schema(mapping: dict[str, list[str]]) -> SchemaMetadata:
    return SchemaMetadata({name: _table(name, columns) for name, columns in mapping.items()})


def _payloads(mapping: dict[str, list[str]]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for table_name, columns in mapping.items():
        payloads.append(
            {"document_type": "table", "table_name": table_name, "column_name": None}
        )
    for table_name, columns in mapping.items():
        for column_name in columns:
            payloads.append(
                {
                    "document_type": "column",
                    "table_name": table_name,
                    "column_name": column_name,
                }
            )
    return payloads


class FakeStore:
    def __init__(self, hits: dict[str, list[dict[str, object]]] | None = None,
                 schema_payloads: list[dict[str, object]] | None = None) -> None:
        self.hits = hits or {}
        self.schema_payloads = schema_payloads or []
        self._ubiquitous_column_cache: dict[tuple, set[str]] = {}

    def _search(self, kind: str) -> list[dict[str, object]]:
        return list(self.hits.get(kind, []))

    def search_table(self, *args):
        return self._search("table")

    def search_column(self, *args):
        return self._search("column")

    def search_relationship(self, *args):
        return self._search("relationship")

    def search_master_value(self, *args):
        return self._search("master_value")

    def _scroll_metadata(self, document_type, tenant_id=None, dataset_id=None):
        return list(self.schema_payloads)


def _settings(**overrides) -> Settings:
    values = {
        "groq_api_key": "",
        "llm_model": "test-model",
        "embedding_model": "test-embedding",
        "vector_store_path": ".",
        "schema_top_k": 8,
        "value_top_k": 5,
        "query_timeout_seconds": 5,
        "max_retries": 0,
        "allowed_schemas": (),
        "excluded_tables": (),
        "value_cardinality_threshold": 50,
    }
    values.update(overrides)
    return Settings(**values)


def _run(metadata: SchemaMetadata, query: str, scores: dict[str, float],
         mapping: dict[str, list[str]], settings: Settings | None = None):
    hits = {"table": [{"table_name": name, "similarity": score} for name, score in scores.items()]}
    store = FakeStore(hits=hits, schema_payloads=_payloads(mapping))
    return retrieve(
        metadata,
        query,
        selected_k=3,
        max_tables=8,
        qdrant_store=store,
        qdrant_tenant_id="tenant",
        qdrant_dataset_id="dataset",
        qdrant_embedding_model_name="model",
        qdrant_embedding_dimension=384,
        qdrant_dataset_metadata_path="dataset.json",
        query_vector=[0.0] * 384,
        settings=settings,
    )


SHOP = {
    "orders": ["id", "created_at", "customer_id", "status"],
    "customers": ["id", "created_at", "name"],
    "payments": ["id", "created_at", "status", "amount"],
    "products": ["id", "created_at", "name"],
    "categories": ["id", "created_at", "name"],
}

HOSPITAL = {
    "patients": ["id", "created_at", "full_name"],
    "doctors": ["id", "created_at", "specialty"],
    "appointments": ["id", "created_at", "scheduled_at"],
    "departments": ["id", "created_at", "department_name"],
    "rooms": ["id", "created_at", "room_number"],
}


@pytest.mark.parametrize("mapping", [SHOP, HOSPITAL], ids=["shop", "hospital"])
def test_clear_winner_with_shared_ubiquitous_columns_is_not_ambiguous(mapping):
    metadata = _schema(mapping)
    first = next(iter(mapping))
    scores = {name: 0.10 for name in mapping}
    scores[first] = 0.95
    result = _run(metadata, "list all records", scores, mapping)
    assert result.ambiguity_flag is False


def test_near_tie_still_requires_clarification():
    metadata = _schema(SHOP)
    scores = {
        "orders": 0.50,
        "customers": 0.45,
        "payments": 0.40,
        "products": 0.10,
        "categories": 0.05,
    }
    result = _run(metadata, "list all records", scores, SHOP)
    assert result.ambiguity_flag is True


@pytest.mark.parametrize(
    ("query", "column"),
    [("customers", "customer_name"), ("categories", "category_label")],
)
def test_plural_query_token_matches_singular_column_token(query, column):
    mapping = {
        "alpha": ["id", "code", column],
        "beta": ["id", "code", "order_name"],
        "gamma": ["id", "gamma_label"],
        "delta": ["id", "delta_label"],
    }
    metadata = _schema(mapping)
    scores = {"alpha": 0.50, "beta": 0.45, "gamma": 0.10, "delta": 0.05}
    result = _run(metadata, query, scores, mapping)
    assert result.ambiguity_flag is False


def test_id_at_half_of_tables_is_not_treated_as_ubiquitous():
    mapping = {
        "alpha": ["id", "alpha_code"],
        "beta": ["id", "beta_code"],
        "gamma": ["gamma_key"],
        "delta": ["delta_key"],
    }
    metadata = _schema(mapping)
    store = FakeStore(schema_payloads=_payloads(mapping))
    ubiquitous = _dataset_ubiquitous_columns(
        store, "tenant", "dataset", metadata, 0.5
    )
    assert ubiquitous == set()
    scores = {"alpha": 0.50, "beta": 0.45, "gamma": 0.10, "delta": 0.05}
    result = _run(metadata, "list all records", scores, mapping)
    assert result.ambiguity_flag is True


def test_column_present_in_most_tables_is_ignored_regardless_of_name():
    mapping = {
        "alpha": ["record_key", "alpha_value"],
        "beta": ["record_key", "beta_value"],
        "gamma": ["record_key", "gamma_value"],
    }
    metadata = _schema(mapping)
    store = FakeStore(schema_payloads=_payloads(mapping))
    ubiquitous = _dataset_ubiquitous_columns(
        store, "tenant", "dataset", metadata, 0.5
    )
    assert ubiquitous == {"record_key"}
    scores = {"alpha": 0.50, "beta": 0.45, "gamma": 0.40}
    result = _run(metadata, "list all records", scores, mapping)
    assert result.ambiguity_flag is False


def test_llm_context_is_limited_to_context_top_tables():
    mapping = {
        f"table_{index}": [f"field_{index}_a", f"field_{index}_b"]
        for index in range(6)
    }
    metadata = _schema(mapping)
    scores = {name: 1.0 - index * 0.1 for index, name in enumerate(mapping)}
    result = _run(
        metadata,
        "list all records",
        scores,
        mapping,
        settings=_settings(context_top_tables=3),
    )
    assert len(result.tables) <= 3
    context = build_query_context(metadata, result.tables, [])
    included = [name for name in mapping if f"{name}:" in context]
    assert included == result.tables


def test_no_dataset_specific_identifiers_in_source():
    dataset_names = [
        "munibigiri",
        "vCombo",
        "fComboPrice",
        "tComboDescription",
        "vJobName",
        "fJobAmount",
        "vCategoryName",
        "iStateId",
        "vCityName",
        "vSubscriptionPlan",
        "dExpiryDate",
        "eNotificationType",
        "iServiceId",
        "vQuestion",
        "iCategoriesId",
        "vSubCategoryName",
        "fPrice",
        "eRecurringType",
        "vStaticTypeNot",
        "discount_coupons",
        "eservicetype",
# Synthetic datasets (school, warehouse, clinic)
    "students",
    "courses",
    "enrollments",
    "products",
    "suppliers",
    "orders",
    "patients",
    "appointments",
    "doctors",
    "student_id",
    "course_id",
    "grade",
    "product_id",
    "student_name",
    ]
    root = Path(__file__).resolve().parents[1]
    source_files = [
        path
        for path in root.rglob("*.py")
        if not any(
            part in {".venv", ".git", "tests", "__pycache__", "datasets"}
            for part in path.parts
        )
    ]
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in dataset_names) + r")\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in source_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            offenders.append(f"{path.relative_to(root)}:{match.group(0)}")
    assert offenders == []


def test_normalization_handles_plurals_and_type_prefixes():
    assert _normalize_tokens("customers") == ["customer"]
    assert _normalize_tokens("categories") == ["category"]
    assert _normalize_tokens("states") == ["state"]
    assert _normalize_tokens("vCityName") == ["city", "name"]
    assert _normalize_tokens("iStateId") == ["state", "id"]
    assert _normalize_tokens("e_status") == ["status"]
