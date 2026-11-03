"""Schema context builder for Text-to-SQL RAG prototype.

Builds compact, exact schema context from SchemaMetadata for the LLM.
No column truncation - includes all columns with PK/FK annotations.
"""

from typing import List, Optional

from .metadata import (
    EXCLUDED_SCHEMA_OBJECTS,
    SchemaMetadata,
    TableInfo,
    ColumnInfo,
)

try:
    from config.data_policy import is_blocked
except Exception:
    def is_blocked(key: str) -> bool:
        return False


def build_column_line(col: ColumnInfo) -> str:
    """Format an exact column name with its key relationship, if any."""
    flags = []
    if col.is_primary_key:
        flags.append("PK")
    if col.is_foreign_key and col.foreign_table and col.foreign_column:
        flags.append(f"FK->{col.foreign_table}.{col.foreign_column}")
    return f"{col.name} {' '.join(flags)}".strip()


def build_table_line(table: TableInfo) -> str:
    """Format a table as a compact one-liner with all non-blocked columns."""
    allowed_cols = [col for col in table.columns if not is_blocked(f"{table.name}.{col.name}")]
    col_lines = [build_column_line(col) for col in allowed_cols]
    return f"{table.name}({', '.join(col_lines)})"


def build_relationship_lines(table: TableInfo) -> List[str]:
    """Format FK relationships for a table."""
    lines = []
    for fk in table.foreign_keys:
        local_cols = fk.get("local_cols", [])
        remote_table = fk.get("remote_table", "")
        remote_cols = fk.get("remote_cols", [])
        if local_cols and remote_table and remote_cols:
            local = local_cols[0]
            remote = remote_cols[0]
            lines.append(f"  {table.name}.{local} -> {remote_table}.{remote}")
    return lines


def build_schema_context(
    metadata: SchemaMetadata,
    table_names: List[str],
    include_business_rules: bool = True,
    value_hints: Optional[str] = None,
) -> str:
    """
    Build the complete schema context string for the LLM.
    
    Args:
        metadata: SchemaMetadata with all table info
        table_names: List of table names to include (retrieved + FK-expanded)
        include_business_rules: Whether to append business metric definitions
        value_hints: Optional formatted VALUE HINTS section
    
    Returns:
        Compact schema context string
    """
    parts = []
    
    hint_table_names = []
    if isinstance(value_hints, list):
        hint_table_names = [
            hint["column"].split(".", 1)[0]
            for hint in value_hints
            if isinstance(hint, dict) and "column" in hint
        ]
    unique_table_names = list(dict.fromkeys([*table_names, *hint_table_names]))
    unique_table_names = [
        name for name in unique_table_names if name not in EXCLUDED_SCHEMA_OBJECTS
    ]

    # Table definitions
    parts.append("=== SCHEMA ===")
    for table_name in unique_table_names:
        table = metadata.get_table(table_name)
        if not table:
            continue
        # Filter out blocked columns
        allowed_cols = [c for c in table.columns if not is_blocked(f"{table_name}.{c.name}")]
        if not allowed_cols:
            continue
        # Build table line with only allowed columns
        col_lines = [build_column_line(col) for col in allowed_cols]
        parts.append(f"{table.name}({', '.join(col_lines)})")
    
    # Value hints (resolved user mentions to catalog values)
    if isinstance(value_hints, list) and value_hints:
        parts.append("")
        parts.append("=== VALUE HINTS ===")
        for hint in value_hints:
            parts.append(
                f"- {hint['mention']!r} -> {hint['column']} = {hint['value']!r}"
            )
    elif value_hints:
        parts.append("")
        parts.append(value_hints)
    
    return "\n".join(parts)


def get_expanded_table_names(
    metadata: SchemaMetadata,
    initial_tables: List[str],
) -> List[str]:
    """
    Expand initial table list by following FK relationships.
    Returns ordered list: initial tables first, then FK dependencies.
    """
    expanded = list(initial_tables)
    added = set(expanded)
    changed = True
    
    while changed:
        changed = False
        for table_name in list(added):
            table = metadata.get_table(table_name)
            if not table:
                continue
            for fk in table.foreign_keys:
                remote = fk.get("remote_table")
                if remote and remote not in added:
                    added.add(remote)
                    expanded.append(remote)
                    changed = True
    
    return expanded


def build_full_context(
    metadata: SchemaMetadata,
    retrieved_table_names: List[str],
    value_hints: Optional[str] = None,
) -> tuple[str, List[str]]:
    """
    Build complete context from retrieved tables.
    
    Returns:
        (schema_context_string, expanded_table_names)
    """
    expanded = get_expanded_table_names(metadata, retrieved_table_names)
    context = build_schema_context(metadata, expanded, value_hints=value_hints)
    return context, expanded