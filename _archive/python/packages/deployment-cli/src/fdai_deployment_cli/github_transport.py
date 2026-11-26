"""Bounded GitHub CLI process transport."""

from __future__ import annotations

import shutil
import subprocess

from fdai_deployment_cli.github_workflow_values import CommandResult, CommandRunner

_ARTIFACT_DOWNLOAD_TIMEOUT = 90

_DEFAULT_GH_TIMEOUT = 30


def run_github_cli(
    arguments: tuple[str, ...],
    timeout: int = _DEFAULT_GH_TIMEOUT,
) -> CommandResult:
    """Execute one fixed GitHub CLI command with bounded output and duration."""

    executable = shutil.which("gh")
    if executable is None:
        raise OSError("GitHub CLI is unavailable")
    try:
        completed = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stdout="", stderr="")
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout[:65_536],
        stderr=completed.stderr[:65_536],
    )


def _artifact_runner(base: CommandRunner) -> CommandRunner:
    """Wrap the real runner with a longer timeout for artifact downloads."""

    if base is not run_github_cli:
        return base  # Test runners handle their own timing.
    return lambda args: run_github_cli(args, timeout=_ARTIFACT_DOWNLOAD_TIMEOUT)
