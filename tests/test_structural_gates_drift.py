"""Drift guards for the three structural gates.

These tests assert that the gates the tracker (#14 / #22) requires stay
wired into CI and the pre-push hook. They are the last line of defence
against someone removing a job to unblock a red pipeline without also
adding the file to an allowlist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PRE_PUSH = _REPO_ROOT / ".githooks" / "pre-push"

_REQUIRED_JOBS = (
    "core-imports",
    "agents-imports",
    "file-loc",
    "subsystem-fanout",
    "protected-paths",
)


@pytest.fixture(scope="module")
def ci_workflow() -> dict:
    return yaml.safe_load(_CI.read_text())


@pytest.mark.parametrize("job", _REQUIRED_JOBS)
def test_ci_workflow_declares_required_job(ci_workflow: dict, job: str) -> None:
    assert job in ci_workflow["jobs"], (
        f"CI workflow missing required structural gate job '{job}'. "
        "Removing a gate to unblock a red pipeline is a drift regression - "
        "add the offending file to the gate's allowlist with a justification "
        "instead. See tracker #14."
    )


@pytest.mark.parametrize(
    "job,script",
    [
        ("core-imports", "check-core-imports.sh"),
        ("agents-imports", "check-agents-imports.sh"),
        ("file-loc", "check-file-loc.sh"),
        ("subsystem-fanout", "check-subsystem-fanout.sh"),
    ],
)
def test_ci_job_invokes_expected_script(
    ci_workflow: dict, job: str, script: str
) -> None:
    steps = ci_workflow["jobs"][job]["steps"]
    invocations = " ".join(str(step.get("run", "")) for step in steps)
    assert script in invocations, (
        f"CI job '{job}' no longer invokes scripts/{script} - probable"
        " accidental rewrite. See tracker #14."
    )


def test_pre_push_hook_invokes_all_three_gates() -> None:
    body = _PRE_PUSH.read_text()
    for gate in ("check-agents-imports", "check-file-loc", "check-subsystem-fanout"):
        assert gate in body, (
            f"pre-push hook no longer invokes {gate}.sh - a routine push"
            " will now miss the structural gate locally. See tracker #14."
        )
