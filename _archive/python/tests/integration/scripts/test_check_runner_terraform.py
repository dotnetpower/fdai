"""Protected deploy runners refuse a Terraform older than the validated toolchain."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_GUARD = _ROOT / "scripts" / "deployment" / "azure" / "check-runner-terraform.sh"
_GENESIS_TOOLCHAIN = _ROOT / "infra" / "genesis-runner-image" / "toolchain.json"


def _bin_with_jq(tmp_path: Path) -> Path:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required by the protected runner guard")
    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "jq").symlink_to(jq)
    return directory


def _terraform(directory: Path, output: str) -> None:
    binary = directory / "terraform"
    binary.write_text(
        f"""#!/bin/bash
[[ "$*" == "version -json" ]] || exit 9
printf '%s\\n' '{output}'
""",
        encoding="ascii",
    )
    binary.chmod(0o755)


def _run(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - controlled repository script
        ["/bin/bash", str(_GUARD)],
        cwd=_ROOT,
        env={**os.environ, "PATH": str(directory)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("version", ["1.16.1", "1.16.2", "1.17.0", "1.17.0-beta1", "2.0.0"])
def test_validated_or_newer_terraform_passes(tmp_path: Path, version: str) -> None:
    directory = _bin_with_jq(tmp_path)
    _terraform(directory, f'{{"terraform_version":"{version}"}}')

    result = _run(directory)

    assert result.returncode == 0, result.stderr
    assert f"Terraform {version} meets the protected-workflow minimum 1.16.1" in result.stdout


@pytest.mark.parametrize("version", ["1.9.8", "1.15.6", "1.16.0", "1.16.1-rc1", "0.17.1"])
def test_older_terraform_fails_fast_with_the_required_version(tmp_path: Path, version: str) -> None:
    directory = _bin_with_jq(tmp_path)
    _terraform(directory, f'{{"terraform_version":"{version}"}}')

    result = _run(directory)

    assert result.returncode == 1
    assert f"has Terraform {version}; protected workflows require 1.16.1 or later" in result.stderr
    assert "Genesis-image runners pin an older toolchain" in result.stderr


@pytest.mark.parametrize(
    "output",
    ["not json", '{"terraform_version":1.17}', '{"terraform_version":"v1.17.0"}', "{}"],
)
def test_unreadable_terraform_version_fails_closed(tmp_path: Path, output: str) -> None:
    directory = _bin_with_jq(tmp_path)
    _terraform(directory, output)

    result = _run(directory)

    assert result.returncode == 1
    assert "Terraform version" in result.stderr


def test_runner_without_terraform_passes_with_a_notice(tmp_path: Path) -> None:
    directory = _bin_with_jq(tmp_path)

    result = _run(directory)

    assert result.returncode == 0
    assert "Terraform is not installed" in result.stdout


def test_genesis_toolchain_pin_is_judged_by_the_same_minimum(tmp_path: Path) -> None:
    pinned = json.loads(_GENESIS_TOOLCHAIN.read_text(encoding="utf-8"))["terraform_version"]
    directory = _bin_with_jq(tmp_path)
    _terraform(directory, f'{{"terraform_version":"{pinned}"}}')

    result = _run(directory)

    older = tuple(int(part) for part in pinned.split(".")) < (1, 16, 1)
    assert result.returncode == (1 if older else 0)
    assert (f"has Terraform {pinned}" in result.stderr) is older
