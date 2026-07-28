#!/usr/bin/env python3
"""Enforce SDK, host, benchmark, metadata, and workspace dependency boundaries."""

from __future__ import annotations

import argparse
import ast
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    message: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    violations = scan(root)
    for violation in violations:
        relative = violation.path.relative_to(root)
        print(f"{relative}:{violation.line}: {violation.message}")
    if violations:
        print(f"check-evaluation-boundaries: FAILED ({len(violations)} violation(s))")
        return 1
    print("check-evaluation-boundaries: OK")
    return 0


def scan(root: Path) -> tuple[Violation, ...]:
    violations: list[Violation] = []
    for path, surface in _python_surfaces(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError:
            violations.append(Violation(path, 1, "Python source cannot be read"))
            continue
        except SyntaxError as exc:
            if surface == "benchmarks" or "/fdai/evaluation/" in path.as_posix():
                violations.append(
                    Violation(path, exc.lineno or 1, "evaluation Python source cannot be parsed")
                )
                continue
            violations.extend(_fallback_import_scan(path, surface))
            continue
        visitor = _BoundaryVisitor(path=path, surface=surface)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return tuple(sorted(violations, key=lambda item: (str(item.path), item.line, item.message)))


def _fallback_import_scan(path: Path, surface: str) -> tuple[Violation, ...]:
    """Scan dependency direction when the local parser predates source syntax."""

    violations: list[Violation] = []
    if surface == "sdk":
        pattern = re.compile(
            r"^\s*(?:from|import)\s+(?:fdai(?:\.|\s|$)|fdai_bench_[A-Za-z0-9_.]*)",
            re.MULTILINE,
        )
        message = "evaluation SDK MUST NOT import FDAI implementations"
    else:
        pattern = re.compile(
            r"^\s*(?:from|import)\s+fdai_bench_[A-Za-z0-9_.]*",
            re.MULTILINE,
        )
        message = "FDAI implementation MUST NOT import benchmark packages"
    source = path.read_text(encoding="utf-8")
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start()) + 1
        violations.append(Violation(path, line, message))
    return tuple(violations)


def _python_surfaces(root: Path):  # type: ignore[no-untyped-def]
    surfaces = (
        (root / "src" / "fdai", "fdai"),
        (root / "evaluation-sdk" / "src", "sdk"),
        (root / "benchmarks", "benchmarks"),
    )
    for base, surface in surfaces:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or (surface == "benchmarks" and "src" not in path.parts):
                continue
            yield path, surface


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, *, path: Path, surface: str) -> None:
        self._path = path
        self._surface = surface
        self.violations: list[Violation] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name, node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module is not None:
            self._check_import(node.module, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if self._surface in {"fdai", "benchmarks"} and (
            name.startswith("subprocess.")
            or name in {"os.system", "os.popen", "asyncio.create_subprocess_exec"}
        ):
            if self._is_evaluation_surface():
                self._add(node.lineno, "workspace command bypasses the reviewed provider")
        if name.endswith("MetadataEntry"):
            for keyword in node.keywords:
                if keyword.arg == "value" and _contains_bytes(keyword.value):
                    self._add(node.lineno, "binary artifact content MUST NOT enter metadata")
        if name.startswith(("logging.", "logger.", "_LOGGER.", "_LOG.")) and any(
            _contains_bytes(argument) for argument in node.args
        ):
            self._add(node.lineno, "binary artifact content MUST NOT enter logs")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "metadata" and _contains_bytes(value):
                self._add(node.lineno, "binary artifact content MUST NOT enter metadata")
        self.generic_visit(node)

    def _check_import(self, module: str, line: int) -> None:
        if self._surface == "fdai" and module.startswith("fdai_bench_"):
            self._add(line, "FDAI implementation MUST NOT import benchmark packages")
        elif self._surface == "sdk" and (
            module == "fdai" or module.startswith(("fdai.", "fdai_bench_"))
        ):
            self._add(line, "evaluation SDK MUST NOT import FDAI implementations")
        elif self._surface == "benchmarks" and module.startswith("fdai."):
            if not module.startswith("fdai.evaluation.public"):
                self._add(line, "benchmark package imports a private FDAI implementation")

    def _is_evaluation_surface(self) -> bool:
        path_text = self._path.as_posix()
        return "/fdai/evaluation/" in path_text or "/benchmarks/" in path_text

    def _add(self, line: int, message: str) -> None:
        self.violations.append(Violation(self._path, line, message))


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _contains_bytes(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Constant) and isinstance(child.value, bytes)
        for child in ast.walk(node)
    )


if __name__ == "__main__":
    raise SystemExit(main())
