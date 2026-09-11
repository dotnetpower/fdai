"""Drift guards for required structural gates.

These tests assert that the gates the tracker (#14 / #22) requires stay
wired into CI and the pre-push hook. A gate may share a CI job with other
lightweight checks, but its command and aggregate required status remain
mandatory.
"""

# ruff: noqa: S603, S607 - tests execute fixed repository hooks and Git commands.

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PRE_PUSH = _REPO_ROOT / ".githooks" / "pre-push"

_REQUIRED_GATE_BINDINGS = (
    ("contracts", "check-core-imports.sh"),
    ("contracts", "check-agents-imports.sh"),
    ("contracts", "check-evaluation-boundaries.py"),
    ("contracts", "check-operator-api-boundaries.py"),
    ("contracts", "check-file-loc.sh"),
    ("contracts", "check-subsystem-fanout.sh"),
    ("contracts", "check-doc-links.sh"),
    ("contracts", "check-protected-paths.sh"),
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
    steps = ci_workflow["jobs"]["contracts"]["steps"]
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


def test_pre_push_validates_workflow_contract_changes_before_structural_gates() -> None:
    body = _PRE_PUSH.read_text()

    contract_check = "python3 scripts/quality/ci/check-ci-contracts.py"
    regression_test = "tests/integration/scripts/test_check_ci_contracts.py"
    structural_check = "bash scripts/automation/run-pre-push-structural-gates.sh"
    assert ".github/workflows/*.yml" in body
    assert contract_check in body
    assert regression_test in body
    assert body.index(contract_check) < body.index(structural_check)


def test_pre_push_validates_a_new_branch_against_the_remote_default() -> None:
    body = _PRE_PUSH.read_text()

    assert 'remote_head="$(git symbolic-ref --quiet "refs/remotes/$remote_name/HEAD"' in body
    assert 'base_ref="${remote_head:-refs/remotes/$remote_name/main}"' in body
    assert 'range="$base_sha..$local_sha"' in body
    assert "new; skipping sync + diff checks" not in body


@pytest.mark.parametrize(
    ("local_ref", "expected_message"),
    (
        ("refs/heads/topic", "refusing to validate a non-current branch push"),
        ("HEAD", "unsupported push source ref 'HEAD'"),
    ),
)
def test_pre_push_blocks_unowned_source_refs(
    tmp_path: Path,
    local_ref: str,
    expected_message: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    git_env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        env=git_env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        env=git_env,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        env=git_env,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("value\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, env=git_env, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "initial"],
        cwd=repository,
        env=git_env,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        env=git_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = f"{local_ref} {commit} refs/heads/topic {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        env=git_env,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert expected_message in result.stdout


def test_pre_push_routes_deleted_and_yaml_workflows_to_contract_checks() -> None:
    body = _PRE_PUSH.read_text()

    assert 'changed_paths < <(git diff --name-only --diff-filter=ACMRTD "$range"' in body
    assert ".github/workflows/*.yaml" in body
    assert 'for f in "${changed_paths[@]}"; do' in body


def test_pre_push_validates_an_isolated_committed_snapshot() -> None:
    body = _PRE_PUSH.read_text()

    assert 'git worktree add --quiet --detach "$validation_root" "$local_sha"' in body
    assert 'git worktree remove --force "$validation_root"' in body
    assert body.index("git worktree add --quiet --detach") < body.index(
        "# 2. Merge-conflict marker guard."
    )
