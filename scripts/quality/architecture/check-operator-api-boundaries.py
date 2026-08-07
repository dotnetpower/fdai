#!/usr/bin/env python3
"""Enforce cleaned Operator API dependency directions and report known debt.

The gate parses imports without importing application code. Cleaned reverse
dependencies fail immediately, while route-policy and opposite-direction
service debt remain visible reports. Reviewed composition roots may exceed the
fanout limit only through a justified, exact-path allowlist whose stale entries
also fail the gate.
"""

from __future__ import annotations

import argparse
import ast
import os
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_SCAN_ROOTS = (
    "src/fdai/core",
    "src/fdai/runtime",
    "src/fdai/delivery/auth",
    "src/fdai/delivery/agent_activity.py",
    "src/fdai/delivery/agent_activity",
    "src/fdai/delivery/ingestion_gateway",
    "src/fdai/delivery/operator_api",
)
_COMPOSITION_ROOTS = (
    "src/fdai/delivery/operator_api/production/factory.py",
    "src/fdai/delivery/operator_api/dev/factory.py",
    "src/fdai/runtime/bootstrap.py",
)
_DEFAULT_ALLOWLIST = "scripts/quality/architecture/.check-operator-api-boundaries.allowlist"
_DEFAULT_DEBT_BUDGET = "scripts/quality/architecture/.check-operator-api-boundaries.debt"


@dataclass(frozen=True, slots=True)
class ImportRef:
    """One absolute import observed in a Python source file."""

    path: str
    line: int
    module: str
    fanout_module: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One enforceable or report-only dependency finding."""

    rule: str
    ref: ImportRef
    message: str


@dataclass(frozen=True, slots=True)
class AllowEntry:
    """One justified exact-path exception for a named rule."""

    rule: str
    path: str
    maximum: int
    justification: str


@dataclass(frozen=True, slots=True)
class DebtBudget:
    """Reviewed aggregate ceiling for one report-only debt rule."""

    rule: str
    maximum: int
    justification: str


class AllowlistError(ValueError):
    """The reviewed exception file is malformed or ambiguous."""


class ScanError(ValueError):
    """The requested repository scan scope is missing or unsafe."""


def main() -> int:
    """Scan selected paths and return nonzero for enforced or stale findings."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Repository-relative file or directory to scan; repeat as needed.",
    )
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--debt-budget", type=Path)
    parser.add_argument("--fanout-limit", type=int, default=40)
    parser.add_argument("--report-limit", type=int, default=10)
    args = parser.parse_args()
    if args.fanout_limit < 1 or args.report_limit < 0:
        parser.error("--fanout-limit must be positive and --report-limit non-negative")

    root = args.root.resolve()
    try:
        if not root.is_dir():
            raise ScanError(f"repository root is not a directory: {root}")
        selectors = tuple(_normalize_relative(value) for value in args.path)
        allowlist_path = _config_path(root, args.allowlist, _DEFAULT_ALLOWLIST)
        debt_budget_path = _config_path(root, args.debt_budget, _DEFAULT_DEBT_BUDGET)
        entries = _load_allowlist(allowlist_path)
        budgets = _load_debt_budgets(debt_budget_path)
        enforced, reported, parse_errors, imports = _scan_imports(root, selectors)
    except (AllowlistError, ScanError) as exc:
        print(f"check-operator-api-boundaries: invalid configuration or scope: {exc}")
        return 2

    used_entries: set[tuple[str, str]] = set()
    fanout_errors, fanout_metrics = _measure_fanout(
        root=root,
        selectors=selectors,
        imports=imports,
        limit=args.fanout_limit,
        entries=entries,
        used_entries=used_entries,
    )
    debt_errors = _check_debt_budgets(reported, budgets)
    stale = tuple(
        entry
        for entry in entries
        if _selected(entry.path, selectors) and (entry.rule, entry.path) not in used_entries
    )

    for path, line, message in parse_errors:
        print(f"{path}:{line}: [python-parse] {message}")
    for finding in (*enforced, *fanout_errors, *debt_errors):
        print(
            f"{finding.ref.path}:{finding.ref.line}: "
            f"[{finding.rule}] {finding.message}: {finding.ref.module}"
        )
    _print_reports(reported, args.report_limit)
    for path, count, allowlisted in fanout_metrics:
        status = "reviewed" if allowlisted else "within-limit"
        print(f"fanout {path}: {count} unique fdai imports ({status})")
    for entry in stale:
        print(f"stale allowlist entry [{entry.rule}] {entry.path}")

    failure_count = (
        len(parse_errors) + len(enforced) + len(fanout_errors) + len(debt_errors) + len(stale)
    )
    if failure_count:
        print(f"check-operator-api-boundaries: FAILED ({failure_count} finding(s))")
        return 1
    print(
        "check-operator-api-boundaries: OK "
        f"(reported={len(reported)} fanout_roots={len(fanout_metrics)})"
    )
    return 0


def _scan_imports(
    root: Path,
    selectors: tuple[str, ...],
) -> tuple[
    tuple[Finding, ...],
    tuple[Finding, ...],
    tuple[tuple[str, int, str], ...],
    dict[str, tuple[ImportRef, ...]],
]:
    enforced: list[Finding] = []
    reported: list[Finding] = []
    parse_errors: list[tuple[str, int, str]] = []
    imports: dict[str, tuple[ImportRef, ...]] = {}
    for path in _source_files(root, selectors):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            line = exc.lineno if isinstance(exc, SyntaxError) else 1
            parse_errors.append((relative, line or 1, "Python source cannot be parsed"))
            continue
        refs = tuple(_imports(tree, relative, root))
        imports[relative] = refs
        seen: set[tuple[str, str, int, str]] = set()
        for ref in refs:
            finding = _classify(ref)
            if finding is None:
                continue
            key = (finding.rule, ref.path, ref.line, ref.fanout_module)
            if key in seen:
                continue
            seen.add(key)
            target = reported if finding.rule.startswith("report-") else enforced
            target.append(finding)

    def finding_key(item: Finding) -> tuple[str, int, str, str]:
        return (item.ref.path, item.ref.line, item.rule, item.ref.module)

    return (
        tuple(sorted(enforced, key=finding_key)),
        tuple(sorted(reported, key=finding_key)),
        tuple(sorted(parse_errors)),
        imports,
    )


def _classify(ref: ImportRef) -> Finding | None:
    path = ref.path
    module = ref.module
    if module == "<dynamic-import>":
        return Finding(
            "dynamic-import-unresolved",
            ref,
            "dynamic import targets must be static string literals for dependency review",
        )
    if path.startswith("src/fdai/core/") and _module_is(module, "fdai.delivery"):
        return Finding(
            "core-to-delivery",
            ref,
            "core must depend on provider contracts, not delivery implementations",
        )
    if path.startswith("src/fdai/runtime/") and _module_is(module, "fdai.delivery.operator_api"):
        return Finding(
            "runtime-to-operator-api",
            ref,
            "runtime must not import Operator API implementations",
        )
    if path.startswith("src/fdai/delivery/ingestion_gateway/") and _module_is(
        module, "fdai.delivery.operator_api"
    ):
        return Finding(
            "ingestion-to-operator-api",
            ref,
            "ingestion must not import Operator API implementations",
        )
    if _is_neutral_delivery(path) and module.startswith(
        ("fdai.delivery.operator_api", "fdai.delivery.ingestion_gateway", "fdai.runtime")
    ):
        return Finding(
            "shared-delivery-to-application",
            ref,
            "shared delivery contracts must remain application-neutral",
        )
    if path.startswith("src/fdai/delivery/operator_api/application/") and _module_is(
        module, "fdai.delivery.operator_api.adapters"
    ):
        return Finding(
            "operator-application-to-adapter",
            ref,
            "Operator application code must depend on contracts, not provider adapters",
        )
    if path.startswith("src/fdai/delivery/operator_api/routes/") and _module_is(
        module, "fdai.delivery.operator_api.adapters"
    ):
        return Finding(
            "operator-route-to-adapter",
            ref,
            "Operator routes must depend on application contracts, not provider adapters",
        )
    if path.startswith("src/fdai/delivery/operator_api/routes/") and _module_is(
        module, "fdai.core"
    ):
        return Finding(
            "report-route-core-policy",
            ref,
            "route namespace still imports core policy or application implementations",
        )
    if path.startswith("src/fdai/delivery/operator_api/") and _module_is(module, "fdai.runtime"):
        return Finding(
            "report-operator-to-runtime",
            ref,
            "Operator API still imports runtime implementation modules",
        )
    if path.startswith("src/fdai/delivery/operator_api/") and _module_is(
        module, "fdai.delivery.ingestion_gateway"
    ):
        return Finding(
            "report-operator-to-ingestion",
            ref,
            "Operator API still imports ingestion implementation modules",
        )
    return None


def _measure_fanout(
    *,
    root: Path,
    selectors: tuple[str, ...],
    imports: dict[str, tuple[ImportRef, ...]],
    limit: int,
    entries: tuple[AllowEntry, ...],
    used_entries: set[tuple[str, str]],
) -> tuple[tuple[Finding, ...], tuple[tuple[str, int, bool], ...]]:
    entry_map = {(entry.rule, entry.path): entry for entry in entries}
    errors: list[Finding] = []
    metrics: list[tuple[str, int, bool]] = []
    for relative in _COMPOSITION_ROOTS:
        if not _selected(relative, selectors) or not (root / relative).is_file():
            continue
        modules = {
            ref.fanout_module
            for ref in imports.get(relative, ())
            if ref.fanout_module.startswith("fdai")
        }
        count = len(modules)
        key = ("composition-fanout", relative)
        entry = entry_map.get(key)
        allowlisted = count >= limit and entry is not None and count <= entry.maximum
        if allowlisted and entry is not None:
            used_entries.add(key)
        elif count >= limit and entry is not None and count > entry.maximum:
            errors.append(
                Finding(
                    "composition-fanout",
                    ImportRef(
                        relative,
                        1,
                        f"{count} unique fdai imports",
                        f"{count} unique fdai imports",
                    ),
                    f"composition root exceeds its reviewed ceiling {entry.maximum}",
                )
            )
        elif count >= limit:
            errors.append(
                Finding(
                    "composition-fanout",
                    ImportRef(
                        relative,
                        1,
                        f"{count} unique fdai imports",
                        f"{count} unique fdai imports",
                    ),
                    f"composition root is at or above the reviewed fanout limit {limit}",
                )
            )
        metrics.append((relative, count, allowlisted))
    return tuple(errors), tuple(metrics)


def _load_allowlist(path: Path) -> tuple[AllowEntry, ...]:
    if not path.exists():
        return ()
    entries: list[AllowEntry] = []
    justification: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            justification.clear()
            continue
        if stripped.startswith("#"):
            justification.append(stripped.removeprefix("#").strip())
            continue
        parts = stripped.split("|")
        if len(parts) != 3 or not all(parts):
            raise AllowlistError(f"{path}:{line_number}: expected rule|path|maximum")
        rule, relative, maximum_raw = parts
        if rule != "composition-fanout":
            raise AllowlistError(f"{path}:{line_number}: unsupported rule {rule!r}")
        if not justification:
            raise AllowlistError(
                f"{path}:{line_number}: entry requires a preceding justification comment"
            )
        try:
            maximum = int(maximum_raw)
        except ValueError as exc:
            raise AllowlistError(f"{path}:{line_number}: maximum must be an integer") from exc
        if maximum < 1:
            raise AllowlistError(f"{path}:{line_number}: maximum must be positive")
        entries.append(
            AllowEntry(
                rule,
                _normalize_relative(relative),
                maximum,
                " ".join(justification),
            )
        )
        justification.clear()
    keys = [(entry.rule, entry.path) for entry in entries]
    if len(keys) != len(set(keys)):
        raise AllowlistError(f"{path}: duplicate entries are not allowed")
    return tuple(entries)


def _source_files(root: Path, selectors: tuple[str, ...]) -> tuple[Path, ...]:
    candidates = selectors or _DEFAULT_SCAN_ROOTS
    files: set[Path] = set()
    for relative in candidates:
        target = root / relative
        if selectors and not target.exists():
            raise ScanError(f"selected path does not exist: {relative}")
        if target.is_symlink():
            raise ScanError(f"source selector must not be a symlink: {relative}")
        if target.exists() and not target.resolve().is_relative_to(root):
            raise ScanError(f"selected path escapes repository root: {relative}")
        if target.is_file() and target.suffix == ".py":
            files.add(target)
        elif target.is_dir():
            before = len(files)
            files.update(_walk_python_files(target, root))
            if selectors and len(files) == before:
                raise ScanError(f"selected path contains no Python source: {relative}")
        elif selectors:
            raise ScanError(f"selected path is not a Python file or directory: {relative}")
    return tuple(sorted(files))


def _imports(tree: ast.AST, path: str, root: Path) -> Iterator[ImportRef]:
    importlib_aliases = {"importlib"}
    import_module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importlib_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "importlib"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield ImportRef(path, node.lineno, alias.name, alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(path, node)
            if not module:
                continue
            if any(alias.name == "*" for alias in node.names):
                yield ImportRef(path, node.lineno, module, module)
            for alias in node.names:
                if alias.name != "*":
                    candidate = f"{module}.{alias.name}"
                    fanout_module = candidate if _module_exists(root, candidate) else module
                    yield ImportRef(path, node.lineno, candidate, fanout_module)
        elif isinstance(node, ast.Call) and _is_dynamic_import_call(
            node, importlib_aliases, import_module_aliases
        ):
            target = node.args[0] if node.args else None
            module = _dynamic_import_target(node, target)
            yield ImportRef(path, node.lineno, module, module)


def _walk_python_files(target: Path, root: Path) -> Iterator[Path]:
    for directory, directories, filenames in os.walk(target, followlinks=False):
        current = Path(directory)
        for name in tuple(directories):
            child = current / name
            if child.is_symlink():
                raise ScanError(
                    f"source tree must not contain directory symlink: "
                    f"{child.relative_to(root).as_posix()}"
                )
        for name in filenames:
            child = current / name
            if child.is_symlink():
                raise ScanError(
                    f"source tree must not contain file symlink: "
                    f"{child.relative_to(root).as_posix()}"
                )
            if child.suffix == ".py" and not any(
                part.startswith(".") or part == "__pycache__" for part in child.parts
            ):
                if not child.resolve().is_relative_to(root):
                    raise ScanError(
                        f"source file escapes repository root: {child.relative_to(root).as_posix()}"
                    )
                yield child


def _resolve_import_from(path: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = list(Path(path).with_suffix("").parts)
    try:
        fdai_index = parts.index("fdai")
    except ValueError:
        return ""
    module_parts = parts[fdai_index:]
    module_parts.pop()
    keep = len(module_parts) - node.level + 1
    if keep < 0:
        return ""
    resolved = module_parts[:keep]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _is_dynamic_import_call(
    node: ast.Call,
    importlib_aliases: set[str],
    import_module_aliases: set[str],
) -> bool:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id == "__import__" or function.id in import_module_aliases
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "import_module"
        and isinstance(function.value, ast.Name)
        and function.value.id in importlib_aliases
    )


def _dynamic_import_target(node: ast.Call, target: ast.expr | None) -> str:
    if not isinstance(target, ast.Constant) or not isinstance(target.value, str):
        return "<dynamic-import>"
    module = target.value
    if module.startswith("."):
        return "<dynamic-import>"
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        level = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "level"),
            node.args[4] if len(node.args) > 4 else None,
        )
        if level is not None and (not isinstance(level, ast.Constant) or level.value != 0):
            return "<dynamic-import>"
    return module


def _module_exists(root: Path, module: str) -> bool:
    relative = Path("src", *module.split("."))
    return (root / relative).with_suffix(".py").is_file() or (
        root / relative / "__init__.py"
    ).is_file()


def _load_debt_budgets(path: Path) -> tuple[DebtBudget, ...]:
    if not path.exists():
        return ()
    budgets: list[DebtBudget] = []
    justification: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            justification.clear()
            continue
        if stripped.startswith("#"):
            justification.append(stripped.removeprefix("#").strip())
            continue
        parts = stripped.split("|")
        if len(parts) != 2 or not all(parts):
            raise AllowlistError(f"{path}:{line_number}: expected rule|maximum")
        rule, maximum_raw = parts
        if not rule.startswith("report-") or not justification:
            raise AllowlistError(
                f"{path}:{line_number}: report budget requires a rule and justification"
            )
        try:
            maximum = int(maximum_raw)
        except ValueError as exc:
            raise AllowlistError(f"{path}:{line_number}: maximum must be an integer") from exc
        if maximum < 0:
            raise AllowlistError(f"{path}:{line_number}: maximum must be non-negative")
        budgets.append(DebtBudget(rule, maximum, " ".join(justification)))
        justification.clear()
    rules = [budget.rule for budget in budgets]
    if len(rules) != len(set(rules)):
        raise AllowlistError(f"{path}: duplicate report budgets are not allowed")
    return tuple(budgets)


def _check_debt_budgets(
    findings: tuple[Finding, ...],
    budgets: tuple[DebtBudget, ...],
) -> tuple[Finding, ...]:
    counts: dict[str, int] = defaultdict(int)
    first_ref: dict[str, ImportRef] = {}
    for finding in findings:
        counts[finding.rule] += 1
        first_ref.setdefault(finding.rule, finding.ref)
    errors: list[Finding] = []
    for budget in budgets:
        count = counts.get(budget.rule, 0)
        if count <= budget.maximum:
            continue
        ref = first_ref[budget.rule]
        errors.append(
            Finding(
                "report-debt-growth",
                ref,
                f"{budget.rule} grew to {count} above reviewed budget {budget.maximum}",
            )
        )
    unbudgeted = sorted(set(counts) - {budget.rule for budget in budgets})
    if unbudgeted:
        rule = unbudgeted[0]
        errors.append(
            Finding(
                "report-debt-unbudgeted",
                first_ref[rule],
                f"report-only debt rule has no reviewed budget: {rule}",
            )
        )
    return tuple(errors)


def _print_reports(findings: tuple[Finding, ...], limit: int) -> None:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.rule].append(finding)
    for rule, items in sorted(grouped.items()):
        paths = {item.ref.path for item in items}
        print(f"report [{rule}]: {len(items)} import(s) across {len(paths)} file(s)")
        for finding in items[:limit]:
            print(f"  {finding.ref.path}:{finding.ref.line}: {finding.ref.module}")
        if len(items) > limit:
            print(f"  ... {len(items) - limit} more")


def _is_neutral_delivery(path: str) -> bool:
    return (
        path.startswith("src/fdai/delivery/auth/")
        or path.startswith("src/fdai/delivery/agent_activity/")
        or path == "src/fdai/delivery/agent_activity.py"
    )


def _module_is(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _selected(path: str, selectors: tuple[str, ...]) -> bool:
    if not selectors:
        return True
    return any(
        path == selector
        or path.startswith(f"{selector.rstrip('/')}/")
        or selector.startswith(f"{path.rstrip('/')}/")
        for selector in selectors
    )


def _normalize_relative(value: str) -> str:
    candidate = Path(value)
    normalized = candidate.as_posix().removeprefix("./").rstrip("/")
    if candidate.is_absolute() or ".." in candidate.parts or not normalized or normalized == ".":
        raise AllowlistError(f"repository-relative path required: {value!r}")
    return normalized


def _config_path(root: Path, configured: Path | None, default: str) -> Path:
    path = configured or root / default
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ScanError(f"configuration path escapes repository root: {path}")
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
