from __future__ import annotations

from pathlib import Path

import pytest

from fdai_deployment_cli.deployment_kit_cache import validate_cached_tree


def _tree(tmp_path: Path, *, tool_mode: int) -> tuple[Path, Path]:
    root = tmp_path / "verified"
    (root / "bin").mkdir(parents=True, mode=0o700)
    (root / "terraform").mkdir(mode=0o700)
    root.chmod(0o700)
    terraform = root / "terraform/terraform"
    terraform.write_bytes(b"tf")
    terraform.chmod(0o700)
    tool = root / "bin/kubelogin"
    tool.write_bytes(b"tool")
    tool.chmod(tool_mode)
    data = root / "bin-data.json"
    data.write_bytes(b"{}")
    data.chmod(0o600)
    return root, terraform


def test_materialized_tools_may_be_owner_executable(tmp_path: Path) -> None:
    root, terraform = _tree(tmp_path, tool_mode=0o700)

    validate_cached_tree(root, executable=terraform, tool_directory=root / "bin")


def test_tools_outside_the_tool_directory_stay_non_executable(tmp_path: Path) -> None:
    root, terraform = _tree(tmp_path, tool_mode=0o700)

    with pytest.raises(ValueError, match="file is unsafe"):
        validate_cached_tree(root, executable=terraform)


def test_group_writable_tool_is_rejected(tmp_path: Path) -> None:
    root, terraform = _tree(tmp_path, tool_mode=0o770)

    with pytest.raises(ValueError, match="file is unsafe"):
        validate_cached_tree(root, executable=terraform, tool_directory=root / "bin")
