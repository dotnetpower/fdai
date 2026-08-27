"""Regression contract for neutral runtime tool descriptions."""

from __future__ import annotations

import ast
from pathlib import Path

CONVERSATION_ROOT = Path(__file__).resolve().parents[2] / "src" / "fdai" / "core" / "conversation"
FORBIDDEN_PARENT_DIRECTIVES = (
    "ask the user",
    "end your response",
    "reply to the user",
    "respond to the user",
    "stop after",
    "stop here",
    "wait for the user",
)


def _class_string_attributes(node: ast.ClassDef) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for statement in node.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"name", "description"}:
            continue
        try:
            value = ast.literal_eval(statement.value)
        except (ValueError, TypeError):
            continue
        if isinstance(value, str):
            attributes[target.id] = value
    return attributes


def test_runtime_tool_descriptions_do_not_direct_parent_conversation_flow() -> None:
    violations: list[str] = []
    discovered = 0

    for path in sorted(CONVERSATION_ROOT.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in (item for item in module.body if isinstance(item, ast.ClassDef)):
            attributes = _class_string_attributes(node)
            if not {"name", "description"} <= attributes.keys():
                continue
            discovered += 1
            normalized = " ".join(attributes["description"].casefold().split())
            for directive in FORBIDDEN_PARENT_DIRECTIVES:
                if directive in normalized:
                    violations.append(f"{path.name}:{node.name}: {directive!r}")

    assert discovered > 0, "no runtime tool descriptions were discovered"
    assert violations == [], (
        "Tool descriptions must describe capability, inputs, effects, and authority without "
        f"directing the parent conversation: {violations}"
    )
