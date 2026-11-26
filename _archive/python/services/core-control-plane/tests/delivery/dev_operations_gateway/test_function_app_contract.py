"""Static worker-indexing contract for the standalone Function artifact."""

from __future__ import annotations

import ast
from pathlib import Path


def _gateway_source(name: str) -> str:
    root = Path(__file__).resolve().parents[5]
    return (root / "delivery" / "dev_operations_gateway" / name).read_text(encoding="utf-8")


def test_function_artifact_remains_python_310_compatible() -> None:
    tree = ast.parse(_gateway_source("idempotency.py"))

    datetime_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "datetime"
        for alias in node.names
    }

    assert "UTC" not in datetime_imports
    assert "timezone" in datetime_imports


def test_http_trigger_names_match_python_parameters() -> None:
    tree = ast.parse(_gateway_source("function_app.py"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in {"health", "invoke"}
    }

    assert set(functions) == {"health", "invoke"}
    for function in functions.values():
        route = next(
            decorator
            for decorator in function.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "route"
        )
        trigger_arg = next(
            keyword.value for keyword in route.keywords if keyword.arg == "trigger_arg_name"
        )
        assert isinstance(trigger_arg, ast.Constant)
        assert trigger_arg.value == function.args.args[0].arg
