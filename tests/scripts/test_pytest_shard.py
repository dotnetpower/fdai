"""Deterministic pytest shard assignment contract."""

from __future__ import annotations

from pathlib import Path

from scripts.quality.ci.pytest_shard import _shard_for
from scripts.quality.ci.resolve_test_scope import classify_paths


def test_shard_assignment_is_stable_and_bounded() -> None:
    path = Path("tests/core/risk_gate/test_gate.py")
    assert _shard_for(path, 3) == _shard_for(path, 3)
    assert 0 <= _shard_for(path, 3) < 3


def test_each_file_is_assigned_to_exactly_one_shard() -> None:
    paths = (
        Path("tests/core/risk_gate/test_gate.py"),
        Path("tests/core/quality_gate/test_gate.py"),
        Path("tests/delivery/operator_api/test_local.py"),
    )
    assignments = {_shard_for(path, 3) for path in paths}
    assert assignments <= {0, 1, 2}
    assert all(sum(_shard_for(path, 3) == shard for shard in range(3)) == 1 for path in paths)


def test_change_scope_classification_skips_expensive_python_for_docs_and_console() -> None:
    assert classify_paths(["docs/roadmap/architecture/project-structure.md"]) == (False, True)
    assert classify_paths(["console/src/app.tsx"]) == (False, False)
    assert classify_paths(["src/fdai/core/risk_gate/gate.py"]) == (True, False)
    assert classify_paths(["alembic/versions/revision.py"]) == (True, False)
    assert classify_paths(["config/rbac-groups.yaml"]) == (True, False)
    assert classify_paths(["tools/seed_p1_rules.py"]) == (True, False)
    assert classify_paths(["extensions/code-assurance/assets/skill.json"]) == (True, False)
    assert classify_paths(["tests/core/risk_gate/test_gate.py", "README.md"]) == (True, True)
