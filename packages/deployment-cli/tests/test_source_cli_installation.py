"""The managed host installs the source CLI without any package index publishing FDAI packages."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from fdai_deployment_cli.standalone_remote_prepare import _source_cli_installation

PACKAGES = Path(__file__).resolve().parents[2]


def _name(project: Path) -> str:
    return tomllib.loads((project / "pyproject.toml").read_text())["project"]["name"]


def test_every_pinned_fdai_dependency_is_installed_from_the_snapshot():
    ((step, command, _limit),) = _source_cli_installation("/srv/run")
    assert step == "install-source-cli"
    tree = "/srv/run/source-snapshot/tree/"
    local = [argument.removeprefix(tree) for argument in command if argument.startswith(tree)]
    assert local[-1] == "packages/deployment-cli"
    installed = {_name(PACKAGES.parent / path) for path in local}
    dependencies = tomllib.loads((PACKAGES / "deployment-cli/pyproject.toml").read_text())[
        "project"
    ]["dependencies"]
    pinned = {
        re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
        for requirement in dependencies
        if requirement.startswith("fdai-")
    }
    assert pinned
    assert pinned <= installed
