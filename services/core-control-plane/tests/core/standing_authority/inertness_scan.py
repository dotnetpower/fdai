"""Whole-tree inertness scanner shared by the A3-E static import guards.

A hardcoded authority-root list is unsound: it silently misses shipped directories
(``core/decision_case``, ``core/execution_authorization``, ``shared/providers``, and
others) and a future adapter placed in one of them would keep the suite green. This
helper instead scans **every** shipped module under ``src/fdai`` except the
``standing_authority`` package itself, and resolves absolute imports, relative imports,
package re-export symbol imports, and dynamic ``importlib.import_module`` /
``__import__`` string literals.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PACKAGE_PREFIX = "fdai.core.standing_authority"
_OWNING_PACKAGE_PARTS = ("core", "standing_authority")


@dataclass(frozen=True, slots=True)
class ImportReference:
    """One import reference resolved to a fully qualified module or symbol path."""

    path: Path
    reference: str


def shipped_modules(source_root: Path, *, include_owning_package: bool = False) -> Iterator[Path]:
    """Yield shipped modules, by default excluding the standing-authority package."""

    owning = source_root.joinpath(*_OWNING_PACKAGE_PARTS)
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if not include_owning_package and path.is_relative_to(owning):
            continue
        yield path


def module_name(path: Path, source_root: Path) -> str:
    """Return the dotted module name for one shipped file."""

    parts = list(path.relative_to(source_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(["fdai", *parts])


def _package_name(path: Path, source_root: Path) -> str:
    name = module_name(path, source_root)
    if path.name == "__init__.py":
        return name
    return name.rsplit(".", 1)[0] if "." in name else name


def _resolve_relative(path: Path, source_root: Path, node: ast.ImportFrom) -> str | None:
    base = _package_name(path, source_root).split(".")
    drop = node.level - 1
    if drop > len(base):
        return None
    prefix = base[: len(base) - drop] if drop else base
    return ".".join([*prefix, node.module]) if node.module else ".".join(prefix)


def import_references(path: Path, source_root: Path) -> list[ImportReference]:
    """Resolve every import reference in one shipped module.

    Covers ``import a.b``, ``from a.b import c`` (recorded as both ``a.b`` and
    ``a.b.c`` so a package re-export cannot hide), explicit relative imports, and
    ``importlib.import_module("...")`` / ``__import__("...")`` string literals.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    references: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module if node.level == 0 else _resolve_relative(path, source_root, node)
            if module is None:
                continue
            references.append(module)
            references.extend(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            target = node.func
            dynamic = (isinstance(target, ast.Name) and target.id == "__import__") or (
                isinstance(target, ast.Attribute) and target.attr == "import_module"
            )
            if dynamic:
                references.extend(
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                )
    return [ImportReference(path=path, reference=reference) for reference in references]


def find_inertness_violations(
    source_root: Path,
    *,
    forbidden_modules: tuple[str, ...],
    forbidden_symbols: frozenset[str],
) -> list[str]:
    """Return every shipped module that reaches a forbidden module or symbol."""

    violations: set[str] = set()
    for path in shipped_modules(source_root):
        for item in import_references(path, source_root):
            reference = item.reference
            if reference.startswith(forbidden_modules):
                violations.add(f"{path.relative_to(source_root)} -> {reference}")
                continue
            if reference.startswith(f"{PACKAGE_PREFIX}."):
                tail = reference.removeprefix(f"{PACKAGE_PREFIX}.")
                if tail in forbidden_symbols:
                    violations.add(f"{path.relative_to(source_root)} -> {reference}")
    return sorted(violations)


def find_text_references(
    source_root: Path,
    needles: frozenset[str],
    *,
    exclude: frozenset[Path] = frozenset(),
) -> list[str]:
    """Return every shipped module whose text names one of ``needles``.

    Scans the standing-authority package too, so a writer adapter hidden inside the
    package is still reported; ``exclude`` carries the defining module itself.
    """

    hits: list[str] = []
    for path in shipped_modules(source_root, include_owning_package=True):
        if path in exclude:
            continue
        text = path.read_text(encoding="utf-8")
        if any(needle in text for needle in needles):
            hits.append(str(path.relative_to(source_root)))
    return sorted(hits)


__all__ = [
    "PACKAGE_PREFIX",
    "ImportReference",
    "find_inertness_violations",
    "find_text_references",
    "import_references",
    "module_name",
    "shipped_modules",
]
