"""Negative import boundary for advisory framework assessment."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "services/core-control-plane/src/fdai/core/framework_assessment"
FORBIDDEN_PREFIXES = (
    "fdai.agents",
    "fdai.core.approval",
    "fdai.core.executor",
    "fdai.core.risk_gate",
    "fdai.core.standing_authority",
)


def test_framework_assessment_cannot_import_authority_or_execution_paths() -> None:
    imports: list[tuple[str, str]] = []
    for path in sorted(SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((path.name, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((path.name, node.module))

    forbidden = [
        f"{filename}:{module}"
        for filename, module in imports
        if module.startswith(FORBIDDEN_PREFIXES)
    ]

    assert forbidden == []
