"""Static dependency boundaries for the independent isolated Executor."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_SOURCE = REPO_ROOT / "services" / "isolated-executor" / "src" / "fdai_executor_service"
CORE_CLIENT = REPO_ROOT / "src" / "fdai" / "runtime" / "isolated_executor_client.py"
CLI_FACADE = REPO_ROOT / "src" / "fdai" / "runtime" / "isolated_executor_cli.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_service_imports_no_core_agent_or_runtime_implementation() -> None:
    forbidden: dict[Path, set[str]] = {}
    for path in SERVICE_SOURCE.rglob("*.py"):
        imports = {
            name
            for name in _imports(path)
            if name in {"fdai.core", "fdai.agents", "fdai.runtime"}
            or name.startswith(("fdai.core.", "fdai.agents.", "fdai.runtime."))
        }
        if imports:
            forbidden[path.relative_to(REPO_ROOT)] = imports

    assert forbidden == {}


def test_service_fdai_dependencies_are_shared_only() -> None:
    invalid: dict[Path, set[str]] = {}
    for path in SERVICE_SOURCE.rglob("*.py"):
        imports = {
            name
            for name in _imports(path)
            if (name == "fdai" or name.startswith("fdai.")) and not name.startswith("fdai.shared.")
        }
        if imports:
            invalid[path.relative_to(REPO_ROOT)] = imports

    assert invalid == {}


def test_core_client_imports_only_shared_fdai_contracts_and_providers() -> None:
    invalid = {
        name
        for name in _imports(CORE_CLIENT)
        if (name == "fdai" or name.startswith("fdai."))
        and not name.startswith(("fdai.shared.contracts", "fdai.shared.providers"))
    }

    assert invalid == set()
    assert "fdai_service_contracts" in _imports(CORE_CLIENT)


def test_deprecated_runtime_cli_is_an_implementation_free_facade() -> None:
    tree = _tree(CLI_FACADE)
    executable_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    assert executable_nodes == []
    assert _imports(CLI_FACADE) == {"fdai_executor_service.cli"}
