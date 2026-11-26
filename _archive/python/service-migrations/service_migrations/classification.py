"""Classify forward migrations as expand or contract without importing them.

A Hub-managed upgrade applies only expand revisions before workloads switch, because the previous
workloads must keep working against the new schema. A revision that drops or renames a table,
column, schema or type, or that changes a column type, is a contract revision. The Release declares
the class of every revision that is pending in an installation. Static analysis is a floor: it can
force a declared expand to be rejected, and it never promotes a declaration.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

CLASSIFICATION_SCHEMA: Final = "fdai.migration-classification.v1"
EXPAND: Final = "expand"
CONTRACT: Final = "contract"
_CLASSES: Final = frozenset({EXPAND, CONTRACT})
_REVISION_ID: Final = re.compile(r"[A-Za-z0-9_]{1,128}")

_DESTRUCTIVE_OPERATIONS: Final = frozenset({"drop_table", "drop_column", "rename_table"})
_ALTER_RENAMING_KEYWORDS: Final = frozenset({"new_column_name", "type_"})
_DESTRUCTIVE_SQL: Final = re.compile(
    r"\bDROP\s+(?:TABLE|COLUMN|SCHEMA|TYPE)\b"
    r"|\bALTER\s+(?:TABLE|TYPE|SCHEMA)\b[^;]*?\bRENAME\b"
    r"|\bALTER\s+COLUMN\b[^;]*?\bTYPE\b"
    r"|(?:\A|;)\s*TRUNCATE\b",
    re.IGNORECASE | re.DOTALL,
)


class MigrationClassificationError(Exception):
    """A stable reason code, never a path, revision body or database detail."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class RevisionAnalysis:
    revision: str
    destructive: tuple[str, ...]

    @property
    def computed_class(self) -> str:
        return CONTRACT if self.destructive else EXPAND


def analyze_revision(path: Path) -> RevisionAnalysis:
    """Return the destructive operations reachable from the revision's ``upgrade()``."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    constants = _module_constants(tree)
    if "upgrade" not in functions:
        raise MigrationClassificationError("migration_classification_invalid")
    revision = constants.get("revision")
    if not isinstance(revision, str) or not _REVISION_ID.fullmatch(revision):
        raise MigrationClassificationError("migration_classification_invalid")
    found: set[str] = set()
    visited: set[str] = set()
    pending = ["upgrade"]
    while pending:
        name = pending.pop()
        if name in visited or name not in functions:
            continue
        visited.add(name)
        for node in ast.walk(functions[name]):
            found.update(_destructive(node))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                pending.append(node.func.id)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                found.update(_sql_findings(constants.get(node.id)))
    return RevisionAnalysis(revision, tuple(sorted(found)))


def load_release_classification(raw: object) -> dict[str, str]:
    """Validate the Release's ``revision -> class`` declaration."""

    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"schema", "revisions"}
        or raw["schema"] != CLASSIFICATION_SCHEMA
        or not isinstance(raw["revisions"], Mapping)
    ):
        raise MigrationClassificationError("migration_classification_invalid")
    declared = raw["revisions"]
    if not all(
        isinstance(key, str) and _REVISION_ID.fullmatch(key) and value in _CLASSES
        for key, value in declared.items()
    ):
        raise MigrationClassificationError("migration_classification_invalid")
    return {str(key): str(value) for key, value in declared.items()}


def pending_revisions(image: Mapping[str, Path], applied: Iterable[str]) -> dict[str, Path]:
    """Revisions in the image that the installation has not applied yet."""

    done = set(applied)
    return {revision: path for revision, path in sorted(image.items()) if revision not in done}


def plan_expand(pending: Mapping[str, Path], declared: Mapping[str, str]) -> tuple[str, ...]:
    """Return the revisions the schema-expand Job may run, or reject the whole upgrade.

    Revisions applied before enrollment are outside ``pending`` and need no declaration. Every
    pending revision must be declared, a declared contract revision waits for a fenced Plan after
    the restore checkpoint, and a declared expand revision that analysis finds destructive is
    rejected rather than trusted.
    """

    for revision, path in pending.items():
        analysis = analyze_revision(path)
        if analysis.revision != revision:
            raise MigrationClassificationError("migration_classification_invalid")
        if revision not in declared:
            raise MigrationClassificationError("migration_unclassified")
        if declared[revision] == CONTRACT:
            raise MigrationClassificationError("migration_contract_revision")
        if analysis.destructive:
            raise MigrationClassificationError("migration_expand_destructive")
    return tuple(pending)


def _module_constants(tree: ast.Module) -> dict[str, object]:
    constants: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name):
            try:
                constants[target.id] = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                continue
    return constants


def _destructive(node: ast.AST) -> set[str]:
    findings: set[str] = set()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        operation = node.func.attr
        if operation in _DESTRUCTIVE_OPERATIONS:
            findings.add(operation)
        if operation == "alter_column" and any(
            keyword.arg in _ALTER_RENAMING_KEYWORDS for keyword in node.keywords
        ):
            findings.add("alter_column_rename_or_type")
    if isinstance(node, ast.Constant):
        findings.update(_sql_findings(node.value))
    return findings


def _sql_findings(value: object) -> set[str]:
    if isinstance(value, str):
        return {"sql_destructive"} if _DESTRUCTIVE_SQL.search(value) else set()
    if isinstance(value, (tuple, list, set, frozenset)):
        return set().union(*(_sql_findings(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_sql_findings(item) for item in value.values())) if value else set()
    return set()
