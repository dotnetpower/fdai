"""Build the Core wheel from an explicit repository-source allowlist."""

from __future__ import annotations

import ast
from collections import deque
from importlib.util import resolve_name
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import (  # type: ignore[import-not-found]
    BuildHookInterface,
)

OWNED_PACKAGE_TREES = (
    "agents",
    "composition",
    "core",
    "rule_catalog",
    "shared",
)

OWNED_SOURCE_SUFFIXES = frozenset({".json", ".md", ".py", ".typed"})

CORE_RUNTIME_FILES = (
    "__init__.py",
    "bootstrap.py",
    "bootstrap_bindings.py",
    "bootstrap_lifecycle.py",
    "bootstrap_shutdown.py",
    "case_history.py",
    "catalog_ontology.py",
    "configuration.py",
    "consumers.py",
    "control_loop.py",
    "conversation_assurance.py",
    "conversation_assurance_lifecycle.py",
    "delivery.py",
    "dynamic_evidence.py",
    "forecast_learning.py",
    "health.py",
    "human_access.py",
    "human_assignment_reconciliation.py",
    "inventory_ontology.py",
    "isolated_executor_client.py",
    "operating_model.py",
    "post_turn_review.py",
    "providers.py",
    "readiness.py",
    "t2_recovery.py",
    "t2_route_registry.py",
)

ROOT_PACKAGE_FILES = ("__init__.py", "__main__.py", "py.typed")

SOURCE_REPLACEMENTS = {
    Path("delivery/github/__init__.py"): Path(
        "services/core-control-plane/assets/fdai/delivery/github/__init__.py"
    ),
}

ALLOWED_CLOSURE_ROOTS = frozenset(
    {
        *OWNED_PACKAGE_TREES,
        "delivery",
        "runtime",
    }
)

PROHIBITED_IMPLEMENTATION_PREFIXES = (
    Path("deployment_cli"),
    Path("delivery/ingestion_gateway"),
    Path("delivery/operator_api"),
)

PROHIBITED_RUNTIME_FILES = frozenset(
    {
        "evaluation_runner.py",
        "evaluation_runner_cli.py",
        "executor_authority_probe_cli.py",
        "isolated_executor.py",
        "isolated_executor_cli.py",
        "isolated_executor_lock.py",
        "isolated_executor_runtime.py",
    }
)


def _is_prohibited(relative_path: Path) -> bool:
    if relative_path.parts[:1] == ("runtime",):
        return relative_path.name in PROHIBITED_RUNTIME_FILES
    return any(
        relative_path == prefix or prefix in relative_path.parents
        for prefix in PROHIBITED_IMPLEMENTATION_PREFIXES
    )


def _module_file(source_root: Path, module: str) -> Path | None:
    if module == "fdai":
        return source_root / "__init__.py"
    if not module.startswith("fdai."):
        return None
    relative = Path(*module.split(".")[1:])
    module_file = source_root / relative.with_suffix(".py")
    if module_file.is_file():
        return module_file
    package_file = source_root / relative / "__init__.py"
    return package_file if package_file.is_file() else None


def _module_name(source_root: Path, source_file: Path) -> str:
    relative = source_file.relative_to(source_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("fdai", *parts))


def _imported_modules(
    source_root: Path,
    source_file: Path,
    *,
    parse_file: Path | None = None,
) -> set[str]:
    parsed_file = parse_file or source_file
    tree = ast.parse(parsed_file.read_text(encoding="utf-8"), filename=str(parsed_file))
    imported: set[str] = set()
    current_module = _module_name(source_root, source_file)
    current_package = (
        current_module if source_file.name == "__init__.py" else current_module.rpartition(".")[0]
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names if alias.name.startswith("fdai"))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            suffix = node.module or ""
            module = resolve_name(f"{'.' * node.level}{suffix}", current_package)
        else:
            module = node.module or ""
        if not module.startswith("fdai"):
            continue
        imported.add(module)
        for alias in node.names:
            if alias.name != "*":
                imported.add(f"{module}.{alias.name}")
    return imported


def _package_initializers(source_root: Path, source_file: Path) -> set[Path]:
    initializers: set[Path] = set()
    parent = source_file.parent
    while parent == source_root or source_root in parent.parents:
        initializer = parent / "__init__.py"
        if initializer.is_file():
            initializers.add(initializer)
        if parent == source_root:
            break
        parent = parent.parent
    return initializers


def _build_source_file(repo_root: Path, source_root: Path, source_file: Path) -> Path:
    replacement = SOURCE_REPLACEMENTS.get(source_file.relative_to(source_root))
    return repo_root / replacement if replacement is not None else source_file


def core_source_files(repo_root: Path) -> tuple[Path, ...]:
    """Return the deterministic Core payload and reject service implementations."""

    source_root = repo_root / "src" / "fdai"
    selected = {
        path
        for tree in OWNED_PACKAGE_TREES
        for path in (source_root / tree).rglob("*")
        if path.is_file() and path.suffix in OWNED_SOURCE_SUFFIXES
    }
    selected.update(source_root / name for name in ROOT_PACKAGE_FILES)
    selected.update(source_root / "runtime" / name for name in CORE_RUNTIME_FILES)

    missing = sorted(str(path) for path in selected if not path.is_file())
    if missing:
        raise RuntimeError(f"Core package allowlist contains missing source: {missing}")

    pending = deque(path for path in selected if path.suffix == ".py")
    parsed: set[Path] = set()
    while pending:
        source_file = pending.popleft()
        if source_file in parsed:
            continue
        parsed.add(source_file)
        for initializer in _package_initializers(source_root, source_file):
            if initializer not in selected:
                selected.add(initializer)
                pending.append(initializer)
        parse_file = _build_source_file(repo_root, source_root, source_file)
        if not parse_file.is_file():
            raise RuntimeError(f"Core package replacement source is missing: {parse_file}")
        for module in _imported_modules(source_root, source_file, parse_file=parse_file):
            imported_file = _module_file(source_root, module)
            if imported_file is None:
                continue
            relative = imported_file.relative_to(source_root)
            if relative.parts[0] not in ALLOWED_CLOSURE_ROOTS:
                raise RuntimeError(
                    f"Core package import closure reached unowned source {relative} "
                    f"from {source_file.relative_to(repo_root)}"
                )
            if _is_prohibited(relative):
                raise RuntimeError(
                    f"Core package import closure reached prohibited implementation {relative} "
                    f"from {source_file.relative_to(repo_root)}"
                )
            if imported_file not in selected:
                selected.add(imported_file)
                pending.append(imported_file)

    prohibited = sorted(
        str(path.relative_to(source_root))
        for path in selected
        if _is_prohibited(path.relative_to(source_root))
    )
    if prohibited:
        raise RuntimeError(f"Core package selected prohibited implementations: {prohibited}")
    return tuple(sorted(selected))


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    """Force-include the current Core-owned source closure in the service wheel."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name != "wheel":
            return
        repo_root = Path(self.root).resolve().parents[1]
        source_root = repo_root / "src" / "fdai"
        force_include = build_data.setdefault("force_include", {})
        if not isinstance(force_include, dict):
            raise RuntimeError("Hatch wheel force_include build data must be a mapping")
        for source_file in core_source_files(repo_root):
            destination = Path("fdai") / source_file.relative_to(source_root)
            build_source = _build_source_file(repo_root, source_root, source_file)
            force_include[str(build_source)] = destination.as_posix()
