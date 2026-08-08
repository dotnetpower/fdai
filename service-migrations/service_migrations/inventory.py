"""Read the immutable legacy Alembic lineage without importing migration modules."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:(?:IF\s+NOT\s+EXISTS)\s+)?"
    r"(?:public\.)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)
_DDL_TABLE = re.compile(
    r"(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE|DROP\s+TABLE"
    r"|TRUNCATE(?:\s+TABLE)?|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"(?:public\.)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)
_TRIGGER_TABLE = re.compile(
    r"(?:CREATE|DROP)\s+TRIGGER\s+[a-zA-Z_][a-zA-Z0-9_]*\s+.*?\s+ON\s+"
    r"(?:public\.)?([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE | re.DOTALL,
)
_SQL_NON_TABLE_TOKENS = frozenset({"OF", "ON", "SET"})
_TABLE_ARG_BY_OPERATION = {
    "add_column": 0,
    "alter_column": 0,
    "create_check_constraint": 1,
    "create_foreign_key": 1,
    "create_index": 1,
    "create_primary_key": 1,
    "create_table": 0,
    "create_unique_constraint": 1,
    "drop_column": 0,
    "drop_constraint": 1,
    "drop_index": 1,
    "drop_table": 0,
}


@dataclass(frozen=True)
class LegacyInventory:
    """Normalized revisions and durable tables found in the legacy lineage."""

    down_revisions: dict[str, str | None]
    table_sources: dict[str, tuple[str, ...]]

    @property
    def heads(self) -> tuple[str, ...]:
        """Return revisions that are not the parent of another revision."""
        parents = {parent for parent in self.down_revisions.values() if parent is not None}
        return tuple(sorted(set(self.down_revisions) - parents))


@dataclass(frozen=True)
class RevisionMetadata:
    """Ownership and rollback declarations required on every forward revision."""

    revision: str
    owner: str
    owned_tables: tuple[str, ...]
    touched_tables: tuple[str, ...]
    created_tables: tuple[str, ...]
    rollback: dict[str, str]


def _assignment_value(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            if value is None:
                raise ValueError(f"migration assignment {name!r} has no value")
            return ast.literal_eval(value)
    raise ValueError(f"migration is missing {name!r}")


def _migration_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ValueError(f"migration is missing {name}()")


def _created_tables(upgrade: ast.FunctionDef) -> set[str]:
    tables: set[str] = set()
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tables.update(_CREATE_TABLE.findall(node.value))
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "op"
            and function.attr == "create_table"
        ):
            table_name = ast.literal_eval(node.args[0])
            if not isinstance(table_name, str):
                raise ValueError("op.create_table() name must be a string literal")
            tables.add(table_name)
    return tables


def _literal_table_argument(call: ast.Call, operation: str, index: int) -> str:
    if len(call.args) > index:
        value = ast.literal_eval(call.args[index])
    else:
        keyword = next(
            (item.value for item in call.keywords if item.arg == "table_name"),
            None,
        )
        if keyword is None:
            raise ValueError(f"op.{operation}() must name a literal table")
        value = ast.literal_eval(keyword)
    if not isinstance(value, str):
        raise ValueError(f"op.{operation}() table name must be a string literal")
    return value


def _sql_tables(statement: str) -> set[str]:
    tables = {
        table
        for table in _DDL_TABLE.findall(statement)
        if table.upper() not in _SQL_NON_TABLE_TOKENS
    }
    tables.update(_TRIGGER_TABLE.findall(statement))
    return tables


def _touched_tables(upgrade: ast.FunctionDef) -> set[str]:
    tables: set[str] = set()
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            tables.update(_sql_tables(node.value))
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "op":
            continue
        operation = node.func.attr
        if operation == "rename_table":
            tables.add(_literal_table_argument(node, operation, 0))
            tables.add(_literal_table_argument(node, operation, 1))
            continue
        if operation == "bulk_insert":
            raise ValueError("op.bulk_insert() cannot prove literal table ownership")
        if operation == "execute":
            if (
                not node.args
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
            ):
                raise ValueError("op.execute() SQL must be a string literal for ownership review")
            tables.update(_sql_tables(node.args[0].value))
            continue
        index = _TABLE_ARG_BY_OPERATION.get(operation)
        if index is not None:
            tables.add(_literal_table_argument(node, operation, index))
    return tables


def load_legacy_inventory(version_location: Path) -> LegacyInventory:
    """Parse one linear legacy Alembic version location into a stable inventory.

    Migration modules are never imported or executed. Invalid or non-linear metadata
    raises ``ValueError`` so callers cannot silently adopt an ambiguous baseline.
    """
    down_revisions: dict[str, str | None] = {}
    sources: defaultdict[str, list[str]] = defaultdict(list)
    paths = sorted(version_location.glob("*.py"))
    if not paths:
        raise ValueError(f"legacy version location is empty: {version_location}")

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _assignment_value(tree, "revision")
        down_revision = _assignment_value(tree, "down_revision")
        if not isinstance(revision, str):
            raise ValueError(f"{path.name}: revision must be a string")
        if down_revision is not None and not isinstance(down_revision, str):
            raise ValueError(f"{path.name}: tuple down_revision is not a linear lineage")
        if revision in down_revisions:
            raise ValueError(f"duplicate legacy revision: {revision}")
        down_revisions[revision] = down_revision
        for table_name in sorted(_created_tables(_migration_function(tree, "upgrade"))):
            sources[table_name].append(revision)

    missing_parents = {
        parent
        for parent in down_revisions.values()
        if parent is not None and parent not in down_revisions
    }
    if missing_parents:
        missing = ", ".join(sorted(missing_parents))
        raise ValueError(f"legacy lineage has missing parent revisions: {missing}")

    inventory = LegacyInventory(
        down_revisions=down_revisions,
        table_sources={table: tuple(revisions) for table, revisions in sorted(sources.items())},
    )
    if len(inventory.heads) != 1:
        raise ValueError(f"legacy lineage must have one head; found {inventory.heads}")
    return inventory


def load_revision_metadata(path: Path) -> RevisionMetadata:
    """Read required service revision metadata without importing the migration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    revision = _assignment_value(tree, "revision")
    owner = _assignment_value(tree, "migration_owner")
    owned_tables = _assignment_value(tree, "owned_tables")
    rollback = _assignment_value(tree, "rollback")
    if not isinstance(revision, str) or not isinstance(owner, str):
        raise ValueError(f"{path.name}: revision and migration_owner must be strings")
    if not isinstance(owned_tables, tuple) or not all(
        isinstance(table, str) for table in owned_tables
    ):
        raise ValueError(f"{path.name}: owned_tables must be a tuple of strings")
    if (
        not isinstance(rollback, dict)
        or not rollback
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in rollback.items()
        )
    ):
        raise ValueError(f"{path.name}: non-empty string rollback metadata is required")
    upgrade = _migration_function(tree, "upgrade")
    downgrade = _migration_function(tree, "downgrade")
    touched_tables = tuple(sorted(_touched_tables(upgrade) | _touched_tables(downgrade)))
    created_tables = tuple(sorted(_created_tables(upgrade)))
    undeclared = set(touched_tables) - set(owned_tables)
    if undeclared:
        raise ValueError(f"{path.name}: migration touches unowned tables {sorted(undeclared)}")
    return RevisionMetadata(
        revision=revision,
        owner=owner,
        owned_tables=owned_tables,
        touched_tables=touched_tables,
        created_tables=created_tables,
        rollback=cast(dict[str, str], rollback),
    )
