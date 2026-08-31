#!/usr/bin/env python3
"""Validate complete decision-critical evidence admission coverage.

Every registered positive decision boundary must resolve its decision-critical
evidence through the shared admission contract and must fail closed when no
admission is available. The inventory in `config/decision-boundary-inventory.json`
is the declared complete list, and this check enforces coverage in both
directions: every registered boundary is really wired to the shared contract, and
every module that touches the shared contract or declares an evidence purpose is
really registered. An intentionally uncovered registered boundary fails here.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INVENTORY = Path("config/decision-boundary-inventory.json")
BOUNDARY_ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PURPOSE_CONSTANT_PATTERN = re.compile(r"^[A-Z0-9_]+_EVIDENCE_PURPOSE$")
REQUIRED_BOUNDARY_KEYS = frozenset(
    {"id", "positive_decision", "module", "purpose_constant", "purpose_id", "tests"}
)
REQUIRED_NEGATIVE_CLASSES = (
    "missing",
    "stale",
    "incomplete",
    "conflicting",
    "synthetic",
    "wrong-purpose",
    "wrong-scope",
)


class InventoryError(Exception):
    """The inventory document itself cannot be interpreted."""


@dataclass(frozen=True, slots=True)
class ModuleFacts:
    """Structural facts extracted from one module without importing it."""

    imports_assessor: bool
    calls_assessor: bool
    purpose_constants: Mapping[str, str | None]
    fails_closed_on_absent_admission: bool


def _load_inventory(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise InventoryError(f"inventory not found: {path}") from error
    except json.JSONDecodeError as error:
        raise InventoryError(f"inventory is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise InventoryError("inventory must be a JSON object")
    return document


def _module_facts(path: Path, assessor: str, admission_type: str) -> ModuleFacts:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports_assessor = False
    calls_assessor = False
    purpose_constants: dict[str, str | None] = {}
    fails_closed = False
    admission_hints = ("admission", "decision_evidence")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == assessor:
                    imports_assessor = True
        elif isinstance(node, ast.Call):
            function = node.func
            name = getattr(function, "id", None) or getattr(function, "attr", None)
            if name == assessor:
                calls_assessor = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not PURPOSE_CONSTANT_PATTERN.match(target.id):
                    continue
                value = node.value
                literal = value.value if isinstance(value, ast.Constant) else None
                purpose_constants[target.id] = literal if isinstance(literal, str) else None
        elif isinstance(node, ast.Compare):
            if not any(isinstance(operator, ast.Is | ast.IsNot) for operator in node.ops):
                continue
            if not any(
                isinstance(comparator, ast.Constant) and comparator.value is None
                for comparator in node.comparators
            ):
                continue
            left = ast.unparse(node.left).lower()
            if any(hint in left for hint in admission_hints):
                fails_closed = True
    del admission_type
    return ModuleFacts(
        imports_assessor=imports_assessor,
        calls_assessor=calls_assessor,
        purpose_constants=purpose_constants,
        fails_closed_on_absent_admission=fails_closed,
    )


def _iter_source_modules(root: Path, source_roots: Iterable[str]) -> Iterable[Path]:
    for relative in source_roots:
        base = root / relative
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _validate_schema(document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    shared = document.get("shared_admission")
    if not isinstance(shared, dict):
        raise InventoryError("inventory requires a 'shared_admission' object")
    for key in ("module", "assessor", "admission_type", "provider_protocol", "source"):
        if not isinstance(shared.get(key), str) or not shared[key]:
            raise InventoryError(f"inventory 'shared_admission.{key}' must be a non-empty string")
    boundaries = document.get("boundaries")
    if not isinstance(boundaries, list) or not boundaries:
        raise InventoryError("inventory requires a non-empty 'boundaries' array")
    identifiers: list[str] = []
    for index, boundary in enumerate(boundaries):
        label = f"boundaries[{index}]"
        if not isinstance(boundary, dict):
            raise InventoryError(f"{label} must be an object")
        missing = sorted(REQUIRED_BOUNDARY_KEYS - set(boundary))
        if missing:
            errors.append(f"{label}: missing required keys: {', '.join(missing)}")
            continue
        identifier = boundary["id"]
        if not isinstance(identifier, str) or not BOUNDARY_ID_PATTERN.match(identifier):
            errors.append(f"{label}: 'id' must be lowercase kebab-case")
            continue
        identifiers.append(identifier)
        tests = boundary["tests"]
        if not isinstance(tests, list) or not tests:
            errors.append(f"{identifier}: 'tests' must list at least one focused test file")
        constant = boundary["purpose_constant"]
        if constant is not None and not (
            isinstance(constant, str) and PURPOSE_CONSTANT_PATTERN.match(constant)
        ):
            errors.append(f"{identifier}: 'purpose_constant' must be null or a purpose constant")
        if (constant is None) != (boundary["purpose_id"] is None):
            errors.append(
                f"{identifier}: 'purpose_constant' and 'purpose_id' must both be set "
                "or both be null"
            )
        if constant is None and not boundary.get("purpose_note"):
            errors.append(
                f"{identifier}: a dynamic purpose requires a 'purpose_note' naming its source"
            )
    if len(set(identifiers)) != len(identifiers):
        errors.append("boundaries: 'id' values must be unique")
    if identifiers != sorted(identifiers):
        errors.append("boundaries: entries must be sorted by 'id'")
    return errors


def _validate_boundaries(
    *,
    root: Path,
    document: Mapping[str, Any],
    facts_by_module: dict[Path, ModuleFacts],
    assessor: str,
    admission_type: str,
) -> list[str]:
    errors: list[str] = []
    for boundary in document["boundaries"]:
        if not isinstance(boundary, dict) or "id" not in boundary:
            continue
        identifier = boundary["id"]
        module_ref = boundary.get("module")
        if not isinstance(module_ref, str):
            errors.append(f"{identifier}: 'module' must be a repository-relative path")
            continue
        module_path = root / module_ref
        if not module_path.is_file():
            errors.append(f"{identifier}: module does not exist: {module_ref}")
            continue
        facts = facts_by_module.get(module_path)
        if facts is None:
            facts = _module_facts(module_path, assessor, admission_type)
            facts_by_module[module_path] = facts
        if not facts.imports_assessor:
            errors.append(
                f"{identifier}: {module_ref} does not import the shared admission "
                f"assessor '{assessor}'"
            )
        if not facts.calls_assessor:
            errors.append(
                f"{identifier}: {module_ref} does not call the shared admission "
                f"assessor '{assessor}'"
            )
        if not facts.fails_closed_on_absent_admission:
            errors.append(f"{identifier}: {module_ref} does not fail closed on an absent admission")
        constant = boundary.get("purpose_constant")
        if isinstance(constant, str):
            if constant not in facts.purpose_constants:
                errors.append(f"{identifier}: {module_ref} does not define {constant}")
            elif facts.purpose_constants[constant] != boundary.get("purpose_id"):
                errors.append(
                    f"{identifier}: {constant} is {facts.purpose_constants[constant]!r} in "
                    f"{module_ref} but the inventory declares {boundary.get('purpose_id')!r}"
                )
        for test_ref in boundary.get("tests", []):
            if not isinstance(test_ref, str) or not (root / test_ref).is_file():
                errors.append(f"{identifier}: focused test does not exist: {test_ref}")
    return errors


def _validate_completeness(
    *,
    root: Path,
    document: Mapping[str, Any],
    facts_by_module: dict[Path, ModuleFacts],
    assessor: str,
    admission_type: str,
) -> list[str]:
    errors: list[str] = []
    shared_source = root / str(document["shared_admission"]["source"])
    registered_modules = {
        root / boundary["module"]
        for boundary in document["boundaries"]
        if isinstance(boundary, dict) and isinstance(boundary.get("module"), str)
    }
    declared_constants: dict[Path, set[str]] = {}
    for boundary in document["boundaries"]:
        if not isinstance(boundary, dict) or not isinstance(boundary.get("module"), str):
            continue
        constant = boundary.get("purpose_constant")
        if isinstance(constant, str):
            declared_constants.setdefault(root / boundary["module"], set()).add(constant)
    for declaration in document.get("purpose_declarations", []):
        if not isinstance(declaration, dict):
            errors.append("purpose_declarations: every entry must be an object")
            continue
        module_ref = declaration.get("module")
        constant = declaration.get("constant")
        if not isinstance(module_ref, str) or not isinstance(constant, str):
            errors.append("purpose_declarations: every entry needs 'module' and 'constant'")
            continue
        if not declaration.get("note"):
            errors.append(f"purpose_declarations: {constant} requires an explanatory 'note'")
        declared_constants.setdefault(root / module_ref, set()).add(constant)
    source_roots = document.get("source_roots")
    if not isinstance(source_roots, list) or not source_roots:
        raise InventoryError("inventory requires a non-empty 'source_roots' array")
    for module_path in _iter_source_modules(root, source_roots):
        if module_path == shared_source:
            continue
        facts = facts_by_module.get(module_path)
        if facts is None:
            facts = _module_facts(module_path, assessor, admission_type)
            facts_by_module[module_path] = facts
        relative = module_path.relative_to(root).as_posix()
        if facts.calls_assessor and module_path not in registered_modules:
            errors.append(
                f"{relative} resolves the shared admission but is not a registered boundary"
            )
        known = declared_constants.get(module_path, set())
        for constant in sorted(set(facts.purpose_constants) - known):
            errors.append(
                f"{relative} declares {constant} but the inventory registers neither a "
                "boundary nor a purpose declaration for it"
            )
    return errors


def _validate_negative_matrix(root: Path, document: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    matrix = document.get("negative_evidence_matrix")
    if not isinstance(matrix, dict):
        errors.append("inventory requires a 'negative_evidence_matrix' object")
        return errors
    classes = matrix.get("classes")
    if not isinstance(classes, list) or tuple(classes) != REQUIRED_NEGATIVE_CLASSES:
        errors.append(
            "negative_evidence_matrix.classes must be exactly: "
            + ", ".join(REQUIRED_NEGATIVE_CLASSES)
        )
    tests = matrix.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("negative_evidence_matrix.tests must list at least one focused test file")
        return errors
    for test_ref in tests:
        path = root / str(test_ref)
        if not path.is_file():
            errors.append(f"negative_evidence_matrix: test does not exist: {test_ref}")
            continue
        text = path.read_text(encoding="utf-8")
        for negative_class in REQUIRED_NEGATIVE_CLASSES:
            if negative_class not in text:
                errors.append(
                    f"negative_evidence_matrix: {test_ref} does not cover the "
                    f"'{negative_class}' evidence class"
                )
    return errors


def validate(*, root: Path, inventory_path: Path) -> list[str]:
    document = _load_inventory(inventory_path)
    errors = _validate_schema(document)
    shared = document["shared_admission"]
    assessor = str(shared["assessor"])
    admission_type = str(shared["admission_type"])
    shared_source = root / str(shared["source"])
    if not shared_source.is_file():
        errors.append(f"shared_admission.source does not exist: {shared['source']}")
        return errors
    shared_text = shared_source.read_text(encoding="utf-8")
    for symbol in (assessor, admission_type, str(shared["provider_protocol"])):
        if symbol not in shared_text:
            errors.append(f"shared_admission: {shared['source']} does not define {symbol}")
    facts_by_module: dict[Path, ModuleFacts] = {}
    errors.extend(
        _validate_boundaries(
            root=root,
            document=document,
            facts_by_module=facts_by_module,
            assessor=assessor,
            admission_type=admission_type,
        )
    )
    errors.extend(
        _validate_completeness(
            root=root,
            document=document,
            facts_by_module=facts_by_module,
            assessor=assessor,
            admission_type=admission_type,
        )
    )
    errors.extend(_validate_negative_matrix(root, document))
    return errors


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--inventory", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    root = arguments.root.resolve()
    inventory_path = arguments.inventory or (root / DEFAULT_INVENTORY)
    try:
        errors = validate(root=root, inventory_path=inventory_path)
    except InventoryError as error:
        print(f"decision-boundary-coverage: ERROR: {error}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"decision-boundary-coverage: ERROR: {error}", file=sys.stderr)
        return 1
    print("decision-boundary-coverage: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
