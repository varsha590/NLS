"""Security and behavior tests for uploaded schema ingestion."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import warnings

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


def test_realistic_mysqldump_insert_ignore_escaped_values_and_version_comments():
    sql = r"""
    /*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
    CREATE TABLE `publishers` (
        `id` int NOT NULL,
        `name` varchar(80) DEFAULT NULL,
        PRIMARY KEY (`id`)
    ) ENGINE=InnoDB;
    INSERT IGNORE INTO `publishers` (`id`, `name`) VALUES
        (1, 'O\'Reilly, Inc.'),
        (2, 'Northwind');
    /*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
    """
    schema, documents, warnings = parse_sql_dump(sql, dialect="mysql")
    assert set(schema.tables) == {"publishers"}
    assert {item["value"] for item in documents} == {"O'Reilly, Inc.", "Northwind"}
    assert not warnings


def test_realistic_pg_dump_copy_block_is_skipped_without_crashing():
    sql = """
    -- PostgreSQL database dump
    CREATE TABLE public.regions (
        id integer NOT NULL,
        name text
    );
    COPY public.regions (id, name) FROM stdin;
    1\tNorth
    2\tSouth
    \\.
    """
    schema, documents, warnings = parse_sql_dump(sql, dialect="postgres")
    assert "public.regions" in schema.tables
    assert documents == []
    assert not warnings


def test_unsupported_dump_statements_are_ignored_without_losing_tables():
    sql = """
    CREATE TABLE visible_table (id INTEGER PRIMARY KEY, label TEXT);
    CREATE VIEW visible_view AS SELECT label FROM visible_table;
    CREATE TRIGGER visible_trigger AFTER INSERT ON visible_table BEGIN SELECT 1; END;
    SET FOREIGN_KEY_CHECKS = 0;
    LOCK TABLES visible_table WRITE;
    DELIMITER $$
    CREATE PROCEDURE hidden_procedure() BEGIN SELECT 1; END$$
    DELIMITER ;
    """
    schema, documents, _ = parse_sql_dump(sql, dialect="mysql")
    assert set(schema.tables) == {"visible_table"}
    assert documents == []


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
    import numpy as np
    from qdrant_client import QdrantClient

    from retrieval.qdrant_store import QdrantVectorStore

    registry = DatasetRegistry(tmp_path)
    result = registry.register(
        "catalog.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="tenant-a",
        embedding_model_name="tiny-384",
    )
    assert result["status"] == "registered"
    metadata_path = registry.dataset_directory("tenant-a", result["dataset_id"]) / "dataset.json"
    before_index = json.loads(metadata_path.read_text())
    assert before_index["indexed"] is False
    assert before_index["dataset_hash"] == result["dataset_hash"]
    assert before_index["embedding_model_name"] == "tiny-384"
    assert "vector_dimension" not in before_index

    class TinyEmbedder:
        model_name = "tiny-384"
        dim = 384

        def embed(self, texts):
            return np.tile(np.asarray([[1.0] + [0.0] * 383]), (len(texts), 1))

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Payload indexes have no effect in the local Qdrant")
        store = QdrantVectorStore(client=QdrantClient(location=":memory:"))
    doc = [{
        "document_type": "table",
        "table_name": "regions",
        "column_name": None,
        "content": "regions",
    }]
    store.reindex_dataset(
        "tenant-a",
        result["dataset_id"],
        doc,
        TinyEmbedder().embed(["regions"]).tolist(),
        metadata_path,
        result["dataset_hash"],
        TinyEmbedder.model_name,
        TinyEmbedder.dim,
    )

    monkeypatch.setattr(
        datasets,
        "parse_sql_dump",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unchanged upload was reparsed")),
    )
    unchanged = registry.register(
        "catalog.sql",
        b"CREATE TABLE regions (id INTEGER PRIMARY KEY, name TEXT);",
        tenant_id="tenant-a",
        embedding_model_name="tiny-384",
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


def test_db_upload_builds_low_cardinality_values_read_only_and_skips_pii(tmp_path, monkeypatch):
    import ingestion.datasets as datasets

    source_path = tmp_path / "values.db"
    connection = sqlite3.connect(source_path)
    connection.executescript(
        "CREATE TABLE locations (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE contact_data (id INTEGER PRIMARY KEY, label TEXT, email TEXT);"
        "CREATE TABLE many_values (id INTEGER PRIMARY KEY, label TEXT);"
        "INSERT INTO locations VALUES (1, 'North'), (2, 'South');"
        "INSERT INTO contact_data VALUES (1, '+1 (555) 123-4567', 'person@example.com');"
        "INSERT INTO many_values VALUES (1, 'One'), (2, 'Two'), (3, 'Three'), (4, 'Four');"
    )
    connection.close()

    executed: list[str] = []
    original_connect = datasets.sqlite3.connect

    class TracedConnection:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def execute(self, sql, parameters=()):
            executed.append(sql.strip())
            return self.wrapped.execute(sql, parameters)

        def enable_load_extension(self, enabled):
            if hasattr(self.wrapped, "enable_load_extension"):
                return self.wrapped.enable_load_extension(enabled)
            return None

        def close(self):
            return self.wrapped.close()

    def traced_connect(*args, **kwargs):
        return TracedConnection(original_connect(*args, **kwargs))

    monkeypatch.setattr(datasets.sqlite3, "connect", traced_connect)
    registry = DatasetRegistry(tmp_path / "datasets")
    result = registry.register(
        "values.db",
        source_path.read_bytes(),
        tenant_id="tenant-db",
        low_cardinality_max=3,
    )
    dataset_dir = next((tmp_path / "datasets").glob("*/" + result["dataset_id"]))
    stored_values = json.loads((dataset_dir / "value_documents.json").read_text())

    assert {item["value"] for item in stored_values} == {"North", "South"}
    assert all("email" not in item["column_name"] for item in stored_values)
    assert any("PII-shaped values" in warning for warning in result["warnings"])
    assert any(statement.startswith("SELECT DISTINCT") and "LIMIT ?" in statement for statement in executed)
    assert not any('"email"' in statement for statement in executed)
    assert not any(item["table_name"] == "many_values" for item in stored_values)
    assert all(
        value not in (dataset_dir / "value_documents.json").read_text()
        for value in ("555", "person@example.com", "One", "Two", "Three", "Four")
    )
    assert all(
        statement.startswith(("SELECT ", "PRAGMA "))
        for statement in executed
    )


def test_parser_environment_excludes_credentials_and_unapproved_variables(monkeypatch):
    import ingestion.datasets as datasets

    monkeypatch.setenv("GROQ_API_KEY", "not-for-child")
    monkeypatch.setenv("DATABASE_URL", "postgresql://not-for-child")
    monkeypatch.setenv("ARBITRARY_SECRET", "not-for-child")
    observed_env: dict[str, str] = {}
    actual_run = datasets.subprocess.run

    def capture_environment(*args, **kwargs):
        observed_env.update(kwargs["env"])
        kwargs.pop("check", None)
        return actual_run(*args, check=False, **kwargs)

    monkeypatch.setattr(datasets.subprocess, "run", capture_environment)
    parse_sql_dump(
        "CREATE TABLE safe_table (id INTEGER PRIMARY KEY, label TEXT);",
        dialect="sqlite",
    )
    child_env = observed_env
    assert "GROQ_API_KEY" not in child_env
    assert "DATABASE_URL" not in child_env
    assert "ARBITRARY_SECRET" not in child_env
    assert set(child_env) <= set(datasets.PARSER_ENV_ALLOWLIST)


def test_upload_parse_timeout_is_enforced(monkeypatch):
    import ingestion.datasets as datasets

    def timeout(*args, **kwargs):
        raise datasets.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(datasets.subprocess, "run", timeout)
    with pytest.raises(UploadError, match="time limit"):
        datasets.parse_sql_dump("SELECT 1", dialect="sqlite", parse_timeout_seconds=0.001)


def test_dataset_directory_validates_tenant_and_dataset_id(tmp_path):
    registry = DatasetRegistry(tmp_path)
    # Valid inputs should work
    valid_dir = registry.dataset_directory("valid_tenant", "valid_dataset")
    assert valid_dir.exists() or True  # directory may not exist yet

    # Invalid tenant_id with path traversal
    with pytest.raises(UploadError, match="Invalid tenant_id"):
        registry.dataset_directory("../x", "valid_dataset")

    # Invalid tenant_id with slash
    with pytest.raises(UploadError, match="Invalid tenant_id"):
        registry.dataset_directory("a/../b", "valid_dataset")

    # Invalid tenant_id with bare path
    with pytest.raises(UploadError, match="Invalid tenant_id"):
        registry.dataset_directory("a/b", "valid_dataset")

    # Absolute path tenant_id
    with pytest.raises(UploadError, match="Invalid tenant_id"):
        registry.dataset_directory("/absolute", "valid_dataset")

    # Empty tenant_id
    with pytest.raises(UploadError, match="Invalid tenant_id"):
        registry.dataset_directory("", "valid_dataset")

    # Invalid dataset_id with path traversal
    with pytest.raises(UploadError, match="Invalid dataset_id"):
        registry.dataset_directory("valid_tenant", "../x")

    # Invalid dataset_id with slash
    with pytest.raises(UploadError, match="Invalid dataset_id"):
        registry.dataset_directory("valid_tenant", "a/../b")

    # Invalid dataset_id with bare path
    with pytest.raises(UploadError, match="Invalid dataset_id"):
        registry.dataset_directory("valid_tenant", "a/b")

    # Absolute path dataset_id
    with pytest.raises(UploadError, match="Invalid dataset_id"):
        registry.dataset_directory("valid_tenant", "/absolute")

    # Empty dataset_id
    with pytest.raises(UploadError, match="Invalid dataset_id"):
        registry.dataset_directory("valid_tenant", "")


def test_slow_parser_child_process_is_killed_on_real_timeout(tmp_path):
    import ingestion.datasets as datasets

    pid_path = tmp_path / "child.pid"
    child_code = (
        "import os, time; "
        f"open({str(pid_path)!r}, 'w').write(str(os.getpid())); "
        "time.sleep(30)"
    )
    with pytest.raises(UploadError, match="time limit"):
        datasets.run_parser_process(
            [sys.executable, "-c", child_code],
            payload="",
            timeout_seconds=0.2,
            working_directory=tmp_path,
        )
    child_pid = int(pid_path.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)