from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
QUEUE_SCRIPT = REPO_ROOT / "scripts" / "automation" / "validation_queue.py"
POST_COMMIT_HOOK = REPO_ROOT / ".githooks" / "post-commit"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"
VALIDATOR_AGENT = REPO_ROOT / ".github" / "agents" / "integration-validator.agent.md"


def _run(
    cwd: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled arguments and repository paths
        list(arguments),
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "automation").mkdir(parents=True)
    shutil.copy2(QUEUE_SCRIPT, repo / "scripts" / "automation" / "validation_queue.py")
    (repo / "scripts" / "automation" / "tests-for-diff.sh").write_text(
        "#!/usr/bin/env bash\n"
        "test -f resolved-models.json || exit 9\n"
        'printf "changed:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n',
        encoding="utf-8",
    )
    (repo / "scripts" / "verify.sh").write_text(
        "#!/usr/bin/env bash\n"
        "test -f resolved-models.json || exit 9\n"
        'printf "verify:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n',
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text("resolved-models*.json\n", encoding="utf-8")
    (repo / "source.txt").write_text("initial\n", encoding="utf-8")
    assert _run(repo, "git", "init", "--quiet", "--initial-branch=main").returncode == 0
    assert _run(repo, "git", "config", "user.email", "user@example.com").returncode == 0
    assert _run(repo, "git", "config", "user.name", "Example User").returncode == 0
    assert _run(repo, "git", "add", ".").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "initial").returncode == 0
    (repo / "resolved-models.json").write_text('{"capabilities": {}}\n', encoding="utf-8")
    return repo


def _commit_change(repo: Path) -> str:
    (repo / "source.txt").write_text("changed\n", encoding="utf-8")
    assert _run(repo, "git", "add", "source.txt").returncode == 0
    assert _run(repo, "git", "commit", "--quiet", "-m", "change").returncode == 0
    result = _run(repo, "git", "rev-parse", "HEAD")
    assert result.returncode == 0
    return result.stdout.strip()


def test_run_batches_pending_commits_and_records_receipts(git_repo: Path, tmp_path: Path) -> None:
    commit = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", "HEAD^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    revision_range = "HEAD^..HEAD"
    log_path = tmp_path / "validation.log"

    enqueued = _run(git_repo, "python3", str(script), "enqueue", commit)
    blocked = _run(git_repo, "python3", str(script), "check-range", revision_range)
    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )
    accepted = _run(git_repo, "python3", str(script), "check-range", revision_range)

    assert enqueued.returncode == 0, enqueued.stderr
    assert blocked.returncode == 1
    assert validated.returncode == 0, validated.stderr
    assert accepted.returncode == 0, accepted.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        f"changed:--run {parent}..{commit}",
        "verify:--fast",
    ]


def test_linked_worktree_uses_the_shared_git_queue(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    assert (
        _run(git_repo, "git", "worktree", "add", "--quiet", "--detach", str(linked)).returncode == 0
    )
    script = linked / "scripts" / "automation" / "validation_queue.py"

    enqueued = _run(linked, "python3", str(script), "enqueue", "HEAD")
    status = _run(git_repo, "python3", str(script), "status")

    assert enqueued.returncode == 0, enqueued.stderr
    assert status.returncode == 0, status.stderr
    assert "1 pending commit(s)" in status.stdout


def test_concurrent_enqueue_of_same_commit_is_atomic(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"

    def enqueue() -> subprocess.CompletedProcess[str]:
        return _run(git_repo, "python3", str(script), "enqueue", "HEAD")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: enqueue(), range(16)))

    assert all(result.returncode == 0 for result in results)
    status = _run(git_repo, "python3", str(script), "status")
    assert "1 pending commit(s)" in status.stdout


def test_all_mode_skips_changed_test_pass(git_repo: Path, tmp_path: Path) -> None:
    _commit_change(git_repo)
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", "HEAD").returncode == 0

    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        "--all",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert validated.returncode == 0, validated.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == ["verify:--all"]


def test_post_commit_hook_automatically_enqueues_commit(git_repo: Path) -> None:
    hooks = git_repo / ".githooks"
    hooks.mkdir()
    shutil.copy2(POST_COMMIT_HOOK, hooks / "post-commit")
    (hooks / "post-commit").chmod(0o755)
    assert _run(git_repo, "git", "config", "core.hooksPath", ".githooks").returncode == 0

    commit = _commit_change(git_repo)
    common_dir = Path(_run(git_repo, "git", "rev-parse", "--git-common-dir").stdout.strip())

    assert (
        git_repo / common_dir / "fdai-validation-queue" / "pending" / f"{commit}.json"
    ).is_file()


def test_pre_push_requires_central_validation_receipts() -> None:
    hook = PRE_PUSH_HOOK.read_text(encoding="utf-8")

    ensure_offset = hook.index('ensure-range "$range"')
    check_offset = hook.index('check-range "$range"')
    worktree_offset = hook.index("git worktree add")

    assert ensure_offset < check_offset < worktree_offset


def test_validator_agent_is_read_execute_only_and_uses_make_facade() -> None:
    _prefix, frontmatter, body = VALIDATOR_AGENT.read_text(encoding="utf-8").split("---", 2)
    config = yaml.safe_load(frontmatter)
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert config["name"] == "Integration Validator"
    assert config["tools"] == ["read", "execute"]
    assert config["agents"] == []
    assert config["user-invocable"] is True
    assert "make validation-status" in body
    assert "make validation-run" in body
    assert "validation-status:" in makefile
    assert "validation-run:" in makefile
    assert "validation-all:" in makefile


def test_queue_cli_runs_with_system_python() -> None:
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file():
        pytest.skip("system Python is unavailable")

    result = _run(REPO_ROOT, str(system_python), str(QUEUE_SCRIPT), "status")

    assert result.returncode == 0, result.stderr
    assert "validation-queue:" in result.stdout
