"""Drift guards for required structural gates.

These tests assert that the gates the tracker (#14 / #22) requires stay
wired into CI and the pre-push hook. A gate may share a CI job with other
lightweight checks, but its command and aggregate required status remain
mandatory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PRE_PUSH = _REPO_ROOT / ".githooks" / "pre-push"

_REQUIRED_GATE_BINDINGS = (
    ("repository-contracts", "check-core-imports.sh"),
    ("repository-contracts", "check-agents-imports.sh"),
    ("repository-contracts", "check-evaluation-boundaries.py"),
    ("repository-contracts", "check-operator-api-boundaries.py"),
    ("repository-contracts", "check-file-loc.sh"),
    ("repository-contracts", "check-subsystem-fanout.sh"),
    ("repository-contracts", "check-doc-links.sh"),
    ("design-contracts", "check-protected-paths.sh"),
)


@pytest.fixture(scope="module")
def ci_workflow() -> dict:
    return yaml.safe_load(_CI.read_text())


@pytest.mark.parametrize("job,script", _REQUIRED_GATE_BINDINGS)
def test_ci_job_invokes_expected_script(ci_workflow: dict, job: str, script: str) -> None:
    assert job in ci_workflow["jobs"]
    steps = ci_workflow["jobs"][job]["steps"]
    invocations = " ".join(str(step.get("run", "")) for step in steps)
    assert script in invocations, (
        f"CI job '{job}' no longer invokes scripts/{script} - probable"
        " accidental rewrite. See tracker #14."
    )
    assert job in ci_workflow["jobs"]["required"]["needs"]


def test_evaluation_packages_remain_a_required_independent_job(ci_workflow: dict) -> None:
    assert "evaluation-packages" in ci_workflow["jobs"]
    assert "evaluation-packages" in ci_workflow["jobs"]["required"]["needs"]


def test_operator_api_boundary_ci_step_is_exact(ci_workflow: dict) -> None:
    steps = ci_workflow["jobs"]["repository-contracts"]["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps if "run" in step)

    command = "python3 scripts/quality/architecture/check-operator-api-boundaries.py"
    assert commands.count(command) == 1


def test_pre_push_hook_invokes_all_structural_gates() -> None:
    body = (_REPO_ROOT / "scripts" / "automation" / "run-pre-push-structural-gates.sh").read_text()
    for gate_path in (
        "scripts/quality/architecture/check-agents-imports.sh",
        "scripts/quality/architecture/check-evaluation-boundaries.py",
        "scripts/quality/architecture/check-file-loc.sh",
        "scripts/quality/architecture/check-independent-services.py",
        "scripts/quality/architecture/check-operator-api-boundaries.py",
        "scripts/quality/architecture/check-subsystem-fanout.sh",
        "scripts/quality/repository/check-doc-links.sh",
    ):
        assert gate_path in body, (
            f"pre-push hook no longer invokes {gate_path} - a routine push"
            " will now miss the structural gate locally. See tracker #14."
        )


def test_operator_api_boundary_gate_is_in_executed_pre_push_loop() -> None:
    body = (_REPO_ROOT / "scripts" / "automation" / "run-pre-push-structural-gates.sh").read_text()
    loop_start = body.index("for gate_path in \\")
    loop_end = body.index("\ndo\n", loop_start)
    loop_paths = body[loop_start:loop_end]
    assert "scripts/quality/architecture/check-operator-api-boundaries.py \\\n" in loop_paths
    execution_block = body[loop_end : body.index("done", loop_end)]
    assert 'gate_command=(uv run --extra dev python "$gate_path")' in execution_block
    assert 'gate_command=(python3 "$gate_path")' not in execution_block
    assert 'output="${TMPDIR:-/tmp}/pre-push-${gate}.out"' in execution_block
    assert 'if ! CHECK_QUIET=1 "${gate_command[@]}" > "$output" 2>&1; then' in execution_block


def test_pre_push_runs_the_structural_gate_helper() -> None:
    body = _PRE_PUSH.read_text()

    assert "bash scripts/automation/run-pre-push-structural-gates.sh" in body


def test_pre_push_validates_an_isolated_committed_snapshot() -> None:
    body = _PRE_PUSH.read_text()

    assert 'git worktree add --quiet --detach "$validation_root" HEAD' in body
    assert 'git worktree remove --force "$validation_root"' in body
    assert body.index("git worktree add --quiet --detach") < body.index(
        "# 2. Merge-conflict marker guard."
    )
