"""Table-driven unit and integration tests for Phase 1 automated deny-first classifier."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import sqlalchemy as sa

from catalog.classifier import (
    ColumnClass,
    classify_column,
    get_column_stats,
    is_flag_like_options,
    is_text_type,
    parse_enum_options,
    reviewable_sensitive_name_tokens,
    split_identifier_tokens,
)
from catalog.introspect import introspect_catalog
from config import data_policy
from db.adapter import DatabaseAdapter
from pipeline.orchestrator import PipelineResult, TextToSQLPipeline, ValueSafetyError
from retrieval.schema_retriever import HybridSchemaRetriever
from retrieval.value_index import ValueIndex
from schema.documents import build_column_document, build_table_document
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo, is_internal_table_name
from validation.validator import ValidationError, validate_sql


# ---------------------------------------------------------------------------
# 1. Sensitive-name patterns: positive and negative cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "col_name,expected_blocked",
    [
        # Positive cases (must be BLOCKED)
        ("password", True),
        ("user_password", True),
        ("passwordHash", True),
        ("passwd", True),
        ("pwd", True),
        ("secret_key", True),
        ("api_key", True),
        ("apiKey", True),
        ("session_token", True),
        ("sessionToken", True),
        ("auth_token", True),
        ("otp_code", True),
        ("email", True),
        ("user_email", True),
        ("emailVerifiedAt", True),
        ("phone", True),
        ("mobile_number", True),
        ("contact_person", True),
        ("contactPersonName", True),
        ("home_address", True),
        ("ssn", True),
        ("user_ssn", True),
        ("aadhaar_number", True),
        ("aadhar_card", True),
        ("pan", True),
        ("pan_number", True),
        ("panNumber", True),
        ("CompanyPAN", True),
        ("credit_card", True),
        ("card_number", True),
        ("account_no", True),
        ("accountNo", True),
        ("customer_account_no", True),
        ("bank_ifsc", True),
        ("upi_id", True),
        ("ip_addr", True),
        ("client_ip_addr", True),
        ("dob", True),
        ("user_dob", True),
        ("date_of_birth", True),
        ("birth_date", True),
        ("loc_lat", True),
        ("userLat", True),
        ("loc_lng", True),
        ("userLng", True),

        # Negative cases (must NOT be blocked)
        ("company", False),          # Does NOT match 'pan'
        ("company_name", False),     # Does NOT match 'pan'
        ("companyName", False),      # Does NOT match 'pan'
        ("translate", False),        # Does NOT match 'lat'
        ("translation_id", False),   # Does NOT match 'lat'
        ("japan_origin", False),     # Does NOT match 'pan'
        ("status", False),
        ("category_name", False),
        ("publisher_name", False),
        ("description", False),      # Skipped as free-text, not blocked
        ("created_at", False),
        ("updated_at", False),
    ],
)
def test_sensitive_name_patterns_positive_and_negative(col_name: str, expected_blocked: bool):
    """Verify word-boundary token splitting prevents false positives while catching true positives."""
    col_class, reason = classify_column(
        table_name="test_table",
        column_name=col_name,
        sql_type=sa.String(50),
        distinct_count=10,
    )
    is_blocked = (col_class == ColumnClass.BLOCKED)
    assert is_blocked == expected_blocked, f"Column '{col_name}' expected blocked={expected_blocked}, got {col_class} ({reason})"


# ---------------------------------------------------------------------------
# 2. Default-deny for unknown or unclassifiable column types
# ---------------------------------------------------------------------------

def test_default_deny_unknown_column_types():
    """Unknown or unclassifiable types must evaluate to SKIP, never allow."""
    # Opaque custom type without count
    col_class, reason = classify_column(
        table_name="users",
        column_name="metadata_blob",
        sql_type="OPAQUE_GEOMETRY_TYPE",
        distinct_count=None,
    )
    assert col_class == ColumnClass.SKIP
    assert "non-text" in reason or "unclassifiable" in reason

    # Text type with count unavailable
    col_class, reason = classify_column(
        table_name="users",
        column_name="unscannable_col",
        sql_type=sa.Text(),
        distinct_count=None,
    )
    assert col_class == ColumnClass.SKIP
    assert "unclassifiable" in reason


@pytest.mark.parametrize(
    "sql_type,expected_class,expected_option_count",
    [
        ("ENUM('a','b','c')", ColumnClass.VALUE_LOW, 3),
        ("ENUM('0','1')", ColumnClass.VALUE_LOW, 2),
        ("VARCHAR(32) COLLATE utf8mb4_unicode_ci", ColumnClass.VALUE_LOW, None),
        ("TINYINT(1)", ColumnClass.SKIP, None),
        ("SET('x','y')", ColumnClass.VALUE_LOW, 2),
    ],
)
def test_phase1b_type_metadata_classification(
    sql_type: str,
    expected_class: ColumnClass,
    expected_option_count: int | None,
):
    """Use declared ENUM/SET options and normalize collated text type strings."""
    options = parse_enum_options(sql_type)
    observed, reason = classify_column(
        table_name="generic_table",
        column_name="generic_field",
        sql_type=sql_type,
        distinct_count=2,
        avg_text_length=1,
    )
    assert observed == expected_class
    assert (len(options) if options is not None else None) == expected_option_count
    assert is_text_type(sql_type) is (expected_class != ColumnClass.SKIP)
    if expected_option_count is not None:
        assert str(expected_option_count) in reason


def test_phase1b_sensitive_name_review_and_enum_privacy_guards():
    """Clean categorical options are reviewable; credentials and PII-shaped options remain blocked."""
    clean, _ = classify_column(
        "generic_table", "generic_status_email", "ENUM('0','1')"
    )
    credential, _ = classify_column(
        "generic_table", "generic_secret_status", "ENUM('0','1')"
    )
    pii_shaped, _ = classify_column(
        "generic_table", "generic_status", "ENUM('a@example.test','b@example.test')"
    )
    text_without_shape_evidence, _ = classify_column(
        "generic_table",
        "generic_status_email",
        "VARCHAR(32) COLLATE utf8mb4_unicode_ci",
        distinct_count=2,
    )
    text_with_clean_shape_evidence, _ = classify_column(
        "generic_table",
        "generic_status_email",
        "VARCHAR(32) COLLATE utf8mb4_unicode_ci",
        distinct_count=2,
        sensitive_values_clean=True,
    )

    assert clean == ColumnClass.VALUE_LOW
    assert credential == ColumnClass.BLOCKED
    assert pii_shaped == ColumnClass.BLOCKED
    assert text_without_shape_evidence == ColumnClass.BLOCKED
    assert text_with_clean_shape_evidence == ColumnClass.VALUE_LOW
    assert reviewable_sensitive_name_tokens("generic_status_email") == ["email"]
    assert is_flag_like_options(parse_enum_options("ENUM('0','1')"))


# ---------------------------------------------------------------------------
# 3. Override precedence
# ---------------------------------------------------------------------------

def test_override_precedence_and_force_allow_boundaries():
    """Verify override rules: force_allow cannot relax pattern BLOCK unless exact table.column."""
    # 1. force_block overrides an otherwise innocent column
    col_class, _ = classify_column(
        table_name="products",
        column_name="category",
        sql_type=sa.String(50),
        distinct_count=5,
        overrides={"force_block": ["products.category"]},
    )
    assert col_class == ColumnClass.BLOCKED

    # 2. force_mask marks column as MASKED
    col_class, _ = classify_column(
        table_name="users",
        column_name="username",
        sql_type=sa.String(50),
        distinct_count=100,
        overrides={"force_mask": ["users.username"]},
    )
    assert col_class == ColumnClass.MASKED

    # 3. Pattern-based force_allow CANNOT relax a pattern BLOCK
    col_class, reason = classify_column(
        table_name="customers",
        column_name="email",
        sql_type=sa.String(100),
        distinct_count=50,
        overrides={"force_allow": ["customers.*", "*.email"]},
    )
    assert col_class == ColumnClass.BLOCKED
    assert "blocked by name pattern" in reason

    # 4. Exact table.column force_allow CAN relax a pattern BLOCK
    col_class, reason = classify_column(
        table_name="customers",
        column_name="contact_person",
        sql_type=sa.String(100),
        distinct_count=20,
        overrides={"force_allow": ["customers.contact_person"]},
    )
    assert col_class == ColumnClass.VALUE_LOW

    # 5. force_value_low forces value_low regardless of threshold
    col_class, _ = classify_column(
        table_name="items",
        column_name="sku",
        sql_type=sa.String(100),
        distinct_count=10000,
        cardinality_threshold=500,
        overrides={"force_value_low": ["items.sku"]},
    )
    assert col_class == ColumnClass.VALUE_LOW


# ---------------------------------------------------------------------------
# 4. BLOCKED columns absent from DDL, schema docs, retriever, mappings, and logs
# ---------------------------------------------------------------------------

def test_blocked_columns_absent_from_ddl_and_documents():
    """BLOCKED columns must never appear in compact DDL or schema embedding documents."""
    meta = SchemaMetadata(
        tables={
            "users": TableInfo(
                name="users",
                description="users table",
                columns=[
                    ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True),
                    ColumnInfo(name="username", data_type="VARCHAR(50)"),
                    ColumnInfo(name="password_hash", data_type="VARCHAR(255)"),  # BLOCKED
                    ColumnInfo(name="email", data_type="VARCHAR(255)"),          # BLOCKED
                ],
                primary_key_names=["id"],
                foreign_keys=[],
            )
        }
    )

    # 1. Compact DDL omits blocked columns
    retriever = HybridSchemaRetriever(
        metadata=meta,
        embedding_model=MagicMock(embed=lambda texts: np.ones((len(texts), 4))),
    )
    ddl = retriever.compact_ddl(["users"])
    assert "password_hash" not in ddl
    assert "email" not in ddl
    assert "username" in ddl
    assert "id" in ddl

    # 2. Table document omits blocked columns
    doc = build_table_document(meta.tables["users"])
    assert "password_hash" not in doc
    assert "email" not in doc
    assert "username" in doc

    # 3. Column document returns empty for blocked column
    assert build_column_document(meta.tables["users"], meta.tables["users"].columns[2]) == ""
    assert build_column_document(meta.tables["users"], meta.tables["users"].columns[3]) == ""


def test_blocked_and_value_high_columns_not_sent_as_llm_mappings():
    """Only VALUE_LOW columns may produce resolved value mappings sent to the LLM."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    metadata = SchemaMetadata(tables={})

    mock_vindex = MagicMock()
    # mock_vindex.values contains ONLY VALUE_LOW columns
    mock_vindex.values = {"users.status": ["active"]}
    mock_vindex.large_columns = {"users.name"}

    captured_prompt_messages = []

    class CapturingGenerator:
        def generate(self, messages):
            captured_prompt_messages.append(messages)
            return "SELECT id FROM users"

    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=metadata,
        retriever=MagicMock(retrieve=lambda q, k: {"tables": ["users"], "ddl": "TABLE users (id INT)"}),
        generator=CapturingGenerator(),
        value_index=mock_vindex,
    )

    # Supply confirmed matches containing both VALUE_LOW (status) and VALUE_HIGH/unindexed (name)
    confirmed = [
        {"mention": "active", "column": "users.status", "value": "active"},
        {"mention": "Alice", "column": "users.name", "value": "Alice"},
    ]

    with patch.object(adapter, "run_readonly_query", return_value=MagicMock(rows=[{"id": 1}], columns=["id"])):
        pipeline.run("find active users", confirmed_values=confirmed)

    assert len(captured_prompt_messages) > 0
    prompt_text = str(captured_prompt_messages[0])
    # VALUE_LOW mapping must be in prompt
    assert "users.status" in prompt_text
    assert "active" in prompt_text
    # VALUE_HIGH / unindexed mapping must NOT be in prompt
    assert "users.name" not in prompt_text
    assert "Alice" not in prompt_text


def test_rejected_literal_correction_scrubs_sensitive_values():
    """Rejected literal text in correction must not echo values from BLOCKED/MASKED/VALUE_HIGH columns."""
    engine = sa.create_engine("sqlite:///:memory:")
    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    metadata = SchemaMetadata(tables={})

    mock_vindex = MagicMock()
    mock_vindex.values = {}
    mock_vindex.large_columns = {"customers.secret_token"}

    generator = MagicMock()
    generator.generate.return_value = "SELECT id FROM customers WHERE secret_token = 'SUPER_SECRET'"

    pipeline = TextToSQLPipeline(
        adapter=adapter,
        metadata=metadata,
        retriever=MagicMock(retrieve=lambda q, k: {"tables": ["customers"], "ddl": "TABLE customers (id INT)"}),
        generator=generator,
        value_index=mock_vindex,
    )

    # Force a ValueSafetyError on secret_token
    safety_error = ValueSafetyError(
        message="No matching value found for 'SUPER_SECRET' in customers.secret_token.",
        kind="not_found",
        mention="SUPER_SECRET",
        column="customers.secret_token",
        closest=["SECRET123"],
    )

    with patch("pipeline.orchestrator.validate_sql", side_effect=safety_error):
        result = pipeline.run("find user by secret")
        # Ensure raw secret is not in result.answer or errors
        assert "SUPER_SECRET" not in result.answer
        assert "SUPER_SECRET" not in str(result.errors)


# ---------------------------------------------------------------------------
# 5. Fail-closed policy import behavior
# ---------------------------------------------------------------------------

def test_fail_closed_policy_import():
    """If data policy cannot be imported, validator must treat all columns as blocked."""
    meta = SchemaMetadata(
        tables={
            "orders": TableInfo(
                name="orders",
                description="orders table",
                columns=[ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True)],
                primary_key_names=["id"],
                foreign_keys=[],
            )
        }
    )

    # Simulate validator falling back to fail-closed stub
    from validation.validator import validate_sql
    with patch("validation.validator.is_blocked", return_value=True):
        with pytest.raises(ValidationError, match="That information isn't available"):
            validate_sql("SELECT id FROM orders", metadata=meta, dialect="sqlite", allowed_tables={"orders"})


# ---------------------------------------------------------------------------
# 6. Internal / system tables excluded by default
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tbl_name,expected_internal",
    [
        ("system_schema_embeddings", True),
        ("system_value_embeddings", True),
        ("system_examples", True),
        ("_private_metadata", True),
        ("alembic_version", True),
        ("django_migrations", True),
        ("auth_permission", True),
        ("auth_user_groups", True),
        ("user_sessions", True),
        ("customer_sessions", True),
        ("customers", False),
        ("orders", False),
        ("order_items", False),
        ("products", False),
    ],
)
def test_internal_system_tables_excluded_by_default(tbl_name: str, expected_internal: bool):
    """Verify system tables and common internal migration/session tables are filtered by default."""
    assert is_internal_table_name(tbl_name) == expected_internal


# ---------------------------------------------------------------------------
# 7. Pipeline works with empty domain overrides
# ---------------------------------------------------------------------------

def test_pipeline_runs_with_empty_domain_overrides():
    """Verify ValueIndex and TextToSQLPipeline function seamlessly when domain overrides are empty."""
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE cities (id INTEGER PRIMARY KEY, city_name TEXT)")
        conn.exec_driver_sql("INSERT INTO cities VALUES (1, 'Berlin'), (2, 'Paris')")

    adapter = DatabaseAdapter("sqlite:///:memory:", engine=engine)
    catalog = introspect_catalog(engine)

    # Instantiate ValueIndex with completely empty domain config overrides
    vindex = ValueIndex(
        adapter=adapter,
        metadata=catalog,
        embedder=MagicMock(embed=lambda texts: np.ones((len(texts), 4))),
    )
    vindex.config = {"thresholds": {"accept_score": 0.88}}
    vindex.cue_aliases = {}
    vindex.metric_terms = set()
    vindex.metric_term_cues = {}
    vindex.status_filter_column_names = set()
    vindex.activity_query_expansion = ()
    vindex.value_column_allowlist = set()

    built = vindex.build()
    assert "cities.city_name" in built
    assert "Berlin" in built["cities.city_name"]

    resolved = vindex.resolve_question("Show data for Berlin")
    assert len(resolved) == 1
    assert resolved[0]["value"] == "Berlin"


# ---------------------------------------------------------------------------
# 8. Real database classification (SQLite and Docker MySQL hiresanta)
# ---------------------------------------------------------------------------

def test_classifier_runs_on_sqlite_fixture():
    """Verify classifier executes distinct count scan and assigns classes on SQLite."""
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE employees ("
            "  emp_id INTEGER PRIMARY KEY,"
            "  full_name VARCHAR(100),"
            "  department VARCHAR(50),"
            "  email VARCHAR(100),"
            "  notes TEXT"
            ")"
        )
        conn.exec_driver_sql("INSERT INTO employees VALUES (1, 'Alice', 'Engineering', 'a@b.com', 'notes 1')")
        conn.exec_driver_sql("INSERT INTO employees VALUES (2, 'Bob', 'HR', 'b@b.com', 'notes 2')")

    catalog = introspect_catalog(engine)
    table = catalog.tables["employees"]

    refl = sa.Table("employees", sa.MetaData(), autoload_with=engine)
    with engine.connect() as conn:
        # emp_id -> SKIP (primary key)
        c_emp_id, _ = classify_column("employees", "emp_id", refl.c.emp_id.type, is_primary_key=True)
        assert c_emp_id == ColumnClass.SKIP

        # email -> BLOCKED (name pattern)
        c_email, _ = classify_column("employees", "email", refl.c.email.type)
        assert c_email == ColumnClass.BLOCKED

        # notes -> SKIP (free text name pattern)
        c_notes, _ = classify_column("employees", "notes", refl.c.notes.type)
        assert c_notes == ColumnClass.SKIP

        # department -> VALUE_LOW (distinct count 2 <= 500)
        cnt, avg_len = get_column_stats(conn, refl, "department")
        c_dept, _ = classify_column("employees", "department", refl.c.department.type, distinct_count=cnt, avg_text_length=avg_len)
        assert c_dept == ColumnClass.VALUE_LOW
