"""Drift guards for required structural gates.

These tests assert that the gates the tracker (#14 / #22) requires stay
wired into CI and the pre-push hook. They are the last line of defence
against someone removing a job to unblock a red pipeline without also
adding the file to an allowlist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PRE_PUSH = _REPO_ROOT / ".githooks" / "pre-push"

_REQUIRED_JOBS = (
    "core-imports",
    "agents-imports",
    "evaluation-boundaries",
    "operator-api-boundaries",
    "evaluation-packages",
    "file-loc",
    "subsystem-fanout",
    "doc-links",
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
        ("evaluation-boundaries", "check-evaluation-boundaries.py"),
        ("operator-api-boundaries", "check-operator-api-boundaries.py"),
        ("file-loc", "check-file-loc.sh"),
        ("subsystem-fanout", "check-subsystem-fanout.sh"),
        ("doc-links", "check-doc-links.sh"),
    ],
)
def test_ci_job_invokes_expected_script(ci_workflow: dict, job: str, script: str) -> None:
    steps = ci_workflow["jobs"][job]["steps"]
    invocations = " ".join(str(step.get("run", "")) for step in steps)
    assert script in invocations, (
        f"CI job '{job}' no longer invokes scripts/{script} - probable"
        " accidental rewrite. See tracker #14."
    )


def test_operator_api_boundary_ci_step_is_exact(ci_workflow: dict) -> None:
    steps = ci_workflow["jobs"]["operator-api-boundaries"]["steps"]
    commands = [str(step.get("run", "")).strip() for step in steps if "run" in step]
    assert commands == ["python3 scripts/quality/architecture/check-operator-api-boundaries.py"]


def test_pre_push_hook_invokes_all_structural_gates() -> None:
    body = _PRE_PUSH.read_text()
    for gate_path in (
        "scripts/quality/architecture/check-agents-imports.sh",
        "scripts/quality/architecture/check-evaluation-boundaries.py",
        "scripts/quality/architecture/check-file-loc.sh",
        "scripts/quality/architecture/check-operator-api-boundaries.py",
        "scripts/quality/architecture/check-subsystem-fanout.sh",
        "scripts/quality/repository/check-doc-links.sh",
    ):
        assert gate_path in body, (
            f"pre-push hook no longer invokes {gate_path} - a routine push"
            " will now miss the structural gate locally. See tracker #14."
        )


def test_operator_api_boundary_gate_is_in_executed_pre_push_loop() -> None:
    body = _PRE_PUSH.read_text()
    loop_start = body.index("for gate_path in \\")
    loop_end = body.index("\ndo\n", loop_start)
    loop_paths = body[loop_start:loop_end]
    assert "scripts/quality/architecture/check-operator-api-boundaries.py \\\n" in loop_paths
    execution_block = body[loop_end : body.index("done", loop_end)]
    assert 'gate_command=(uv run python "$gate_path")' in execution_block
    assert 'gate_command=(python3 "$gate_path")' not in execution_block
    assert (
        'if ! CHECK_QUIET=1 "${gate_command[@]}" > '
        "/tmp/pre-push-${gate}.out 2>&1; then" in execution_block
    )


def test_pre_push_validates_an_isolated_committed_snapshot() -> None:
    body = _PRE_PUSH.read_text()

    assert 'git worktree add --quiet --detach "$validation_root" HEAD' in body
    assert 'git worktree remove --force "$validation_root"' in body
    assert body.index("git worktree add --quiet --detach") < body.index(
        "# 3. Merge-conflict marker guard."
    )
