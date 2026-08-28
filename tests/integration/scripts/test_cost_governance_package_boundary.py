from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_SOURCE = REPO_ROOT / "services/core-control-plane/src"


def test_core_never_imports_optional_cost_governance_package() -> None:
    violations: list[str] = []
    for path in sorted(CORE_SOURCE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(
                name == "fdai_cost_governance" or name.startswith("fdai_cost_governance.")
                for name in names
            ):
                violations.append(str(path.relative_to(REPO_ROOT)))

    assert violations == []


def test_base_core_imports_when_optional_package_is_not_on_pythonpath() -> None:
    import fdai.core.vertical_packages as vertical_packages

    assert vertical_packages.VerticalPackageManager is not None
