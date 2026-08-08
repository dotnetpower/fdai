from __future__ import annotations

import ast
from pathlib import Path

import fdai.core.read_investigation as read_investigation


def test_read_investigation_has_no_mutation_bus_thor_or_executor_dependency() -> None:
    package = Path(read_investigation.__file__).parent
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert "object.event" not in source
    assert "Thor" not in source
    assert "executor identity" not in source.casefold()

    imports: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
    assert not any(name.startswith("fdai.core.executor") for name in imports)
    assert not any(name.startswith("fdai.agents") for name in imports)
    assert not any(name.endswith("event_bus") for name in imports)
