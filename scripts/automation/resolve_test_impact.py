#!/usr/bin/env python3
"""Resolve Python tests that directly or transitively consume changed modules."""

from __future__ import annotations

import argparse
import ast
import importlib.util
from collections import defaultdict, deque
from pathlib import Path


def _module_chain(module: str) -> set[str]:
    parts = module.split(".")
    return {".".join(parts[:index]) for index in range(1, len(parts) + 1)}


def _module_name(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[:2] == ["src", "fdai"]:
        parts = ["fdai", *parts[2:]]
    elif parts and parts[0] in {"delivery", "scripts", "tools"}:
        pass
    else:
        return None
    if not parts or not parts[-1].endswith(".py"):
        return None
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _python_files(root: Path, *directories: str) -> list[Path]:
    files: list[Path] = []
    for directory in directories:
        path = root / directory
        if path.exists():
            files.extend(
                candidate
                for candidate in path.rglob("*.py")
                if "__pycache__" not in candidate.parts
            )
    return sorted(files)


def _resolve_from(module: str, imported: str | None, level: int, *, is_package: bool) -> str | None:
    if level == 0:
        return imported
    package = module if is_package else module.rpartition(".")[0]
    if not package:
        return None
    target = "." * level + (imported or "")
    try:
        return importlib.util.resolve_name(target, package)
    except (ImportError, ValueError):
        return None


def _imports(path: Path, module: str, known_modules: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.update(_module_chain(alias.name))
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(
                module,
                node.module,
                node.level,
                is_package=path.name == "__init__.py",
            )
            if not base:
                continue
            imports.update(_module_chain(base))
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                if candidate in known_modules:
                    imports.update(_module_chain(candidate))
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            is_dynamic_import = (
                isinstance(function, ast.Name) and function.id == "__import__"
            ) or (isinstance(function, ast.Attribute) and function.attr == "import_module")
            if not is_dynamic_import:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                imports.update(_module_chain(argument.value))
            elif isinstance(argument, ast.JoinedStr) and argument.values:
                first = argument.values[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    prefix = first.value.rstrip(".")
                    imports.update(_module_chain(prefix))
                    imports.add(f"{prefix}.*")
    return imports


def _depends_on(dependencies: set[str], affected: set[str]) -> bool:
    for dependency in dependencies:
        if dependency.endswith(".*"):
            prefix = dependency[:-2]
            if any(module == prefix or module.startswith(f"{prefix}.") for module in affected):
                return True
        elif dependency in affected:
            return True
    return False


def resolve_tests(root: Path, changed_paths: list[Path]) -> list[Path]:
    source_files = _python_files(root, "src/fdai", "delivery", "scripts", "tools")
    test_files = _python_files(root, "tests")
    source_modules = {
        module: path for path in source_files if (module := _module_name(path, root)) is not None
    }
    changed_modules = {
        module for path in changed_paths if (module := _module_name(path, root)) is not None
    }
    if not changed_modules:
        return []

    known_modules = set(source_modules) | changed_modules
    reverse_imports: dict[str, set[str]] = defaultdict(set)
    wildcard_imports: list[tuple[str, str]] = []
    for module, path in source_modules.items():
        dependencies = _imports(path, module, known_modules)
        for dependency in dependencies:
            if dependency.endswith(".*"):
                wildcard_imports.append((dependency[:-2], module))
            else:
                reverse_imports[dependency].add(module)

    affected = set(changed_modules)
    for module in tuple(changed_modules):
        parent = module.rpartition(".")[0]
        if parent:
            affected.add(parent)
    queue = deque(affected)
    while queue:
        dependency = queue.popleft()
        importers = set(reverse_imports.get(dependency, ()))
        importers.update(
            importer
            for prefix, importer in wildcard_imports
            if dependency == prefix or dependency.startswith(f"{prefix}.")
        )
        for importer in importers:
            if importer not in affected:
                affected.add(importer)
                queue.append(importer)

    selected: list[Path] = []
    for path in test_files:
        module = "tests." + ".".join(path.relative_to(root / "tests").with_suffix("").parts)
        if _depends_on(_imports(path, module, known_modules), affected):
            selected.append(path.relative_to(root))
    return sorted(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    changed_paths = [path if path.is_absolute() else root / path for path in args.paths]
    for path in resolve_tests(root, changed_paths):
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
