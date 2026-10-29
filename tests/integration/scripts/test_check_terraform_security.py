"""Contracts for the local Terraform security gate that mirrors the CI job."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2].parent
SCRIPT = ROOT / "scripts/quality/repository/check-terraform-security.sh"
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _run(
    tmp_path: Path, tools: dict[str, str], *, pins: str | None = None
) -> subprocess.CompletedProcess[str]:
    repository = tmp_path / "repo"
    (repository / ".github/workflows").mkdir(parents=True)
    (repository / "infra").mkdir()
    (repository / ".github/workflows/ci.yml").write_text(
        pins
        if pins is not None
        else '          TRIVY_VERSION: "0.72.0"\n          CHECKOV_VERSION: "3.2.256"\n',
        encoding="utf-8",
    )
    subprocess.run(["/usr/bin/git", "init", "-q", str(repository)], check=True)  # noqa: S603
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for utility in ("git", "sed", "head"):
        (binaries / utility).symlink_to(Path("/usr/bin") / utility)
    for name, body in tools.items():
        _stub(binaries, name, body)
    environment = {"PATH": str(binaries), "HOME": str(tmp_path)}
    return subprocess.run(  # noqa: S603
        ["/usr/bin/bash", str(SCRIPT)],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _healthy() -> dict[str, str]:
    return {
        "terraform": "exit 0",
        "trivy": '[ "$1" = "--version" ] && echo "Version: 0.72.0"; exit "${TRIVY_RC:-0}"',
        "checkov": '[ "$1" = "--version" ] && echo "3.2.256"; exit 0',
    }


def test_the_gate_runs_exactly_the_commands_ci_enforces() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "trivy config --exit-code 1 --severity MEDIUM,HIGH,CRITICAL" in source
    assert "--ignorefile infra/trivy-config-ignore.yaml infra" in source
    assert "checkov -d infra --quiet --compact --framework terraform" in source
    assert "terraform fmt -check -recursive infra" in source
    ci = yaml.safe_load(WORKFLOW)["jobs"]["terraform-validate"]["steps"]
    commands = " ".join(step.get("run", "") for step in ci)
    assert "--ignorefile infra/trivy-config-ignore.yaml infra" in commands
    assert "checkov -d infra --quiet --compact --framework terraform" in commands


def test_verify_runs_the_gate_for_infrastructure_changes_only() -> None:
    verify = (ROOT / "scripts/verify.sh").read_text(encoding="utf-8")
    line = next(item for item in verify.splitlines() if '"terraform-security"' in item)
    assert line.startswith("run_gate_scoped ")
    assert "^(infra/|" in line and "check-terraform-security.sh" in line
    assert os.access(SCRIPT, os.X_OK)


def test_a_healthy_toolchain_passes_without_notes(tmp_path: Path) -> None:
    result = _run(tmp_path, _healthy())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NOTE" not in result.stdout and "SKIPPED" not in result.stdout


def test_a_scanner_finding_fails_the_gate(tmp_path: Path) -> None:
    tools = _healthy()
    tools["trivy"] = 'if [ "$1" = "--version" ]; then echo "Version: 0.72.0"; exit 0; fi; exit 1'
    assert _run(tmp_path, tools).returncode == 1


@pytest.mark.parametrize("missing", ["terraform", "trivy", "checkov"])
def test_a_missing_scanner_is_an_environment_fault(tmp_path: Path, missing: str) -> None:
    tools = _healthy()
    del tools[missing]
    result = _run(tmp_path, tools)
    assert result.returncode == 125
    assert f"ENVIRONMENT_FAULT {missing} is not installed" in result.stderr
    assert "SKIPPED" not in result.stdout


@pytest.mark.parametrize(
    ("scanner", "version"),
    [
        ("checkov", "3.0.0"),
        ("checkov", "3.2.2560"),
        ("checkov", "v3.2.256"),
        ("checkov", "Checkov 3.2.256"),
        ("trivy", "Version: 0.7.0"),
        ("trivy", "Version: 0.72.00"),
        ("trivy", "Version: 0.72.0-dev"),
        ("trivy", "0.72.0 not a valid version"),
    ],
)
def test_incompatible_versions_are_environment_faults(
    tmp_path: Path, scanner: str, version: str
) -> None:
    tools = _healthy()
    tools[scanner] = f'[ "$1" = "--version" ] && echo "{version}"; exit 0'
    result = _run(tmp_path, tools)
    assert result.returncode == 125
    assert f"ENVIRONMENT_FAULT {scanner} must match CI version" in result.stderr


@pytest.mark.parametrize("scanner", ["trivy", "checkov"])
def test_a_failed_version_command_is_an_environment_fault(tmp_path: Path, scanner: str) -> None:
    tools = _healthy()
    tools[scanner] = "exit 2"
    result = _run(tmp_path, tools)
    assert result.returncode == 125
    assert f"ENVIRONMENT_FAULT cannot determine {scanner} version" in result.stderr


@pytest.mark.parametrize("pins", ["", 'TRIVY_VERSION: "invalid"\nCHECKOV_VERSION: "3.2.256"\n'])
def test_missing_or_invalid_version_pins_are_environment_faults(tmp_path: Path, pins: str) -> None:
    result = _run(tmp_path, _healthy(), pins=pins)
    assert result.returncode == 125
    assert "ENVIRONMENT_FAULT missing or invalid CI version pin" in result.stderr


@pytest.mark.parametrize("exit_code", [0, 1])
def test_trivy_is_scanned_once_and_failure_output_is_preserved(
    tmp_path: Path, exit_code: int
) -> None:
    tools = _healthy()
    tools["trivy"] = (
        'if [ "$1" = "--version" ]; then echo "Version: 0.72.0"; exit 0; fi\n'
        "echo scanned >>trivy-scans\n"
        'echo "scanner stdout"\necho "scanner stderr" >&2\n'
        f"exit {exit_code}"
    )
    result = _run(tmp_path, tools)
    assert result.returncode == exit_code
    assert (tmp_path / "repo/trivy-scans").read_text(encoding="utf-8") == "scanned\n"
    if exit_code:
        assert "scanner stdout" in result.stderr and "scanner stderr" in result.stderr
    else:
        assert not result.stdout and not result.stderr


@pytest.mark.parametrize("scanner", ["terraform", "checkov"])
def test_other_tool_failures_still_block_the_gate(tmp_path: Path, scanner: str) -> None:
    tools = _healthy()
    tools[scanner] = 'if [ "$1" = "--version" ]; then echo "3.2.256"; exit 0; fi\nexit 1'
    assert _run(tmp_path, tools).returncode == 1


def test_environment_faults_prevent_partial_scanning(tmp_path: Path) -> None:
    tools = _healthy()
    tools["terraform"] = 'echo "fmt must not run"; exit 1'
    del tools["checkov"]
    result = _run(tmp_path, tools)
    assert result.returncode == 125
    assert "fmt must not run" not in result.stdout + result.stderr
