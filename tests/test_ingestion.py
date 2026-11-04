"""Security and behavior tests for uploaded schema ingestion."""

from __future__ import annotations

import json
import sqlite3

import pytest

from ingestion.datasets import (
    DatasetRegistry,
    UploadError,
    detect_sql_dialect,
    inspect_sqlite_database,
    parse_sql_dump,
)


def test_dialect_detection_uses_requested_signatures():
    assert detect_sql_dialect("CREATE TABLE `t` (id INT) ENGINE=InnoDB") == "mysql"
    assert detect_sql_dialect("CREATE TABLE t (id SERIAL); SELECT value::text") == "postgres"
    assert detect_sql_dialect("CREATE TABLE t (id INTEGER AUTOINCREMENT)") == "sqlite"


def test_sql_dump_extracts_table_columns_keys_and_foreign_keys_without_execution(monkeypatch):
    import ingestion.datasets as datasets

    def reject_database_connection(*args, **kwargs):
        raise AssertionError("SQL dump ingestion must not connect to a database")

    monkeypatch.setattr(datasets.sqlite3, "connect", reject_database_connection)
    sql = """
    CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER,
        status TEXT,
        CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
    );
    ALTER TABLE orders ADD CONSTRAINT fk_customer_2
        FOREIGN KEY (customer_id) REFERENCES customers(id);
    INSERT INTO customers (id, name) VALUES (1, 'Acme'), (2, 'Northwind');
    INSERT INTO orders (id, customer_id, status) VALUES (1, 1, 'Open'), (2, 2, 'Closed');
    SET FOREIGN_KEY_CHECKS = 0;
    LOCK TABLES orders WRITE;
    CREATE VIEW order_view AS SELECT id FROM orders;
    CREATE TRIGGER order_trigger AFTER INSERT ON orders BEGIN SELECT 1; END;
    DELIMITER $$
    CREATE PROCEDURE ignored_proc() BEGIN SELECT 1; END$$
    DELIMITER ;
    """
    schema, documents, warnings = parse_sql_dump(sql, dialect="mysql")

    assert set(schema.tables) == {"customers", "orders"}
    assert schema.dialect == "mysql"
    assert schema.tables["orders"].primary_key_names == ["id"]
    assert schema.tables["orders"].columns[1].is_foreign_key
    assert len(schema.tables["orders"].foreign_keys) == 1
    assert {(item["table_name"], item["column_name"], item["value"]) for item in documents} == {
        ("customers", "name", "Acme"),
        ("customers", "name", "Northwind"),
        ("orders", "status", "Open"),
        ("orders", "status", "Closed"),
    }
    assert not warnings


def test_table_without_insert_has_no_value_documents():
    schema, documents, _ = parse_sql_dump(
        "CREATE TABLE lookup_values (id INTEGER PRIMARY KEY, label TEXT);",
        dialect="sqlite",
    )
    assert "lookup_values" in schema.tables
    assert documents == []


def test_unknown_insert_sources_are_not_used_to_infer_cardinality():
    sql = (
        "CREATE TABLE master_data (id INTEGER, label TEXT);"
        "INSERT INTO master_data VALUES (1, 'Known');"
        "INSERT INTO master_data SELECT id, label FROM staging;"
    )
    _, documents, _ = parse_sql_dump(sql, dialect="sqlite")
    assert documents == []


def test_high_cardinality_and_sensitive_or_pii_columns_are_skipped():
    rows = ",".join(f"({index}, 'Value {index}', 'person@example.com')" for index in range(55))
    sql = (
        "CREATE TABLE master_data (id INTEGER, label TEXT, email TEXT);"
        f"INSERT INTO master_data VALUES {rows};"
    )
    _, documents, warnings = parse_sql_dump(sql, dialect="sqlite")
    assert documents == []
    assert any("PII-shaped values" in warning for warning in warnings)
    assert any("Upload contains PII-shaped content" in warning for warning in warnings)


def test_phone_shaped_insert_value_is_warned_and_skipped():
    sql = (
        "CREATE TABLE contacts (contact_label TEXT);"
        "INSERT INTO contacts VALUES ('+1 (555) 123-4567');"
    )
    _, documents, warnings = parse_sql_dump(sql, dialect="sqlite")
    assert documents == []
    assert any("PII-shaped values" in warning for warning in warnings)
    assert any("Upload contains PII-shaped content" in warning for warning in warnings)


def test_non_text_sql_and_upload_limits_are_rejected(tmp_path):
    registry = DatasetRegistry(tmp_path)
    with pytest.raises(UploadError, match="UTF-8 text"):
        registry.register("dump.sql", b"\xff\x00", max_upload_mb=1)
    with pytest.raises(UploadError, match="at least 1 MB"):
        registry.register("dump.sql", b"SELECT 1", max_upload_mb=0)
    with pytest.raises(UploadError, match="size limit"):
        registry.register("large.sql", b"x" * (1024 * 1024 + 1), max_upload_mb=1)


def test_sql_upload_hash_skips_unchanged_and_persists_schema(tmp_path, monkeypatch):
    import ingestion.datasets as datasets

    registry = DatasetRegistry(tmp_path)
    result = registry.register(
        "catalog.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="tenant-a",
    )
    unchanged = registry.register(
        "catalog.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="tenant-a",
    )

    assert result["status"] == "registered"
    monkeypatch.setattr(
        datasets,
        "parse_sql_dump",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unchanged upload was reparsed")),
    )
    assert unchanged["status"] == "unchanged"
    assert registry.load_schema("tenant-a", result["dataset_id"]).dialect == "sqlite"
    assert (tmp_path / "schema.json").exists() is False
    schema_path = next(tmp_path.glob("*/**/schema.json"))
    assert json.loads(schema_path.read_text())["dialect"] == "sqlite"


def test_sql_dialect_override_is_persisted(tmp_path):
    result = DatasetRegistry(tmp_path).register(
        "source.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, label TEXT);",
        tenant_id="tenant-c",
        dialect_override="mysql",
    )
    assert result["dialect"] == "mysql"


def test_sqlite_inspection_is_header_checked_and_read_only(tmp_path):
    invalid_path = tmp_path / "invalid.db"
    invalid_path.write_bytes(b"not a sqlite database")
    with pytest.raises(UploadError, match="not a valid SQLite"):
        inspect_sqlite_database(invalid_path)

    database_path = tmp_path / "schema.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id));"
    )
    connection.close()
    before = database_path.read_bytes()
    schema = inspect_sqlite_database(database_path)
    assert set(schema.tables) == {"child", "parent"}
    assert schema.tables["child"].foreign_keys[0]["remote_table"] == "parent"
    assert database_path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        readonly = sqlite3.connect(f"file:{database_path.resolve()}?mode=ro", uri=True)
        try:
            readonly.execute("CREATE TABLE forbidden (id INTEGER)")
        finally:
            readonly.close()


def test_sqlite_dataset_is_persisted_for_later_read_only_execution(tmp_path):
    source_path = tmp_path / "source.db"
    connection = sqlite3.connect(source_path)
    connection.execute("CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT)")
    connection.close()
    registry = DatasetRegistry(tmp_path / "datasets")
    result = registry.register("regions.db", source_path.read_bytes(), tenant_id="tenant-b")
    dataset_dir = next((tmp_path / "datasets").glob("*/" + result["dataset_id"]))
    assert (dataset_dir / "source.db").exists()
    assert registry.load_schema("tenant-b", result["dataset_id"]).tables["regions"]


def test_upload_parse_timeout_is_enforced(monkeypatch):
    import ingestion.datasets as datasets

    def timeout(*args, **kwargs):
        raise datasets.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(datasets.subprocess, "run", timeout)
    with pytest.raises(UploadError, match="time limit"):
        datasets.parse_sql_dump("SELECT 1", dialect="sqlite", parse_timeout_seconds=0.001)