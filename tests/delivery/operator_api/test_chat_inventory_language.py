from __future__ import annotations

import ast
from pathlib import Path

from fdai.delivery.operator_api.routes.chat_inventory_language import (
    default_inventory_query_language_resolver,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_catalog_resolves_comparison_question_semantics() -> None:
    resolver = default_inventory_query_language_resolver()
    registry = resolver.registry

    assert resolver.matched_values(registry.states, "중지된 데이터베이스 있어?") == (
        "stopped",
        "deallocated",
    )
    assert resolver.matched_values(registry.states, "Are any databases stopped right now?") == (
        "stopped",
        "deallocated",
    )
    assert resolver.matched_ids(registry.query_kinds, "현재 멈춰 있는 DB를 종류별로 보여줘.") == (
        "types",
    )
    assert resolver.matched_ids(
        registry.groupings, "List stopped and paused database services separately."
    ) == ("status",)
    assert resolver.matched_values(
        registry.states, "List stopped and paused database services separately."
    ) == ("stopped", "deallocated", "paused")


def test_catalog_parses_bilingual_activity_windows() -> None:
    resolver = default_inventory_query_language_resolver()
    assert resolver.parse_window_seconds("resources deleted in the last 2 weeks") == 1209600
    assert resolver.parse_window_seconds("최근 7일 변경된 리소스") == 604800


def test_inventory_modules_do_not_own_prompt_regular_expressions() -> None:
    modules = (
        "chat_inventory.py",
        "chat_inventory_compiler.py",
        "chat_inventory_followup.py",
        "chat_inventory_resource_types.py",
    )

    for module in modules:
        path = REPO_ROOT / "src" / "fdai" / "delivery" / "operator_api" / "routes" / module
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "re" not in imports, module
