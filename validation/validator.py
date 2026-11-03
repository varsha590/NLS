"""Dialect-aware SQL parsing and catalog validation."""

from __future__ import annotations

import difflib
import re
from typing import Any

import sqlglot
from sqlglot import exp

from db.adapter import DatabaseAdapter
from retrieval.value_index import ValueIndex
from schema.metadata import SchemaMetadata

try:
    from config.data_policy import is_blocked, blocked_columns_for_table
except Exception:
    def is_blocked(key: str) -> bool:
        return False
    def blocked_columns_for_table(table_name: str, column_names: list) -> set:
        return set()


class ValidationError(ValueError):
    """Raised when generated SQL is unsafe or does not match the catalog."""


class ValueSafetyError(ValueError):
    """Raised when a SQL literal cannot be verified against the value index."""
    def __init__(self, message: str, kind: str, mention: str, column: str | None, closest: list[str]):
        super().__init__(message)
        self.kind = kind  # "ambiguous" or "not_found"
        self.mention = mention
        self.column = column
        self.closest = closest


def _contains_comment(sql: str) -> bool:
    """Detect SQL comments outside quoted literals and identifiers."""
    quote: str | None = None
    index = 0
    while index < len(sql):
        character = sql[index]
        if quote:
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif character in ("'", '"', "`"):
            quote = character
        elif character == "[":
            quote = "]"
        elif sql.startswith("--", index) or sql.startswith("/*", index):
            return True
        index += 1
    return False


def _table_key(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def _catalog_lookup(metadata: SchemaMetadata) -> dict[str, object]:
    return {name.casefold(): table for name, table in metadata.tables.items()}


def _suggest_column(table_name: str | None, column_name: str, metadata: SchemaMetadata) -> str:
    matches = []
    tables = [metadata.tables[table_name]] if table_name in metadata.tables else metadata.tables.values()
    for table in tables:
        for column in table.columns:
            qualified = f"{table.name}.{column.name}"
            matches.append((qualified, column.name))
    names = [name for name, _ in matches]
    closest = difflib.get_close_matches(column_name, [value for _, value in matches], n=1, cutoff=0.55)
    if closest:
        target = next(name for name, value in matches if value == closest[0])
        return f"; did you mean {target}"
    qualified_closest = difflib.get_close_matches(
        f"{table_name or ''}.{column_name}", names, n=1, cutoff=0.45
    )
    return f"; did you mean {qualified_closest[0]}" if qualified_closest else ""


def _normalize_value(value: str) -> str:
    """Normalize a value for comparison."""
    return re.sub(r"[\W_]+", " ", value.casefold()).strip()


def _is_value_column(column_key: str, value_index: ValueIndex | None) -> bool:
    """Check if a column is a configured value column."""
    if value_index is None:
        return False
    return column_key in value_index.values


def _resolve_literal_against_index(
    literal: str,
    column_key: str,
    value_index: ValueIndex,
    resolved_values: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """
    Resolve a literal against the value index for a column.
    Returns (canonical_value, error_message, closest_values).
    - If exact match: returns (literal, None, [])
    - If unique match: returns (canonical_value, None, [])
    - If ambiguous: returns (None, "ambiguous", closest_values)
    - If not found: returns (None, "not_found", closest_values)
    """
    if column_key not in value_index.values:
        return (literal, None, [])
    
    column_values = value_index.values[column_key]
    literal_lower = literal.casefold()
    
    # Check exact match (case-insensitive)
    for value in column_values:
        if value.casefold() == literal_lower:
            return (value, None, [])
    
    # Check if already resolved
    if resolved_values:
        for rv in resolved_values:
            if rv.get("column") == column_key and rv.get("mention", "").casefold() == literal_lower:
                return (rv["value"], None, [])
    
    # Use value index resolve logic
    matches = value_index.resolve(literal, column_key, top_k=5)
    candidates = matches.get("candidates", [])
    resolved = matches.get("resolved")
    
    if resolved:
        # Unique high-confidence match
        return (resolved["value"], None, [])
    
    if candidates:
        # Check if ambiguous (multiple close candidates)
        best = candidates[0]
        close = [
            c for c in candidates
            if best["confidence"] - c["confidence"] < value_index.ambiguous_gap
        ]
        if len(close) >= 2:
            return (None, "ambiguous", [c["value"] for c in close[:value_index.max_candidates]])
    
    # Not found - return closest values from score candidates
    closest = []
    try:
        sc = value_index._score_candidates(literal, column_key, value_index.max_candidates)
        closest = [c["value"] for c in sc[:value_index.max_candidates]]
    except Exception:
        closest = []
    return (None, "not_found", closest)


def _check_and_rewrite_literals(
    parsed: exp.Expression,
    table_aliases: dict[str, str],
    catalog: dict[str, object],
    value_index: ValueIndex | None,
    resolved_values: list[dict[str, Any]] | None,
    dialect: str | None,
) -> tuple[str | None, list[str]]:
    """
    Check string literals in comparisons against value index.
    Returns (rewritten_sql, errors).
    If errors, the query should not be executed.
    """
    if value_index is None:
        return (None, [])
    
    errors: list[str] = []
    rewrites: list[tuple[exp.Expression, str]] = []  # (node, new_value)
    
    # Find all comparisons: EQ, IN, LIKE, ILIKE
    for node in parsed.walk():
        if isinstance(node, (exp.EQ, exp.NEQ, exp.Like, exp.ILike)):
            # Check if one side is a column and the other is a literal
            left, right = node.left, node.right
            column_node = None
            literal_node = None
            
            # Handle direct column comparisons and function-wrapped columns (LOWER, UPPER, etc.)
            col_candidate = None
            lit_candidate = None
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
                col_candidate = left
                lit_candidate = right
            elif isinstance(right, exp.Column) and isinstance(left, exp.Literal) and left.is_string:
                col_candidate = right
                lit_candidate = left
            elif isinstance(left, exp.Func) and isinstance(right, exp.Literal) and right.is_string:
                # Check if function wraps a column (LOWER(col), UPPER(col), etc.)
                if left.this and isinstance(left.this, exp.Column):
                    col_candidate = left.this
                    lit_candidate = right
            elif isinstance(right, exp.Func) and isinstance(left, exp.Literal) and left.is_string:
                if right.this and isinstance(right.this, exp.Column):
                    col_candidate = right.this
                    lit_candidate = left
            
            if col_candidate is not None and lit_candidate is not None:
                column_node = col_candidate
                literal_node = lit_candidate
            
            if column_node and literal_node:
                literal_value = literal_node.this
                # Resolve column to qualified name
                col_table = column_node.table
                col_name = column_node.name
                column_key = None
                
                if col_table:
                    table_key = table_aliases.get(col_table.casefold())
                    if table_key:
                        column_key = f"{table_key}.{col_name}"
                else:
                    # Unqualified column - find in used tables
                    for table_key, table in catalog.items():
                        if col_name.casefold() in {c.name.casefold() for c in table.columns}:
                            column_key = f"{table_key}.{col_name}"
                            break
                
                if column_key and _is_value_column(column_key, value_index):
                    canonical, error, closest = _resolve_literal_against_index(
                        literal_value, column_key, value_index, resolved_values
                    )
                    if error == "ambiguous":
                        errors.append(
                            f"Ambiguous value '{literal_value}' for {column_key}. "
                            f"Closest: {', '.join(closest)}"
                        )
                    elif error == "not_found":
                        errors.append(
                            f"No matching value found for '{literal_value}' in {column_key}. "
                            f"Closest: {', '.join(closest) if closest else 'none'}"
                        )
                    elif canonical and canonical != literal_value:
                        # Adjust canonical value case to match function wrapper
                        rewritten_value = canonical
                        if isinstance(left if False else None, str):
                            pass
                        # Check if column was wrapped in a case function
                        original_left = node.left
                        if isinstance(original_left, exp.Func):
                            func_name = original_left.sql_name().upper() if hasattr(original_left, 'sql_name') else str(original_left.key).upper()
                            if 'LOWER' in func_name:
                                rewritten_value = canonical.casefold()
                            elif 'UPPER' in func_name:
                                rewritten_value = canonical.upper()
                        original_right = node.right
                        if isinstance(original_right, exp.Func):
                            func_name = original_right.sql_name().upper() if hasattr(original_right, 'sql_name') else str(original_right.key).upper()
                            if 'LOWER' in func_name:
                                rewritten_value = canonical.casefold()
                            elif 'UPPER' in func_name:
                                rewritten_value = canonical.upper()
                        rewrites.append((literal_node, rewritten_value))
        
        elif isinstance(node, exp.In):
            # Check IN clause: column IN (literal, literal, ...)
            if isinstance(node.this, exp.Column) and node.expressions:
                column_node = node.this
                literal_values = []
                literal_nodes = []
                for expr in node.expressions:
                    if isinstance(expr, exp.Literal) and expr.is_string:
                        literal_values.append(expr.this)
                        literal_nodes.append(expr)
                
                if literal_values and literal_nodes:
                    col_table = column_node.table
                    col_name = column_node.name
                    column_key = None
                    
                    if col_table:
                        table_key = table_aliases.get(col_table.casefold())
                        if table_key:
                            column_key = f"{table_key}.{col_name}"
                    else:
                        for table_key, table in catalog.items():
                            if col_name.casefold() in {c.name.casefold() for c in table.columns}:
                                column_key = f"{table_key}.{col_name}"
                                break
                    
                    if column_key and _is_value_column(column_key, value_index):
                        for literal_value, literal_node in zip(literal_values, literal_nodes):
                            canonical, error, closest = _resolve_literal_against_index(
                                literal_value, column_key, value_index, resolved_values
                            )
                            if error == "ambiguous":
                                errors.append(
                                    f"Ambiguous value '{literal_value}' for {column_key}. "
                                    f"Closest: {', '.join(closest)}"
                                )
                            elif error == "not_found":
                                errors.append(
                                    f"No matching value found for '{literal_value}' in {column_key}. "
                                    f"Closest: {', '.join(closest) if closest else 'none'}"
                                )
                            elif canonical and canonical != literal_value:
                                rewrites.append((literal_node, canonical))
    
    # Apply rewrites
    for node, new_value in rewrites:
        node.set("this", new_value)
    
    if errors:
        return (None, errors)
    
    if rewrites:
        return (parsed.sql(dialect=dialect), [])
    
    return (None, [])


def validate_sql(
    sql: str,
    metadata: SchemaMetadata,
    dialect: str | None,
    allowed_tables: set[str] | None = None,
    max_rows: int = 100,
    adapter: DatabaseAdapter | None = None,
    value_index: ValueIndex | None = None,
    resolved_values: list[dict[str, Any]] | None = None,
) -> str:
    """Validate one SELECT, verify catalog references, enforce LIMIT, and explain it."""
    source = sql.strip().rstrip(";").strip()
    if not source:
        raise ValidationError("The SQL generator returned an empty statement.")
    if _contains_comment(source):
        raise ValidationError("SQL comments are not allowed in generated queries.")
    try:
        statements = [statement for statement in sqlglot.parse(source, read=dialect) if statement]
    except sqlglot.errors.ParseError as error:
        raise ValidationError(f"Could not parse SQL for the configured dialect: {error}") from error
    if len(statements) != 1:
        raise ValidationError("Multiple SQL statements detected. Only one SELECT is allowed.")
    parsed = statements[0]
    if not isinstance(parsed, exp.Select):
        raise ValidationError("Only a single SELECT statement is allowed.")
    forbidden = tuple(
        expression
        for expression in (
            exp.Insert,
            exp.Update,
            exp.Delete,
            exp.Drop,
            exp.Alter,
            exp.Create,
            getattr(exp, "Truncate", None),
            getattr(exp, "Grant", None),
        )
        if isinstance(expression, type)
    )
    if any(parsed.find_all(*forbidden)):
        raise ValidationError("Mutating SQL statements are not allowed.")

    catalog = _catalog_lookup(metadata)
    allowed = {name.casefold() for name in allowed_tables} if allowed_tables is not None else set(catalog)
    cte_names = {cte.alias_or_name.casefold() for cte in parsed.find_all(exp.CTE)}
    table_aliases: dict[str, str] = {}
    used_tables: dict[str, object] = {}
    for table_node in parsed.find_all(exp.Table):
        table_name = _table_key(table_node)
        if not table_node.db and table_name.casefold() in cte_names:
            continue
        table = catalog.get(table_name.casefold())
        if table is None:
            alternatives = difflib.get_close_matches(table_name, list(metadata.tables), n=1, cutoff=0.55)
            suggestion = f"; did you mean {alternatives[0]}" if alternatives else ""
            raise ValidationError(f"table {table_name} does not exist in the catalog{suggestion}.")
        if table_name.casefold() not in allowed:
            raise ValidationError(f"table {table_name} was not included in the provided schema.")
        used_tables[table_name.casefold()] = table
        table_aliases[table_node.alias_or_name.casefold()] = table_name.casefold()
        table_aliases[table_node.name.casefold()] = table_name.casefold()

    projection_aliases = {
        projection.alias.casefold()
        for projection in parsed.expressions
        if isinstance(projection, exp.Alias) and projection.alias
    }
    for column_node in parsed.find_all(exp.Column):
        if column_node.name == "*" or column_node.name.casefold() in projection_aliases:
            continue
        resolved_table_name = None
        if column_node.table:
            resolved_table_name = table_aliases.get(column_node.table.casefold())
            if resolved_table_name is None and column_node.table.casefold() in cte_names:
                continue
            if resolved_table_name is None:
                resolved_table_name = column_node.table.casefold()
            table = catalog.get(resolved_table_name)
            if table is None:
                raise ValidationError(f"table or alias {column_node.table} does not exist in the catalog.")
            if column_node.name.casefold() not in {column.name.casefold() for column in table.columns}:
                suggestion = _suggest_column(table.name, column_node.name, metadata)
                raise ValidationError(
                    f"column {column_node.table}.{column_node.name} does not exist{suggestion}."
                )
            continue
        matching = [
            (table_name, table)
            for table_name, table in used_tables.items()
            if column_node.name.casefold() in {column.name.casefold() for column in table.columns}
        ]
        if not matching:
            suggestion = _suggest_column(None, column_node.name, metadata)
            raise ValidationError(f"column {column_node.name} does not exist{suggestion}.")
        if len(matching) > 1:
            raise ValidationError(
                f"column {column_node.name} is ambiguous; qualify it with a table name."
            )

    # Blocked column check (data policy)
    _BLOCKED_MSG = "That information isn't available."
    # Check exp.Star (SELECT *) and qualified stars (t.*)
    for star in parsed.find_all(exp.Star):
        # Find the table this star belongs to
        parent = star.parent
        if isinstance(parent, exp.Column):
            # t.* case
            table_alias = parent.table
            table_key = table_aliases.get(table_alias.casefold()) if table_alias else None
            if table_key:
                table_obj = catalog.get(table_key)
                if table_obj:
                    cols = [c.name for c in table_obj.columns]
                    tbl_name = table_key.rsplit(".", 1)[-1]
                    if blocked_columns_for_table(tbl_name, cols):
                        raise ValidationError(_BLOCKED_MSG)
        elif isinstance(parent, exp.Select):
            # SELECT * case - check all used tables
            for table_key in used_tables:
                table_obj = catalog.get(table_key)
                if table_obj:
                    cols = [c.name for c in table_obj.columns]
                    tbl_name = table_key.rsplit(".", 1)[-1]
                    if blocked_columns_for_table(tbl_name, cols):
                        raise ValidationError(_BLOCKED_MSG)

    # Check all column references (including in functions, subqueries, CTEs, etc.)
    for col_node in parsed.find_all(exp.Column):
        if col_node.name == "*":
            continue
        # Resolve to qualified column key
        col_table = col_node.table
        col_name = col_node.name
        table_key = None
        if col_table:
            table_key = table_aliases.get(col_table.casefold())
        else:
            # Unqualified - find in used tables
            for tk, tobj in used_tables.items():
                if col_name.casefold() in {c.name.casefold() for c in tobj.columns}:
                    table_key = tk
                    break
        if table_key:
            tbl_name = table_key.rsplit(".", 1)[-1]
            full_key = f"{tbl_name}.{col_name}"
            if is_blocked(full_key):
                raise ValidationError(_BLOCKED_MSG)

    limit = parsed.args.get("limit")
    if limit is None:
        parsed = parsed.limit(max_rows)
    else:
        expression = limit.expression
        if isinstance(expression, exp.Literal) and expression.is_int:
            if int(expression.this) > max_rows:
                limit.set("expression", exp.Literal.number(max_rows))
        else:
            limit.set("expression", exp.Literal.number(max_rows))
    # Literal safety net: check string literals against value index
    rewritten_sql, errors = _check_and_rewrite_literals(
        parsed, table_aliases, catalog, value_index, resolved_values, dialect
    )
    if errors:
        # Parse first error to extract structured info
        error_msg = errors[0]
        # Determine kind
        if "Ambiguous value" in error_msg:
            kind = "ambiguous"
            import re
            m = re.search(r"Ambiguous value '([^']+)' for (\S+)\. Closest: (.+)", error_msg)
            mention = m.group(1) if m else ""
            column = m.group(2) if m else None
            closest = [v.strip() for v in m.group(3).split(",")] if m else []
        else:
            kind = "not_found"
            import re
            m = re.search(r"No matching value found for '([^']+)' in (\S+)\. Closest: (.+)", error_msg)
            mention = m.group(1) if m else ""
            column = m.group(2) if m else None
            closest_str = m.group(3) if m else ""
            closest = [v.strip() for v in closest_str.split(",")] if closest_str and closest_str != "none" else []
        raise ValueSafetyError(error_msg, kind, mention, column, closest)
    if rewritten_sql:
        normalized = rewritten_sql
    else:
        normalized = parsed.sql(dialect=dialect)
    if adapter is not None:
        try:
            adapter.explain(normalized)
        except Exception as error:
            raise ValidationError(f"The query failed its EXPLAIN dry-run: {error}") from error
    return normalized