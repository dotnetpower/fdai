#!/usr/bin/env python3
"""Keep venue selection and runtime scope receipts inside one contract.

FDAI-CONST-001 allows a venue to differ only in credentials, endpoints, scale, and provider
scope. That is provable only while every venue-selected binding is enumerated in one place.
Before `fdai_service_contracts/venue.py` existed, each service read `FDAI_EXECUTION_VENUE`
with its own default and compared its own literals, so a new venue-sensitive capability could
appear anywhere and no check would fail.

This gate parses Python syntax and resolves bounded compile-time string aliases. It fails when
the environment variable is read or a venue literal is compared outside the declared contract,
including values assembled by string concatenation. It also discovers every independently
packaged service entry point from its ``ServiceDescriptor`` and requires exactly one structured
runtime-scope receipt before startup. The receipt records product and venue configuration only;
it grants no authority and makes no external-state claim.

Exit codes: 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Every source tree that composes an FDAI process, mapped to the one module allowed to
#: resolve the venue inside it, or ``None`` when the tree has no exempt module and must read
#: the shared contract. A service absent from this mapping is unscanned, so a new service
#: must be added here when it is created.
SCANNED_TREES: dict[Path, Path | None] = {
    ROOT / "packages/service-contracts/src/fdai_service_contracts": (
        ROOT / "packages/service-contracts/src/fdai_service_contracts/venue.py"
    ),
    ROOT / "services/core-control-plane/src/fdai": (
        ROOT / "services/core-control-plane/src/fdai/runtime/venue.py"
    ),
    ROOT / "services/core-control-plane/src/fdai_core_service": None,
    ROOT / "services/operator-service/src/fdai_operator_service": None,
    ROOT / "services/document-ingestion-api/src/fdai_ingestion_api_service": None,
    ROOT / "services/document-processing-worker/src/fdai_document_worker_service": None,
    ROOT / "services/isolated-executor/src/fdai_executor_service": None,
    ROOT / "services/system-knowledge-service/src/fdai_system_knowledge_service": None,
}

_EXECUTION_VENUE_ENV = "FDAI_EXECUTION_VENUE"
_VENUE_VALUES = frozenset({"local", "deployed"})
_RECEIPT_CALL = "record_runtime_scope_receipt"


def _display(path: Path) -> str:
    """Return a repo-relative path when possible, so findings stay readable."""

    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _violations(source_root: Path, contract: Path | None) -> list[str]:
    findings: list[str] = []
    contract_hint = (
        _display(contract) if contract is not None else "fdai_service_contracts/venue.py"
    )
    for path in sorted(source_root.rglob("*.py")):
        if path == contract or "__pycache__" in path.parts:
            continue
        findings.extend(_module_violations(path, contract_hint))
    return findings


def _module_violations(path: Path, contract_hint: str) -> list[str]:
    """Return semantic venue-selection violations in one Python module."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return [f"{_display(path)}: cannot parse Python source: {exc}"]

    constants = _constant_aliases(tree)
    venue_names = _venue_aliases(tree)
    findings: list[str] = []
    seen: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environment_container(node.value):
            if _constant_string(node.slice, constants) == _EXECUTION_VENUE_ENV:
                _append_finding(
                    findings,
                    seen,
                    path,
                    node.lineno,
                    "reads FDAI_EXECUTION_VENUE directly; "
                    f"use resolve_execution_venue() from {contract_hint}",
                )
        elif isinstance(node, ast.Call):
            key = _environment_read_key(node, constants)
            if key == _EXECUTION_VENUE_ENV:
                _append_finding(
                    findings,
                    seen,
                    path,
                    node.lineno,
                    "reads FDAI_EXECUTION_VENUE directly; "
                    f"use resolve_execution_venue() from {contract_hint}",
                )
        elif isinstance(node, ast.Compare):
            operands = (node.left, *node.comparators)
            if any(_constant_string(item, constants) in _VENUE_VALUES for item in operands) and any(
                _is_venue_expression(item, venue_names) for item in operands
            ):
                _append_finding(
                    findings,
                    seen,
                    path,
                    node.lineno,
                    "compares a venue literal; use ExecutionVenue and select_capability() instead",
                )
    return findings


def _constant_aliases(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            value = node.value
            if value is None:
                continue
            resolved = _constant_string(value, constants)
            if resolved is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and constants.get(target.id) != resolved:
                    constants[target.id] = resolved
                    changed = True
        if not changed:
            break
    return constants


def _venue_aliases(tree: ast.AST) -> set[str]:
    names = {"execution_venue"}
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    for _ in range(len(assignments) + 1):
        changed = False
        for node in assignments:
            value = node.value
            if value is None or not _is_venue_expression(value, names):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
        if not changed:
            break
    return names


def _constant_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left, constants)
        right = _constant_string(node.right, constants)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = _constant_string(value.value, constants)
                if resolved is None:
                    return None
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    return None


def _is_environment_container(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "environ") or (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _environment_read_key(node: ast.Call, constants: dict[str, str]) -> str | None:
    if not node.args:
        return None
    function = node.func
    if isinstance(function, ast.Name) and function.id == "getenv":
        return _constant_string(node.args[0], constants)
    if isinstance(function, ast.Attribute):
        if function.attr == "getenv" and isinstance(function.value, ast.Name):
            if function.value.id == "os":
                return _constant_string(node.args[0], constants)
        if function.attr == "get" and _is_environment_container(function.value):
            return _constant_string(node.args[0], constants)
    return None


def _is_venue_expression(node: ast.AST, venue_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in venue_names
    if isinstance(node, ast.Attribute):
        return node.attr == "execution_venue"
    if isinstance(node, ast.Call):
        function = node.func
        return (isinstance(function, ast.Name) and "venue" in function.id.lower()) or (
            isinstance(function, ast.Attribute) and "venue" in function.attr.lower()
        )
    return False


def _append_finding(
    findings: list[str],
    seen: set[tuple[int, str]],
    path: Path,
    line: int,
    message: str,
) -> None:
    identity = (line, message)
    if identity in seen:
        return
    seen.add(identity)
    findings.append(f"{_display(path)}:{line}: {message}")


def _entrypoint_violations(root: Path = ROOT) -> list[str]:
    """Require one startup receipt in every service-owned executable entry point."""

    services = root / "services"
    findings: list[str] = []
    entrypoint_count = 0
    for path in sorted(services.glob("*/src/**/*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not any(_is_service_descriptor_assignment(node) for node in tree.body):
            continue
        entrypoint_count += 1
        main = next(
            (
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
            ),
            None,
        )
        if main is None:
            findings.append(f"{_display(path)}: ServiceDescriptor entry point has no main()")
            continue
        receipt_calls = [
            node
            for node in ast.walk(main)
            if isinstance(node, ast.Call) and _call_name(node.func) == _RECEIPT_CALL
        ]
        if len(receipt_calls) != 1:
            findings.append(
                f"{_display(path)}: main() MUST record exactly one runtime scope receipt; "
                f"found {len(receipt_calls)}"
            )
    if entrypoint_count == 0:
        findings.append("services: no ServiceDescriptor entry points were discovered")
    return findings


def _is_service_descriptor_assignment(node: ast.stmt) -> bool:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
        return False
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return (
        any(isinstance(target, ast.Name) and target.id == "SERVICE" for target in targets)
        and isinstance(node.value, ast.Call)
        and _call_name(node.value.func) == "ServiceDescriptor"
    )


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Scan one directory instead of every declared source tree.",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="The one module allowed to resolve the venue in --source-root.",
    )
    args = parser.parse_args(argv)

    if args.source_root is not None:
        trees = {args.source_root.resolve(): args.contract.resolve() if args.contract else None}
    else:
        trees = {root: contract for root, contract in SCANNED_TREES.items()}

    findings: list[str] = []
    for root, contract in trees.items():
        if not root.is_dir():
            print(f"venue-capability-contract: FAILED - missing source tree {_display(root)}")
            return 1
        if contract is not None and not contract.exists():
            print(
                f"venue-capability-contract: FAILED - missing contract module {_display(contract)}"
            )
            return 1
        findings.extend(_violations(root, contract))
    if args.source_root is None:
        findings.extend(_entrypoint_violations())

    if findings:
        for finding in findings:
            print(f"venue-capability-contract: {finding}")
        print(f"venue-capability-contract: FAILED with {len(findings)} violation(s).")
        return 1
    print(f"venue-capability-contract: OK across {len(trees)} source tree(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
