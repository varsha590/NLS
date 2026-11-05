"""Parse uploaded schema dumps and inspect SQLite files without executing uploads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import sqlglot
from sqlglot import exp
from sqlglot.errors import ErrorLevel

from catalog.classifier import is_key_column, is_pii_shaped_value, is_text_type
from config.data_policy import is_blocked, is_masked
from retrieval.qdrant_store import make_dataset_hash
from schema.metadata import ColumnInfo, SchemaMetadata, TableInfo

DATASET_NAMESPACE = uuid.UUID("ec8f4bc1-0661-4f34-9b91-dffb31759b7b")
DEFAULT_MAX_UPLOAD_MB = 200
DEFAULT_PARSE_TIMEOUT_SECONDS = 10
DEFAULT_LOW_CARDINALITY_MAX = 50
_EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_LONG_ID_PATTERN = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?[\d().\-\s]{7,}(?!\w)")
PARSER_ENV_ALLOWLIST = (
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "TMPDIR",
    "TEMP",
    "TMP",
)

_TENANT_DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_tenant_dataset_id(value: str, label: str) -> None:
    """Raise UploadError if tenant_id or dataset_id fails the allowlist check."""
    if not _TENANT_DATASET_ID_PATTERN.fullmatch(value):
        raise UploadError(f"Invalid {label}: {value!r}. Must match ^[A-Za-z0-9_-]{{1,64}}$")


class UploadError(ValueError):
    """Raised when an uploaded dataset is invalid or unsafe to ingest."""


def parser_environment() -> dict[str, str]:
    """Pass only non-secret process settings to the isolated parser."""
    return {
        key: os.environ[key]
        for key in PARSER_ENV_ALLOWLIST
        if key in os.environ
    }


def run_parser_process(
    command: list[str],
    payload: str,
    timeout_seconds: float,
    working_directory: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=payload,
            capture_output=True,
            check=False,
            cwd=working_directory,
            env=parser_environment(),
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise UploadError("SQL parsing exceeded the configured time limit.") from error
    except OSError as error:
        raise UploadError("Could not start the SQL parser.") from error


def detect_sql_dialect(sql_text: str) -> str:
    """Guess a SQL dump dialect from the requested structural signatures."""
    if re.search(r"`|\bENGINE\s*=|\bAUTO_INCREMENT\b", sql_text, re.IGNORECASE):
        return "mysql"
    if re.search(r"\bSERIAL\b|::", sql_text, re.IGNORECASE):
        return "postgres"
    if re.search(r"\bAUTOINCREMENT\b", sql_text, re.IGNORECASE):
        return "sqlite"
    return "sqlite"


def _strip_delimiter_blocks(sql_text: str) -> str:
    kept_lines: list[str] = []
    custom_delimiter = False
    for line in sql_text.splitlines():
        directive = re.match(r"^\s*DELIMITER\s+(\S+)", line, re.IGNORECASE)
        if directive:
            custom_delimiter = directive.group(1) != ";"
            continue
        if not custom_delimiter:
            kept_lines.append(line)
    return "\n".join(kept_lines)


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split ordinary SQL statements while respecting quotes and comments."""
    text = _strip_delimiter_blocks(sql_text)
    statements: list[str] = []
    current: list[str] = []
    quote_char: str | None = None
    dollar_tag: str | None = None
    in_block_comment = False
    in_line_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        next_character = text[index + 1] if index + 1 < len(text) else ""
        if in_line_comment:
            current.append(character)
            if character == "\n":
                in_line_comment = False
            index += 1
            continue
        if in_block_comment:
            current.append(character)
            if character == "*" and next_character == "/":
                current.append(next_character)
                index += 2
                in_block_comment = False
            else:
                index += 1
            continue
        if dollar_tag:
            if text.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                current.append(character)
                index += 1
            continue
        if quote_char:
            current.append(character)
            if character == quote_char:
                if next_character == quote_char:
                    current.append(next_character)
                    index += 2
                    continue
                quote_char = None
            elif character == "\\" and next_character:
                current.append(next_character)
                index += 2
                continue
            index += 1
            continue
        if character == "-" and next_character == "-":
            current.extend((character, next_character))
            index += 2
            in_line_comment = True
            continue
        if character == "/" and next_character == "*":
            current.extend((character, next_character))
            index += 2
            in_block_comment = True
            continue
        if character == "#":
            current.append(character)
            index += 1
            in_line_comment = True
            continue
        if character in ("'", '"', "`", "["):
            quote_char = "]" if character == "[" else character
            current.append(character)
            index += 1
            continue
        if character == "$":
            match = re.match(r"\$[A-Za-z_0-9]*\$", text[index:])
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                index += len(dollar_tag)
                continue
        if character == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
        else:
            current.append(character)
        index += 1
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def _parse_sql_statement(statement: str, dialect: str) -> list[exp.Expression]:
    try:
        return [node for node in sqlglot.parse(statement, read=dialect, error_level=ErrorLevel.IGNORE) if node]
    except (sqlglot.errors.SqlglotError, ValueError):
        return []


def _sql_name(table: exp.Table) -> str:
    name = table.name
    if table.db:
        name = f"{table.db}.{name}"
    if table.catalog:
        name = f"{table.catalog}.{name}"
    return name


def _foreign_key_record(foreign_key: exp.ForeignKey) -> dict[str, Any] | None:
    reference = foreign_key.args.get("reference")
    remote_schema = reference.this if isinstance(reference, exp.Reference) else None
    if not isinstance(remote_schema, exp.Schema) or not isinstance(remote_schema.this, exp.Table):
        return None
    local_columns = [identifier.name for identifier in foreign_key.expressions]
    remote_columns = [identifier.name for identifier in remote_schema.expressions]
    if not local_columns or not remote_columns or len(local_columns) != len(remote_columns):
        return None
    return {
        "constrain_name": None,
        "local_cols": local_columns,
        "remote_table": _sql_name(remote_schema.this),
        "remote_cols": remote_columns,
    }


def _apply_foreign_key(table: TableInfo, relation: dict[str, Any]) -> None:
    table.foreign_keys.append(relation)
    for local_name, remote_name in zip(relation["local_cols"], relation["remote_cols"]):
        column = next((item for item in table.columns if item.name.casefold() == local_name.casefold()), None)
        if column:
            column.is_foreign_key = True
            column.foreign_table = relation["remote_table"]
            column.foreign_column = remote_name


def _create_table(create: exp.Create, dialect: str) -> TableInfo | None:
    schema = create.this
    if create.args.get("kind", "TABLE").upper() != "TABLE" or not isinstance(schema, exp.Schema):
        return None
    table_node = schema.this
    if not isinstance(table_node, exp.Table):
        return None

    columns: list[ColumnInfo] = []
    primary_keys: list[str] = []
    unique_constraints: list[list[str]] = []
    foreign_keys: list[dict[str, Any]] = []
    for definition in schema.expressions:
        if isinstance(definition, exp.ColumnDef):
            column_name = definition.name
            data_type = definition.kind.sql(dialect=dialect) if definition.kind else "unknown"
            constraints = [constraint.kind for constraint in definition.constraints]
            is_primary_key = any(isinstance(item, exp.PrimaryKeyColumnConstraint) for item in constraints)
            nullable = not is_primary_key and not any(
                isinstance(item, exp.NotNullColumnConstraint) for item in constraints
            )
            if is_primary_key:
                primary_keys.append(column_name)
            column = ColumnInfo(column_name, data_type, is_primary_key=is_primary_key, nullable=nullable)
            columns.append(column)
            for constraint in constraints:
                if isinstance(constraint, exp.UniqueColumnConstraint):
                    unique_constraints.append([column_name])
        elif isinstance(definition, exp.PrimaryKey):
            key_columns = [identifier.name for identifier in definition.expressions]
            primary_keys.extend(key_columns)
        elif isinstance(definition, exp.UniqueColumnConstraint):
            unique_constraints.append([definition.this.name])

    table = TableInfo(
        name=_sql_name(table_node),
        description=f"Table {_sql_name(table_node)}.",
        columns=columns,
        primary_key_names=list(dict.fromkeys(primary_keys)),
        foreign_keys=[],
        schema=table_node.db or None,
        unique_constraints=unique_constraints,
    )
    for column in table.columns:
        if column.name.casefold() in {name.casefold() for name in table.primary_key_names}:
            column.is_primary_key = True
            column.nullable = False
    foreign_keys.extend(
        relation
        for node in create.find_all(exp.ForeignKey)
        if (relation := _foreign_key_record(node)) is not None
    )
    for relation in foreign_keys:
        _apply_foreign_key(table, relation)
    return table


def _apply_alter_foreign_keys(statement: exp.Alter, tables: dict[str, TableInfo]) -> None:
    target = statement.this
    if not isinstance(target, exp.Table):
        return
    table = next((item for name, item in tables.items() if name.casefold() == _sql_name(target).casefold()), None)
    if table is None:
        return
    for foreign_key in statement.find_all(exp.ForeignKey):
        relation = _foreign_key_record(foreign_key)
        if relation and not any(
            item["local_cols"] == relation["local_cols"]
            and item["remote_table"].casefold() == relation["remote_table"].casefold()
            and item["remote_cols"] == relation["remote_cols"]
            for item in table.foreign_keys
        ):
            _apply_foreign_key(table, relation)


def _extract_insert_values(
    insert: exp.Insert,
    tables: dict[str, TableInfo],
    values_by_column: dict[str, set[str]],
    unknown_value_columns: set[str],
) -> None:
    target = insert.this
    if isinstance(target, exp.Schema):
        table_node = target.this
        insert_columns = [identifier.name for identifier in target.expressions]
    elif isinstance(target, exp.Table):
        table_node = target
        insert_columns = []
    else:
        return
    if not isinstance(table_node, exp.Table):
        return
    table = next((item for name, item in tables.items() if name.casefold() == _sql_name(table_node).casefold()), None)
    if table is None:
        return
    if not insert_columns:
        insert_columns = [column.name for column in table.columns]
    columns_by_name = {column.name.casefold(): column.name for column in table.columns}
    if not isinstance(insert.expression, exp.Values):
        unknown_value_columns.update(
            f"{table.name}.{columns_by_name[column.casefold()]}"
            for column in insert_columns
            if column.casefold() in columns_by_name
        )
        return
    for row in insert.expression.expressions:
        if not isinstance(row, exp.Tuple):
            continue
        for index, value in enumerate(row.expressions):
            if index >= len(insert_columns):
                continue
            column_name = columns_by_name.get(insert_columns[index].casefold())
            if column_name is None or not value.this:
                continue
            column_key = f"{table.name}.{column_name}"
            if not isinstance(value, exp.Literal):
                unknown_value_columns.add(column_key)
                continue
            column = next(column for column in table.columns if column.name == column_name)
            if is_key_column(
                column.name,
                is_primary_key=column.is_primary_key,
                is_foreign_key=column.is_foreign_key,
            ):
                continue
            values_by_column.setdefault(column_key, set()).add(str(value.this))


def _parse_sql_content(
    sql_text: str,
    dialect: str,
    low_cardinality_max: int,
) -> tuple[SchemaMetadata, list[dict[str, str]], list[str]]:
    statements = [
        node
        for statement in _split_sql_statements(sql_text)
        for node in _parse_sql_statement(statement, dialect)
    ]
    tables: dict[str, TableInfo] = {}
    for statement in statements:
        if isinstance(statement, exp.Create):
            table = _create_table(statement, dialect)
            if table:
                tables[table.name] = table
    if not tables:
        raise UploadError("No CREATE TABLE statements were found in the SQL upload.")
    for statement in statements:
        if isinstance(statement, exp.Alter):
            _apply_alter_foreign_keys(statement, tables)

    values_by_column: dict[str, set[str]] = {}
    unknown_value_columns: set[str] = set()
    tables_with_inserts: set[str] = set()
    for statement in statements:
        if isinstance(statement, exp.Insert):
            target = statement.this.this if isinstance(statement.this, exp.Schema) else statement.this
            if isinstance(target, exp.Table):
                target_name = _sql_name(target)
                if any(name.casefold() == target_name.casefold() for name in tables):
                    tables_with_inserts.add(target_name.casefold())
                    _extract_insert_values(
                        statement,
                        tables,
                        values_by_column,
                        unknown_value_columns,
                    )

    value_documents: list[dict[str, str]] = []
    warnings: list[str] = []
    for column_key, distinct_values in sorted(values_by_column.items()):
        table_name, _, column_name = column_key.rpartition(".")
        if table_name.casefold() not in tables_with_inserts:
            continue
        if column_key in unknown_value_columns:
            continue
        if any(is_pii_shaped_value(value) or _LONG_ID_PATTERN.fullmatch(value) for value in distinct_values):
            warnings.append(f"Skipped PII-shaped values in {table_name}.{column_name}.")
            continue
        if len(distinct_values) > low_cardinality_max:
            continue
        if is_blocked(column_key) or is_masked(column_key):
            warnings.append(f"Skipped restricted value column {table_name}.{column_name}.")
            continue
        for value in sorted(distinct_values, key=str.casefold):
            value_documents.append({
                "table_name": table_name,
                "column_name": column_name,
                "value": value,
                "content": f"{table_name} {column_name} {value}",
                "metadata_type": "master_value",
            })

    upload_literals = (
        node.this
        for statement in statements
        for node in statement.find_all(exp.Literal)
        if node.is_string
    )
    if (
        _EMAIL_PATTERN.search(sql_text)
        or _LONG_ID_PATTERN.search(sql_text)
        or any(is_pii_shaped_value(value) for value in upload_literals)
    ):
        warnings.append("Upload contains PII-shaped content; matching value columns are excluded.")
    return SchemaMetadata(tables, dialect=dialect), value_documents, sorted(set(warnings))


def parse_sql_dump(
    sql_text: str,
    dialect: str | None = None,
    parse_timeout_seconds: float = DEFAULT_PARSE_TIMEOUT_SECONDS,
    low_cardinality_max: int | None = None,
) -> tuple[SchemaMetadata, list[dict[str, str]], list[str]]:
    """Parse only CREATE TABLE/FK ALTER/literal INSERT AST nodes; never execute SQL."""
    selected_dialect = (dialect or detect_sql_dialect(sql_text)).casefold()
    if selected_dialect not in {"sqlite", "mysql", "postgres"}:
        raise UploadError("Unsupported SQL dialect.")
    if parse_timeout_seconds <= 0:
        raise UploadError("SQL parse timeout must be greater than zero.")
    selected_low_max = low_cardinality_max
    if selected_low_max is None:
        selected_low_max = int(os.getenv("LOW_CARDINALITY_MAX", str(DEFAULT_LOW_CARDINALITY_MAX)))
    if selected_low_max < 0:
        raise UploadError("Low-cardinality threshold cannot be negative.")
    completed = run_parser_process(
        [sys.executable, "-m", "ingestion.sql_worker"],
        json.dumps({
                "sql_text": sql_text,
                "dialect": selected_dialect,
                "low_cardinality_max": selected_low_max,
            }),
        parse_timeout_seconds,
        Path(__file__).resolve().parents[1],
    )
    if completed.returncode != 0:
        raise UploadError("The SQL upload could not be parsed safely.")
    try:
        result = json.loads(completed.stdout)
        schema = SchemaMetadata.from_dict(result["schema"])
        return schema, result["value_documents"], result["warnings"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise UploadError("The SQL parser returned invalid metadata.") from error


def inspect_sqlite_database(database_path: str | Path) -> SchemaMetadata:
    """Read SQLite catalog metadata using a verified, read-only URI connection."""
    path = Path(database_path)
    try:
        with path.open("rb") as file_obj:
            header = file_obj.read(16)
    except OSError as error:
        raise UploadError("Could not read the uploaded SQLite file.") from error
    if header != b"SQLite format 3\x00":
        raise UploadError("The uploaded .db file is not a valid SQLite database.")

    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        if hasattr(connection, "enable_load_extension"):
            connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only = ON")
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables: dict[str, TableInfo] = {}
        for table_name in table_names:
            escaped_name = table_name.replace('"', '""')
            columns = connection.execute(f'PRAGMA table_info("{escaped_name}")').fetchall()
            foreign_rows = connection.execute(f'PRAGMA foreign_key_list("{escaped_name}")').fetchall()
            by_fk: dict[int, list[tuple[int, str, str]]] = {}
            for fk_id, sequence, _, local_column, remote_column, *_ in foreign_rows:
                by_fk.setdefault(fk_id, []).append((sequence, local_column, remote_column))
            relations = []
            for fk_id, entries in by_fk.items():
                ordered = sorted(entries)
                relations.append({
                    "constrain_name": f"fk_{fk_id}",
                    "local_cols": [entry[1] for entry in ordered],
                    "remote_table": foreign_rows[0][2] if len(by_fk) == 1 else next(
                        row[2] for row in foreign_rows if row[0] == fk_id
                    ),
                    "remote_cols": [entry[2] for entry in ordered],
                })
            primary_keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
            column_infos = [
                ColumnInfo(
                    name=row[1],
                    data_type=row[2] or "unknown",
                    is_primary_key=bool(row[5]),
                    is_foreign_key=any(row[1] in relation["local_cols"] for relation in relations),
                    foreign_table=next((relation["remote_table"] for relation in relations if row[1] in relation["local_cols"]), None),
                    foreign_column=next((relation["remote_cols"][relation["local_cols"].index(row[1])] for relation in relations if row[1] in relation["local_cols"]), None),
                    nullable=not bool(row[3]) and not bool(row[5]),
                )
                for row in columns
            ]
            tables[table_name] = TableInfo(
                name=table_name,
                description=f"Table {table_name}.",
                columns=column_infos,
                primary_key_names=primary_keys,
                foreign_keys=relations,
                schema="main",
            )
        return SchemaMetadata(tables, dialect="sqlite")
    except sqlite3.DatabaseError as error:
        raise UploadError("Could not safely inspect the uploaded SQLite database.") from error
    finally:
        if "connection" in locals():
            connection.close()


def extract_sqlite_value_documents(
    database_path: str | Path,
    metadata: SchemaMetadata,
    low_cardinality_max: int = DEFAULT_LOW_CARDINALITY_MAX,
) -> tuple[list[dict[str, str]], list[str]]:
    """Collect only bounded low-cardinality values using read-only SELECT DISTINCT."""
    path = Path(database_path)
    if low_cardinality_max < 0:
        raise UploadError("Low-cardinality threshold cannot be negative.")
    uri = f"file:{quote(str(path.resolve()))}?mode=ro"
    value_documents: list[dict[str, str]] = []
    warnings: list[str] = []
    upload_has_pii = False
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=2.0)
        if hasattr(connection, "enable_load_extension"):
            connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only = ON")
        for table in metadata.tables.values():
            quoted_table = '"' + table.name.replace('"', '""') + '"'
            for column in table.columns:
                if (
                    not is_text_type(column.data_type)
                    or column.is_primary_key
                    or column.is_foreign_key
                    or is_key_column(
                        column.name,
                        is_primary_key=column.is_primary_key,
                        is_foreign_key=column.is_foreign_key,
                    )
                    or is_blocked(f"{table.name}.{column.name}")
                    or is_masked(f"{table.name}.{column.name}")
                ):
                    continue
                quoted_column = '"' + column.name.replace('"', '""') + '"'
                query = (
                    f"SELECT DISTINCT {quoted_column} FROM {quoted_table} "
                    f"WHERE {quoted_column} IS NOT NULL LIMIT ?"
                )
                rows = connection.execute(query, (low_cardinality_max + 1,)).fetchall()
                if len(rows) > low_cardinality_max:
                    continue
                values = [str(row[0]) for row in rows]
                if any(
                    is_pii_shaped_value(value) or _LONG_ID_PATTERN.fullmatch(value)
                    for value in values
                ):
                    warnings.append(f"Skipped PII-shaped values in {table.name}.{column.name}.")
                    upload_has_pii = True
                    continue
                for value in sorted(set(values), key=str.casefold):
                    value_documents.append({
                        "table_name": table.name,
                        "column_name": column.name,
                        "value": value,
                        "content": f"{table.name} {column.name} {value}",
                        "metadata_type": "master_value",
                    })
    except sqlite3.DatabaseError as error:
        raise UploadError("Could not safely read low-cardinality SQLite values.") from error
    finally:
        if connection is not None:
            connection.close()
    if upload_has_pii:
        warnings.append("Upload contains PII-shaped content; matching value columns are excluded.")
    return value_documents, sorted(set(warnings))


class DatasetRegistry:
    """Persist dataset schema and metadata without retaining SQL dump contents."""

    def __init__(self, root: str | Path = "datasets") -> None:
        self.root = Path(root)

    @staticmethod
    def _dataset_id(tenant_id: str, filename: str) -> str:
        _validate_tenant_dataset_id(tenant_id, "tenant_id")
        return str(uuid.uuid5(DATASET_NAMESPACE, f"{tenant_id}\0{filename}"))

    def _tenant_root(self, tenant_id: str) -> Path:
        _validate_tenant_dataset_id(tenant_id, "tenant_id")
        tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        return self.root / tenant_key

    def list_datasets(self, tenant_id: str) -> list[dict[str, Any]]:
        tenant_root = self._tenant_root(tenant_id)
        datasets = []
        for metadata_path in sorted(tenant_root.glob("*/dataset.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("tenant_id") == tenant_id:
                datasets.append(metadata)
        return datasets

    def load_schema(self, tenant_id: str, dataset_id: str) -> SchemaMetadata:
        _validate_tenant_dataset_id(tenant_id, "tenant_id")
        _validate_tenant_dataset_id(dataset_id, "dataset_id")
        dataset_dir = self._tenant_root(tenant_id) / dataset_id
        try:
            payload = json.loads((dataset_dir / "schema.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UploadError("Could not load the registered dataset schema.") from error
        return SchemaMetadata.from_dict(payload)

    def dataset_directory(self, tenant_id: str, dataset_id: str) -> Path:
        """Return the tenant-scoped local dataset directory."""
        _validate_tenant_dataset_id(tenant_id, "tenant_id")
        _validate_tenant_dataset_id(dataset_id, "dataset_id")
        return self._tenant_root(tenant_id) / dataset_id

    def load_value_documents(self, tenant_id: str, dataset_id: str) -> list[dict[str, Any]]:
        """Load persisted low-cardinality master values for vector indexing."""
        path = self.dataset_directory(tenant_id, dataset_id) / "value_documents.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UploadError("Could not load registered dataset values.") from error
        if not isinstance(payload, list):
            raise UploadError("Registered dataset values have an invalid format.")
        return payload

    def register(
        self,
        filename: str,
        content: bytes,
        tenant_id: str | None = None,
        dialect_override: str | None = None,
        max_upload_mb: int | None = None,
        parse_timeout_seconds: float | None = None,
        low_cardinality_max: int | None = None,
        embedding_model_name: str | None = None,
    ) -> dict[str, Any]:
        selected_tenant = tenant_id or os.getenv("TENANT_ID", "default")
        if not selected_tenant.strip():
            raise UploadError("Tenant ID cannot be empty.")
        _validate_tenant_dataset_id(selected_tenant, "tenant_id")
        filename = Path(filename).name
        suffix = Path(filename).suffix.casefold()
        if suffix not in {".sql", ".db"}:
            raise UploadError("Upload a .sql or SQLite .db file.")
        upload_limit = (
            int(os.getenv("MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB)))
            if max_upload_mb is None
            else max_upload_mb
        )
        if upload_limit < 1:
            raise UploadError("Upload size limit must be at least 1 MB.")
        if len(content) > upload_limit * 1024 * 1024:
            raise UploadError(f"Upload exceeds the {upload_limit} MB size limit.")
        low_max = (
            int(os.getenv("LOW_CARDINALITY_MAX", str(DEFAULT_LOW_CARDINALITY_MAX)))
            if low_cardinality_max is None
            else low_cardinality_max
        )
        if low_max < 0:
            raise UploadError("Low-cardinality threshold cannot be negative.")

        digest = hashlib.sha256(content).hexdigest()
        model_name = embedding_model_name or os.getenv(
            "EMBEDDING_MODEL", "all-MiniLM-L6-v2"
        )
        dataset_hash = make_dataset_hash(content, dialect_override, model_name)
        dataset_id = self._dataset_id(selected_tenant, filename)
        dataset_dir = self._tenant_root(selected_tenant) / dataset_id
        metadata_path = dataset_dir / "dataset.json"
        if metadata_path.is_file():
            try:
                previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
            if (
                previous.get("indexed") is True
                and previous.get("dataset_hash") == dataset_hash
                and previous.get("embedding_model_name") == model_name
            ):
                return {
                    **previous,
                    "dataset_hash": dataset_hash,
                    "status": "unchanged",
                    "warnings": [],
                }

        warnings: list[str] = []
        temporary_db: Path | None = None
        if suffix == ".sql":
            try:
                sql_text = content.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise UploadError("The .sql upload must be UTF-8 text.") from error
            if "\x00" in sql_text:
                raise UploadError("The .sql upload contains binary data.")
            detected_dialect = detect_sql_dialect(sql_text)
            dialect = dialect_override or detected_dialect
            if dialect.casefold() not in {"sqlite", "mysql", "postgres"}:
                raise UploadError("Choose SQLite, MySQL, or PostgreSQL as the SQL dialect.")
            timeout = (
                float(os.getenv("SQL_PARSE_TIMEOUT_SECONDS", str(DEFAULT_PARSE_TIMEOUT_SECONDS)))
                if parse_timeout_seconds is None
                else parse_timeout_seconds
            )
            schema, value_documents, warnings = parse_sql_dump(
                sql_text,
                dialect,
                timeout,
                low_cardinality_max=low_max,
            )
        else:
            if dialect_override and dialect_override.casefold() != "sqlite":
                raise UploadError("SQLite .db uploads always use the SQLite dialect.")
            dataset_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", suffix=".db", dir=dataset_dir)
            temporary_db = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as file_obj:
                    file_obj.write(content)
                schema = inspect_sqlite_database(temporary_db)
                value_documents, warnings = extract_sqlite_value_documents(
                    temporary_db,
                    schema,
                    low_cardinality_max=low_max,
                )
            except Exception:
                temporary_db.unlink(missing_ok=True)
                raise

        dataset_dir.mkdir(parents=True, exist_ok=True)
        if temporary_db is not None:
            os.replace(temporary_db, dataset_dir / "source.db")
        upload_pii = suffix == ".sql" and bool(
            _EMAIL_PATTERN.search(sql_text) or _LONG_ID_PATTERN.search(sql_text)
        )
        if upload_pii and "Upload contains PII-shaped content; matching value columns are excluded." not in warnings:
            warnings.append("Upload contains PII-shaped content; matching value columns are excluded.")
        timestamp = datetime.now(timezone.utc).isoformat()
        metadata = {
            "tenant_id": selected_tenant,
            "dataset_id": dataset_id,
            "filename": filename,
            "source_type": "sql" if suffix == ".sql" else "sqlite",
            "file_sha256": digest,
            "dialect_override": dialect_override,
            "dialect": schema.dialect,
            "created_at": timestamp,
            "table_count": len(schema.tables),
            "value_document_count": len(value_documents),
            "indexed": False,
        }
        self._write_json(dataset_dir / "schema.json", schema.to_dict())
        self._write_json(dataset_dir / "dataset.json", metadata)
        self._write_json(dataset_dir / "value_documents.json", value_documents)
        return {
            **metadata,
            "dataset_hash": dataset_hash,
            "status": "registered",
            "warnings": sorted(set(warnings)),
        }

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)