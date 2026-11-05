"""Dialect-aware SQL parsing and catalog validation."""

from __future__ import annotations

import difflib
import re
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from retrieval.value_index import ValueIndex
from schema.metadata import SchemaMetadata
from config.data_policy import is_blocked, is_masked, blocked_columns_for_table


FORBIDDEN_FUNCTIONS = frozenset({
    "pg_sleep",
    "pg_read_file",
    "load_extension",
    "dblink",
    "sleep",
    "benchmark",
})


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


def _is_select_alias_reference(column: exp.Column, scope: Scope | None) -> bool:
    """Allow only this SELECT's aliases in ORDER BY, GROUP BY, or HAVING."""
    if scope is None or column.table:
        return False
    aliases = {
        projection.alias.casefold()
        for projection in scope.expression.selects
        if isinstance(projection, exp.Alias) and projection.alias
    }
    if column.name.casefold() not in aliases:
        return False

    parent = column.parent
    while parent is not None and parent is not scope.expression:
        if isinstance(parent, (exp.Order, exp.Group, exp.Having)):
            return True
        parent = parent.parent
    return False


def _scope_for_column(
    column: exp.Column,
    scope_by_expression: dict[int, Scope],
) -> Scope | None:
    """Find the nearest SELECT scope, including columns omitted from scope.columns."""
    parent: exp.Expression | None = column
    while parent is not None:
        if isinstance(parent, exp.Select):
            return scope_by_expression.get(id(parent))
        parent = parent.parent
    return None


def _is_derived_column_reference(column: exp.Column, scope: Scope | None) -> bool:
    """Return whether a qualified name is an output of a CTE or subquery."""
    if scope is None or not column.table:
        return False
    source = scope.sources.get(column.table.casefold())
    return isinstance(source, Scope) and any(
        projection.alias_or_name.casefold() == column.name.casefold()
        for projection in source.expression.selects
    )


def _validate_read_only_ast(parsed: exp.Expression) -> None:
    """Reject non-query statements and unsafe constructs anywhere in the AST."""
    if not isinstance(parsed, (exp.Select, exp.SetOperation)):
        raise ValidationError("Only a single read-only SELECT query is allowed.")

    forbidden_types = tuple(
        expression
        for expression in (
            exp.DML,
            exp.DDL,
            getattr(exp, "Command", None),
            getattr(exp, "Copy", None),
            getattr(exp, "Pragma", None),
        )
        if isinstance(expression, type)
    )
    for node in parsed.walk():
        if forbidden_types and isinstance(node, forbidden_types):
            raise ValidationError("Mutating or administrative SQL constructs are not allowed.")
        if isinstance(node, exp.Select):
            if node.args.get("into") is not None:
                raise ValidationError("SELECT INTO is not allowed.")
            if node.args.get("locks"):
                raise ValidationError("Locking reads are not allowed.")
        if isinstance(node, exp.Func):
            function_names = {node.name.casefold(), node.sql_name().casefold()}
            if function_names & FORBIDDEN_FUNCTIONS:
                raise ValidationError("A restricted SQL function was requested.")


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


def _column_class(column_key: str, value_index: ValueIndex) -> str:
    if column_key in value_index.values:
        return "VALUE_LOW"
    if column_key in value_index.large_columns:
        return "VALUE_HIGH"
    table_name, _, column_name = column_key.rpartition(".")
    table = next(
        (item for name, item in value_index.metadata.tables.items() if name.casefold() == table_name.casefold()),
        None,
    )
    if table is None:
        return "SKIP"
    entry = value_index.classification_cache.get(table.name, {}).get("columns", {}).get(column_name, {})
    return str(entry.get("class", "SKIP"))


def _scope_column_key(
    column: exp.Column,
    scope: Scope | None,
    metadata: SchemaMetadata,
    scope_by_expression: dict[int, Scope],
    visited: set[tuple[int, str]],
) -> str | None:
    if scope is None:
        return None
    marker = (id(scope.expression), column.sql())
    if marker in visited:
        return None
    visited.add(marker)

    def resolve_source(source: Any, source_scope: Scope, name: str) -> str | None:
        if isinstance(source, exp.Table):
            table_key = _table_key(source)
            table = next(
                (item for key, item in metadata.tables.items() if key.casefold() == table_key.casefold()),
                None,
            )
            if table is None:
                return None
            actual_column = next(
                (item.name for item in table.columns if item.name.casefold() == name.casefold()),
                None,
            )
            return f"{table.name}.{actual_column}" if actual_column else None
        if isinstance(source, Scope):
            projections = [
                projection for projection in source.expression.selects
                if projection.alias_or_name.casefold() == name.casefold()
            ]
            if len(projections) != 1:
                return None
            child_scope = scope_by_expression.get(id(source.expression))
            inner_columns = list(projections[0].find_all(exp.Column))
            if child_scope is None or len(inner_columns) != 1:
                return None
            return _scope_column_key(
                inner_columns[0], child_scope, metadata, scope_by_expression, visited
            )
        return None

    if column.table:
        source = scope.sources.get(column.table.casefold())
        return resolve_source(source, scope, column.name) if source is not None else None

    matches = []
    for source in scope.sources.values():
        resolved = resolve_source(source, scope, column.name)
        if resolved and resolved not in matches:
            matches.append(resolved)
    return matches[0] if len(matches) == 1 else None


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
    used_tables: dict[str, object] | None = None,
    policy_overrides: dict[str, Any] | None = None,
) -> tuple[str | None, list[str]]:
    """Check string literals in comparisons against value index.

    Unqualified column references are resolved only against *used_tables* (the
    tables actually referenced by the query), not the full catalog.  This
    prevents false-positive value-safety rejections on same-named columns in
    tables that are not part of the current query (0g fix).

    Returns (rewritten_sql, errors).
    If errors, the query should not be executed.
    """
    if value_index is None:
        return (None, [])

    # Columns are resolved against the tables actually used by the query.
    # Fall back to the full catalog only if used_tables is not provided (0g fix).
    column_scope = used_tables if used_tables else catalog

    errors: list[str] = []
    rewrites: list[tuple[exp.Expression, str]] = []  # (node, new_value)
    scopes = list(traverse_scope(parsed))
    scope_by_expression = {id(scope.expression): scope for scope in scopes}
    scope_by_column = {
        id(column): scope
        for scope in scopes
        for column in scope.columns
    }
    
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
                scope = scope_by_column.get(id(column_node))
                column_key = _scope_column_key(
                    column_node, scope, value_index.metadata, scope_by_expression, set()
                )
                column_class = _column_class(column_key, value_index) if column_key else "SKIP"
                if column_key and (
                    column_class in {"BLOCKED", "MASKED"}
                    or is_blocked(column_key, policy_overrides=policy_overrides)
                    or is_masked(column_key, policy_overrides=policy_overrides)
                ):
                    errors.append(f"Literal filter on restricted column {column_key} rejected.")
                elif column_key and isinstance(node, (exp.Like, exp.ILike)):
                    continue
                elif column_key and column_class == "VALUE_HIGH":
                    confirmed = next(
                        (
                            item for item in (resolved_values or [])
                            if item.get("column", "").casefold() == column_key.casefold()
                            and item.get("mention", "").casefold() == literal_value.casefold()
                            and item.get("value")
                        ),
                        None,
                    )
                    resolved = (
                        {"status": "resolved", "value": confirmed["value"]}
                        if confirmed is not None
                        else value_index.resolve_high_value(column_key, literal_value)
                    )
                    if resolved["status"] == "resolved":
                        if resolved["value"] != literal_value:
                            rewrites.append((literal_node, resolved["value"]))
                    elif resolved["status"] == "ambiguous":
                        value_index.pending_confirmation = {
                            "mention": literal_value,
                            "column": column_key,
                            "candidates": resolved["candidates"],
                        }
                        errors.append(f"Ambiguous VALUE_HIGH value for {column_key}.")
                elif column_key and column_class == "VALUE_LOW" and _is_value_column(column_key, value_index):
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
                    scope = scope_by_column.get(id(column_node))
                    column_key = _scope_column_key(
                        column_node, scope, value_index.metadata, scope_by_expression, set()
                    )
                    column_class = _column_class(column_key, value_index) if column_key else "SKIP"
                    if column_key and (
                        column_class in {"BLOCKED", "MASKED"}
                        or is_blocked(column_key, policy_overrides=policy_overrides)
                        or is_masked(column_key, policy_overrides=policy_overrides)
                    ):
                        errors.append(f"Literal filter on restricted column {column_key} rejected.")
                    elif column_key and column_class == "VALUE_HIGH":
                        for literal_value, literal_node in zip(literal_values, literal_nodes):
                            confirmed = next(
                                (
                                    item for item in (resolved_values or [])
                                    if item.get("column", "").casefold() == column_key.casefold()
                                    and item.get("mention", "").casefold() == literal_value.casefold()
                                    and item.get("value")
                                ),
                                None,
                            )
                            resolved = (
                                {"status": "resolved", "value": confirmed["value"]}
                                if confirmed is not None
                                else value_index.resolve_high_value(column_key, literal_value)
                            )
                            if resolved["status"] == "resolved":
                                if resolved["value"] != literal_value:
                                    rewrites.append((literal_node, resolved["value"]))
                            elif resolved["status"] == "ambiguous":
                                value_index.pending_confirmation = {
                                    "mention": literal_value,
                                    "column": column_key,
                                    "candidates": resolved["candidates"],
                                }
                                errors.append(f"Ambiguous VALUE_HIGH value for {column_key}.")
                    elif column_key and column_class == "VALUE_LOW" and _is_value_column(column_key, value_index):
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
    value_index: ValueIndex | None = None,
    resolved_values: list[dict[str, Any]] | None = None,
    policy_overrides: dict[str, Any] | None = None,
) -> str:
    """Validate one read-only query locally against the complete schema catalog."""
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
    _validate_read_only_ast(parsed)

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

    validation_scopes = list(traverse_scope(parsed))
    validation_scope_by_expression = {
        id(scope.expression): scope for scope in validation_scopes
    }
    for column_node in parsed.find_all(exp.Column):
        if column_node.name == "*":
            continue
        scope = _scope_for_column(column_node, validation_scope_by_expression)
        if _is_select_alias_reference(column_node, scope):
            continue
        scoped_key = _scope_column_key(
            column_node,
            scope,
            metadata,
            validation_scope_by_expression,
            set(),
        )
        if scoped_key or _is_derived_column_reference(column_node, scope):
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

    schema = {
        name: {column.name: column.data_type for column in table.columns}
        for name, table in metadata.tables.items()
    }
    try:
        parsed = qualify(
            parsed,
            dialect=dialect,
            schema=schema,
            validate_qualify_columns=True,
            identify=False,
        )
    except sqlglot.errors.SqlglotError as error:
        raise ValidationError(f"Invalid table or column reference: {error}") from error

    validation_scopes = list(traverse_scope(parsed))
    validation_scope_by_expression = {
        id(scope.expression): scope for scope in validation_scopes
    }

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
                    if blocked_columns_for_table(table_key, cols, policy_overrides):
                        raise ValidationError(_BLOCKED_MSG)
        elif isinstance(parent, exp.Select):
            # SELECT * case - check all used tables
            for table_key in used_tables:
                table_obj = catalog.get(table_key)
                if table_obj:
                    cols = [c.name for c in table_obj.columns]
                    if blocked_columns_for_table(table_key, cols, policy_overrides):
                        raise ValidationError(_BLOCKED_MSG)

    # Check all column references (including in functions, subqueries, CTEs, etc.)
    for col_node in parsed.find_all(exp.Column):
        if col_node.name == "*":
            continue
        scope = _scope_for_column(col_node, validation_scope_by_expression)
        column_key = _scope_column_key(
            col_node,
            scope,
            metadata,
            validation_scope_by_expression,
            set(),
        )
        if column_key and (
            is_blocked(column_key, policy_overrides=policy_overrides)
            or is_masked(column_key, policy_overrides=policy_overrides)
        ):
            raise ValidationError(_BLOCKED_MSG)

    # Literal safety net: check string literals against value index
    rewritten_sql, errors = _check_and_rewrite_literals(
        parsed,
        table_aliases,
        catalog,
        value_index,
        resolved_values,
        dialect,
        used_tables=used_tables,
        policy_overrides=policy_overrides,
    )
    if errors:
        # Parse first error to extract structured info
        error_msg = errors[0]
        # Determine kind
        if "Ambiguous VALUE_HIGH" in error_msg:
            column_match = re.search(r"for (\S+)\.", error_msg)
            column = column_match.group(1) if column_match else None
            confirmation = getattr(value_index, "pending_confirmation", {})
            raise ValueSafetyError(
                "An ambiguous value needs user confirmation.",
                "ambiguous",
                "",
                column,
                [],
            )
        if "restricted column" in error_msg:
            raise ValidationError("That information isn't available.")
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
    return normalized