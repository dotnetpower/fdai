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
    assert 'output="$(CHECK_QUIET=1 timeout 600 "${gate_command[@]}" 2>&1)"' in execution_block
    assert "/tmp/" not in execution_block  # noqa: S108 - shared temp paths are forbidden here
    assert "exec python3 scripts/automation/local_validation_cache.py structural" in body


def test_pre_push_runs_the_structural_gate_helper() -> None:
    body = _PRE_PUSH.read_text()

    assert "bash scripts/automation/run-pre-push-structural-gates.sh" in body


def test_pre_push_validates_workflow_contract_changes_before_structural_gates() -> None:
    body = _PRE_PUSH.read_text()

    contract_check = "uv run --extra dev python scripts/quality/ci/check-ci-contracts.py"
    regression_test = "tests/integration/scripts/test_check_ci_contracts.py"
    structural_check = "bash scripts/automation/run-pre-push-structural-gates.sh"
    assert ".github/workflows/*.yml" in body
    assert contract_check in body
    assert regression_test in body
    assert body.index(contract_check) < body.index(structural_check)


def test_pre_push_clears_repo_local_git_environment_before_validation(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    repository.mkdir()
    fake_bin.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    structural = repository / "scripts" / "automation" / "run-pre-push-structural-gates.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    workflow = repository / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repository, check=True)
    initial_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", initial_commit],
        cwd=repository,
        check=True,
    )
    workflow.write_text("name: changed\n", encoding="utf-8")
    subprocess.run(["git", "add", str(workflow)], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "changed"], cwd=repository, check=True)
    changed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${GIT_DIR+x}" == x || "${GIT_WORK_TREE+x}" == x ]]; then\n'
        '  echo "repository-local Git environment leaked into validation" >&2\n'
        "  exit 42\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["GIT_DIR"] = str(repository / ".git")
    environment["GIT_WORK_TREE"] = str(repository)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    hook_input = f"refs/heads/main {changed_commit} refs/heads/main {initial_commit}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        env=environment,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pre-push: OK" in result.stdout
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )


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


def test_pre_push_rejects_a_tag_outside_protected_main(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("protected\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "protected"], cwd=repository, check=True)
    protected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", protected_commit],
        cwd=repository,
        check=True,
    )
    tracked.write_text("unmerged\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "unmerged"], cwd=repository, check=True)
    unmerged_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = f"refs/tags/v1 {unmerged_commit} refs/tags/v1 {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "tag 'v1' is not on refs/remotes/origin/main" in result.stdout


def test_pre_push_classifies_a_branch_source_by_its_tag_destination(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("protected\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "protected"], cwd=repository, check=True)
    protected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", protected_commit],
        cwd=repository,
        check=True,
    )
    tracked.write_text("unmerged\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "unmerged"], cwd=repository, check=True)
    unmerged_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = f"refs/heads/main {unmerged_commit} refs/tags/v1 {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "tag 'v1' is not on refs/remotes/origin/main" in result.stdout


def test_pre_push_rejects_rewriting_an_existing_tag(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "first"], cwd=repository, check=True)
    first_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked.write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=repository, check=True)
    second_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", second_commit],
        cwd=repository,
        check=True,
    )
    hook_input = f"refs/tags/v1 {second_commit} refs/tags/v1 {first_commit}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "existing tag 'v1' is immutable" in result.stdout


def test_pre_push_accepts_an_atomic_main_and_tag_update(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    structural = repository / "scripts" / "automation" / "run-pre-push-structural-gates.sh"
    structural.parent.mkdir(parents=True)
    structural.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    tracked = repository / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "first"], cwd=repository, check=True)
    first_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", first_commit],
        cwd=repository,
        check=True,
    )
    tracked.write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=repository, check=True)
    second_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = (
        f"refs/heads/main {second_commit} refs/heads/main {first_commit}\n"
        f"refs/tags/v-test {second_commit} refs/tags/v-test {'0' * 40}\n"
    )

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pre-push: OK" in result.stdout


def test_pre_push_rejects_tags_with_stale_release_controls(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    workflow = repository / ".github" / "workflows" / "container-supply-chain.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: legacy\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "legacy"], cwd=repository, check=True)
    legacy_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    workflow.write_text("name: protected\n", encoding="utf-8")
    subprocess.run(["git", "add", str(workflow)], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "protected"], cwd=repository, check=True)
    protected_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", protected_commit],
        cwd=repository,
        check=True,
    )
    hook_input = f"refs/tags/v1 {legacy_commit} refs/tags/v1 {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "tag 'v1' uses stale release controls" in result.stdout


def test_pre_push_rejects_tag_only_publication_with_stale_tracking(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "first"], cwd=repository, check=True)
    first_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", first_commit],
        cwd=repository,
        check=True,
    )
    tracked.write_text("second\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=repository, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "push",
            str(remote),
            "main:main",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    hook_input = f"refs/tags/v1 {first_commit} refs/tags/v1 {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin", str(remote)],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "protected branch tracking state is stale for tag publication" in result.stdout


def test_pre_push_rejects_a_tag_source_for_a_branch_destination(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("value\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repository, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = f"refs/tags/v1 {commit} refs/heads/main {'0' * 40}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "unsupported push source ref 'refs/tags/v1'" in result.stdout


def test_pre_push_rejects_ref_deletion(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "FDAI Tests"],
        cwd=repository,
        check=True,
    )
    tracked = repository / "tracked.txt"
    tracked.write_text("value\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=repository, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_input = f"(delete) {'0' * 40} refs/heads/main {commit}\n"

    result = subprocess.run(
        ["bash", str(_PRE_PUSH), "origin"],
        cwd=repository,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "ref deletion requires explicit remote administration: refs/heads/main" in result.stdout


def test_pre_push_clears_parent_git_context_before_workflow_contract_tests() -> None:
    hook = _PRE_PUSH.read_text(encoding="utf-8")

    assert "env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE" in hook


def test_pre_push_routes_deleted_and_yaml_workflows_to_contract_checks() -> None:
    body = _PRE_PUSH.read_text()

    assert "mapfile -d '' -t changed_paths" in body
    assert 'git diff --name-only -z --diff-filter=ACMRTD "$range"' in body
    assert ".github/workflows/*.yaml" in body
    assert ".github/actions/*" in body
    assert 'for f in "${changed_paths[@]}"; do' in body


def test_pre_push_lints_every_changed_python_file() -> None:
    body = _PRE_PUSH.read_text()

    assert "# 3. Fast ruff lint on every changed Python file." in body
    assert '*.py) [ -f "$f" ] && py+=("$f")' in body
    assert "src/*.py | tests/*.py" not in body


def test_pre_push_validates_an_isolated_committed_snapshot() -> None:
    body = _PRE_PUSH.read_text()

    assert 'git worktree add --quiet --detach "$validation_root" "$local_sha"' in body
    assert 'git worktree remove --force "$validation_root"' in body
    assert body.index("git worktree add --quiet --detach") < body.index(
        "# 2. Merge-conflict marker guard."
    )
