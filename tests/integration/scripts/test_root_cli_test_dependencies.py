"""Keep root test collection provisioned for the separately locked deployment CLI."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("name", "requirement", "owner"),
    [
        ("rich", "rich>=14,<15", "runtime"),
        ("pyte", "pyte>=0.8,<0.9", "test"),
    ],
)
def test_root_dev_environment_declares_standalone_cli_test_dependencies(
    name: str, requirement: str, owner: str
) -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    cli = tomllib.loads(
        (ROOT / "packages/deployment-cli/pyproject.toml").read_text(encoding="utf-8")
    )
    owned = (
        cli["project"]["dependencies"] if owner == "runtime" else cli["dependency-groups"]["dev"]
    )
    assert requirement in owned
    assert requirement in root["project"]["optional-dependencies"]["dev"]
    assert importlib.util.find_spec(name) is not None

    # Root tooling must not turn the independently locked CLI into a service or runtime dependency.
    assert "packages/deployment-cli" not in root["tool"]["uv"]["workspace"]["members"]
    assert root["project"]["dependencies"] == []

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    workspace = next(package for package in lock["package"] if package["name"] == "fdai")
    assert {"name": name} in workspace["optional-dependencies"]["dev"]
