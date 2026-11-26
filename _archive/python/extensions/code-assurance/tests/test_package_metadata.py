from __future__ import annotations

import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependency_uses_core_control_plane_distribution() -> None:
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    requirements = set(project["dependencies"])

    assert "fdai-core-control-plane==0.1.0" in requirements
    assert not any(value == "fdai" or value.startswith("fdai>") for value in requirements)
