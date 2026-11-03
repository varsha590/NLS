"""Database schema metadata extraction for the Text-to-SQL RAG prototype."""

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from typing import Dict, List, Any, Optional
import json

EXCLUDED_SCHEMA_OBJECTS: set[str] = set()


# ---------------------------------------------------------------------------
# Schema metadata representation
# ---------------------------------------------------------------------------

class ColumnInfo:
    """Represents a single column in a database table."""

    def __init__(
        self,
        name: str,
        data_type: str,
        is_primary_key: bool = False,
        is_foreign_key: bool = False,
        foreign_table: Optional[str] = None,
        foreign_column: Optional[str] = None,
        comment: Optional[str] = None,
        sample_values: Optional[List[Any]] = None,
    ):
        self.name = name
        self.data_type = data_type
        self.is_primary_key = is_primary_key
        self.is_foreign_key = is_foreign_key
        self.foreign_table = foreign_table
        self.foreign_column = foreign_column
        self.comment = comment
        self.sample_values = sample_values or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "is_primary_key": self.is_primary_key,
            "is_foreign_key": self.is_foreign_key,
            "foreign_table": self.foreign_table,
            "foreign_column": self.foreign_column,
            "comment": self.comment,
            "sample_values": self.sample_values,
        }


class TableInfo:
    """Represents a database table with its columns, keys, and relationships."""

    def __init__(
        self,
        name: str,
        description: str,
        columns: List[ColumnInfo],
        primary_key_names: List[str],
        foreign_keys: List[Dict[str, Any]],
        schema: Optional[str] = None,
        comment: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        self.columns = columns
        self.primary_key_names = primary_key_names
        self.foreign_keys = foreign_keys  # list of {constrain_name, local_cols, remote_table, remote_cols}
        self.schema = schema
        self.comment = comment

    def to_schema_doc(self) -> str:
        """Convert to a retrievable schema document string."""
        lines = [f"Table: {self.name}"]
        lines.append(f"Description: {self.description}")
        lines.append("")
        lines.append("Columns:")
        for col in self.columns:
            flags = []
            if col.is_primary_key:
                flags.append("primary key")
            if col.is_foreign_key:
                flags.append(f"foreign key → {col.foreign_table}.{col.foreign_column}")
            flag_str = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"- {col.name}: {col.data_type}{flag_str}")
        lines.append("")
        lines.append("Relationships:")
        for fk in self.foreign_keys:
            local = fk["local_cols"][0] if fk["local_cols"] else ""
            remote = fk["remote_table"]
            remote_col = fk["remote_cols"][0] if fk["remote_cols"] else ""
            lines.append(
                f"- {self.name}.{local} → {remote}.{remote_col}"
            )
        # Emit a business-relevance section only when FK relationships exist,
        # so the content is always derived from the actual schema rather than
        # from hard-coded, domain-specific assumptions.
        if self.foreign_keys:
            lines.append("")
            lines.append("Business relevance:")
            for fk in self.foreign_keys:
                local_cols = ", ".join(fk["local_cols"]) if fk["local_cols"] else ""
                remote_table = fk["remote_table"]
                remote_cols = ", ".join(fk["remote_cols"]) if fk["remote_cols"] else ""
                if local_cols and remote_table and remote_cols:
                    lines.append(
                        f"- {self.name}.{local_cols} links to {remote_table}.{remote_cols}."
                    )
        return "\n".join(lines)


class SchemaMetadata:
    """Holds metadata for all tables in the database."""

    def __init__(self, tables: Dict[str, TableInfo]):
        self.tables = tables
        self.version = "1.0"

    def get_table(self, name: str) -> Optional[TableInfo]:
        return self.tables.get(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "tables": {
                name: {
                    "name": t.name,
                    "schema": t.schema,
                    "comment": t.comment,
                    "description": t.description,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_primary_key": c.is_primary_key,
                            "is_foreign_key": c.is_foreign_key,
                            "foreign_table": c.foreign_table,
                            "foreign_column": c.foreign_column,
                            "comment": c.comment,
                            "sample_values": c.sample_values,
                        }
                        for c in t.columns
                    ],
                    "primary_key_names": t.primary_key_names,
                    "foreign_keys": t.foreign_keys,
                }
                for name, t in self.tables.items()
            },
        }

    @classmethod
    def from_engine(cls, engine: sa.Engine) -> "SchemaMetadata":
        """Inspect the default schema without assuming application table names."""
        inspector = sa_inspect(engine)
        tables: Dict[str, TableInfo] = {}

        # Get all table names
        all_tables = [(None, name) for name in inspector.get_table_names()]

        for schema_name, table_name in all_tables:
            if table_name in EXCLUDED_SCHEMA_OBJECTS:
                continue
            # Get columns
            inspect_kwargs = {"schema": schema_name} if schema_name else {}
            cols = inspector.get_columns(table_name, **inspect_kwargs)
            column_infos = []
            pk_names = []
            for col in cols:
                name = col["name"]
                data_type = col.get("type", "").python_type.__name__ if col.get("type") else "Unknown"
                if hasattr(col.get("type"), "__class__"):
                    data_type = str(col["type"])
                else:
                    data_type = str(col.get("type", "Unknown"))

                is_pk = False
                pk_constraint = inspector.get_pk_constraint(table_name, **inspect_kwargs)
                constrained_cols = pk_constraint.get("constrained_columns", [])
                if name in constrained_cols:
                    is_pk = True
                if is_pk:
                    pk_names.append(name)

                # Check foreign keys
                is_fk = False
                fk_table = None
                fk_column = None
                fk_info = inspector.get_foreign_keys(table_name, **inspect_kwargs)
                for fk in fk_info:
                    if name in fk["constrained_columns"]:
                        is_fk = True
                        fk_table = fk["referred_table"]
                        fk_column = fk["referred_columns"][
                            fk["constrained_columns"].index(name)
                        ]
                        break

                column_infos.append(
                    ColumnInfo(
                        name=name,
                        data_type=data_type,
                        is_primary_key=is_pk,
                        is_foreign_key=is_fk,
                        foreign_table=fk_table,
                        foreign_column=fk_column,
                    )
                )

            # Get foreign key relationships for this table
            fk_relationships = inspector.get_foreign_keys(table_name, **inspect_kwargs)
            try:
                table_comment = inspector.get_table_comment(
                    table_name, **inspect_kwargs
                ).get("text")
            except (AttributeError, NotImplementedError, sa.exc.SQLAlchemyError):
                table_comment = None

            tables[table_name] = TableInfo(
                name=table_name,
                # Prefer the database-provided table comment; fall back to a
                # neutral description that does not embed domain assumptions.
                description=table_comment or f"Table {table_name}.",
                columns=column_infos,
                primary_key_names=pk_names,
                foreign_keys=[
                    {
                        "constrain_name": fk["name"],
                        "local_cols": fk["constrained_columns"],
                        "remote_table": fk["referred_table"],
                        "remote_cols": fk["referred_columns"],
                    }
                    for fk in fk_relationships
                ],
                schema=schema_name,
                comment=table_comment,
            )

        return cls(tables)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SchemaMetadata":
        """Restore schema metadata from the local catalog representation."""
        tables = {}
        for name, table_data in data.get("tables", {}).items():
            columns = [ColumnInfo(**column) for column in table_data.get("columns", [])]
            tables[name] = TableInfo(
                name=table_data.get("name", name),
                description=table_data.get("description", ""),
                columns=columns,
                primary_key_names=table_data.get("primary_key_names", []),
                foreign_keys=table_data.get("foreign_keys", []),
                schema=table_data.get("schema"),
                comment=table_data.get("comment"),
            )
        result = cls(tables)
        result.version = data.get("version", "1.0")
        return result


def build_demo_schema_metadata(engine: sa.Engine) -> SchemaMetadata:
    """Backward-compatible alias for generic live schema inspection."""
    return SchemaMetadata.from_engine(engine)