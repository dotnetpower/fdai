from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from scripts.automation import validation_queue
from scripts.automation.validation_queue_context import validation_environment
from scripts.automation.validation_queue_runner import _run_stage
from scripts.automation.validation_queue_support import queue_paths

pytestmark = pytest.mark.no_cover

REPO_ROOT = Path(__file__).resolve().parents[3]
QUEUE_SCRIPT = REPO_ROOT / "scripts" / "automation" / "validation_queue.py"
QUEUE_CONTEXT = REPO_ROOT / "scripts" / "automation" / "validation_queue_context.py"
QUEUE_EVIDENCE = REPO_ROOT / "scripts" / "automation" / "validation_queue_evidence.py"
QUEUE_RESUME = REPO_ROOT / "scripts" / "automation" / "validation_queue_resume.py"
QUEUE_RUNNER = REPO_ROOT / "scripts" / "automation" / "validation_queue_runner.py"
QUEUE_SUPPORT = REPO_ROOT / "scripts" / "automation" / "validation_queue_support.py"
POST_COMMIT_HOOK = REPO_ROOT / ".githooks" / "post-commit"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"
AUTO_PULL_SCRIPT = REPO_ROOT / "scripts" / "automation" / "git-auto-pull.sh"
VALIDATOR_AGENT = REPO_ROOT / ".github" / "agents" / "integration-validator.agent.md"


def test_validation_environment_uses_only_the_dedicated_validation_database(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example.invalid/runtime")
    monkeypatch.setenv("FDAI_VALIDATION_DATABASE_URL", "postgresql://example.invalid/validation")
    monkeypatch.delenv("FDAI_CHANGED_TEST_INTEGRATION", raising=False)

    environment = validation_environment(queue_paths(git_repo))

    assert environment["FDAI_DATABASE_URL"] == "postgresql://example.invalid/validation"
    assert environment["FDAI_CHANGED_TEST_INTEGRATION"] == "1"


def test_validation_environment_loads_database_from_source_checkout(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_env = git_repo / ".fdai" / "local-runtime.env"
    local_env.parent.mkdir()
    local_env.write_text(
        "FDAI_DATABASE_URL=postgresql://example.invalid/runtime\n"
        "FDAI_VALIDATION_DATABASE_URL=postgresql://example.invalid/validation\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FDAI_DATABASE_URL", raising=False)
    monkeypatch.delenv("FDAI_VALIDATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("FDAI_CHANGED_TEST_INTEGRATION", raising=False)
    paths = queue_paths(git_repo)
    paths.worktree.mkdir(parents=True)

    environment = validation_environment(paths)

    assert not (paths.worktree / ".fdai" / "local-runtime.env").exists()
    assert environment["FDAI_DATABASE_URL"] == "postgresql://example.invalid/validation"
    assert environment["FDAI_CHANGED_TEST_INTEGRATION"] == "1"


def _run(
    cwd: Path,
    *arguments: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = cwd / "bin"
    path = f"{bin_dir}:{os.environ['PATH']}" if bin_dir.is_dir() else os.environ["PATH"]
    return subprocess.run(  # noqa: S603 - test-controlled arguments and repository paths
        list(arguments),
        cwd=cwd,
        env={**os.environ, "PATH": path, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    for package_root in ("console", "cli"):
        modules = repo / package_root / "node_modules"
        modules.mkdir(parents=True)
        (modules / ".validation-marker").write_text("ready\n", encoding="utf-8")
    (repo / "bin" / "uv").write_text(
        "#!/usr/bin/env bash\n"
        'test "$1" = sync || exit 11\n'
        'test "$UV_PYTHON" = 3.13 || exit 12\n'
        'mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"\n'
        'touch "$UV_PROJECT_ENVIRONMENT/bin/python"\n'
        'if [[ -n "${FDAI_VALIDATION_TEST_LOG:-}" ]]; then\n'
        '  printf "uv:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n'
        "fi\n",
        encoding="utf-8",
    )
    (repo / "bin" / "uv").chmod(0o755)
    (repo / "bin" / "systemd-run").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ -n "${FDAI_VALIDATION_TEST_LOG:-}" ]]; then\n'
        '  printf "systemd:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n'
        "fi\n",
        encoding="utf-8",
    )
    (repo / "bin" / "systemd-run").chmod(0o755)
    (repo / "scripts" / "automation").mkdir(parents=True)
    for source in (
        QUEUE_SCRIPT,
        QUEUE_CONTEXT,
        QUEUE_EVIDENCE,
        QUEUE_RESUME,
        QUEUE_RUNNER,
        QUEUE_SUPPORT,
    ):
        shutil.copy2(source, repo / "scripts" / "automation" / source.name)
    (repo / "scripts" / "automation" / "tests-for-diff.sh").write_text(
        "#!/usr/bin/env bash\n"
        "test -f resolved-models.json || exit 9\n"
        'case "$UV_PROJECT_ENVIRONMENT" in */fdai-validation-queue/venv) ;; *) exit 10 ;; esac\n'
        'test "$UV_NO_SYNC" = 1 || exit 13\n'
        'printf "changed:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n'
        'if [[ "${FDAI_VALIDATION_CHANGED_TEST_FAIL:-0}" == 1 ]]; then\n'
        '  mkdir -p "$FDAI_CHANGED_TEST_CACHE_DIR/v/cache"\n'
        "  printf '{\"tests/test_example.py::test_failure\": true}\\n' > "
        '"$FDAI_CHANGED_TEST_CACHE_DIR/v/cache/lastfailed"\n'
        "  exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    (repo / "scripts" / "verify.sh").write_text(
        "#!/usr/bin/env bash\n"
        "test -f resolved-models.json || exit 9\n"
        "test -f console/node_modules/.validation-marker || exit 14\n"
        "test -f cli/node_modules/.validation-marker || exit 15\n"
        'case "$UV_PROJECT_ENVIRONMENT" in */fdai-validation-queue/venv) ;; *) exit 10 ;; esac\n'
        'test "$UV_NO_SYNC" = 1 || exit 13\n'
        'printf "verify:%s\\n" "$*" >> "$FDAI_VALIDATION_TEST_LOG"\n'
        '[[ "$(git rev-parse HEAD)" != "${FDAI_VALIDATION_VERIFY_FAIL_AT_HEAD:-}" ]] || exit 17\n'
        '[[ "${FDAI_VALIDATION_VERIFY_FAIL_WITH_MARKER:-0}" != 1 || ! -f broken.txt ]] || exit 17\n'
        '[[ "${FDAI_VALIDATION_VERIFY_FAIL:-0}" != 1 ]] || exit 17\n',
        encoding="utf-8",
    )
    (repo / "scripts" / "automation" / "run-pre-push-structural-gates.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text("resolved-models*.json\n", encoding="utf-8")
    (repo / "source.txt").write_text("initial\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_example.py").write_text(
        "def test_failure() -> None:\n    assert True\n",
        encoding="utf-8",
    )
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


def test_prune_stale_removes_only_old_unreferenced_pending_records(git_repo: Path) -> None:
    paths = queue_paths(git_repo)
    old = datetime.now(timezone.utc) - timedelta(hours=48)  # noqa: UP017
    retained = _commit_change(git_repo)
    orphan = _run(git_repo, "git", "commit-tree", "HEAD^{tree}", "-p", retained, "-m", "orphan")
    assert orphan.returncode == 0, orphan.stderr
    orphan_commit = orphan.stdout.strip()
    recent = _run(git_repo, "git", "commit-tree", "HEAD^{tree}", "-p", retained, "-m", "recent")
    assert recent.returncode == 0, recent.stderr
    recent_commit = recent.stdout.strip()
    validation_queue.initialize(paths)
    for commit, enqueued_at in (
        (retained, old),
        (orphan_commit, old),
        (recent_commit, datetime.now(timezone.utc)),  # noqa: UP017
    ):
        (paths.pending / f"{commit}.json").write_text(
            json.dumps(
                {
                    "commit": commit,
                    "enqueued_at": enqueued_at.isoformat(),
                    "schema_version": 1,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    assert validation_queue.prune_stale(paths, min_age_hours=24, apply=False) == 0
    assert (paths.pending / f"{orphan_commit}.json").is_file()

    assert validation_queue.prune_stale(paths, min_age_hours=24, apply=True) == 0
    assert (paths.pending / f"{retained}.json").is_file()
    assert not (paths.pending / f"{orphan_commit}.json").exists()
    assert (paths.state_root / "retired-pending" / f"{orphan_commit}.json").is_file()
    assert (paths.pending / f"{recent_commit}.json").is_file()


def test_prune_stale_preserves_old_pending_reachable_only_from_branch(git_repo: Path) -> None:
    paths = queue_paths(git_repo)
    old = datetime.now(timezone.utc) - timedelta(hours=48)  # noqa: UP017
    branch_commit = _run(
        git_repo,
        "git",
        "commit-tree",
        "HEAD^{tree}",
        "-p",
        "HEAD",
        "-m",
        "branch-only",
    )
    assert branch_commit.returncode == 0, branch_commit.stderr
    commit = branch_commit.stdout.strip()
    assert _run(git_repo, "git", "update-ref", "refs/heads/preserved", commit).returncode == 0
    validation_queue.initialize(paths)
    (paths.pending / f"{commit}.json").write_text(
        json.dumps(
            {
                "commit": commit,
                "enqueued_at": old.isoformat(),
                "schema_version": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert validation_queue.prune_stale(paths, min_age_hours=24, apply=True) == 0

    assert (paths.pending / f"{commit}.json").is_file()
    assert not (paths.state_root / "retired-pending" / f"{commit}.json").exists()


def test_run_stage_records_failed_verify_gate_detail(tmp_path: Path) -> None:
    result = _run_stage(
        "fast-gates",
        [
            sys.executable,
            "-c",
            "print('== summary =='); print('  derived-sources          FAIL'); raise SystemExit(1)",
        ],
        cwd=tmp_path,
        env=dict(os.environ),
    )

    assert result["status"] == 1
    assert result["detail"] == "derived-sources"


def test_drain_reloads_validator_code_when_wake_request_advances(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = SimpleNamespace(wake_lock=tmp_path / "wake.lock")
    requests = iter(("old-head", "new-head"))
    executed: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(validation_queue, "initialize", lambda _paths: None)
    monkeypatch.setattr(validation_queue, "_checkout_heads", lambda _paths: [])
    monkeypatch.setattr(validation_queue, "_wake_request", lambda _paths: next(requests))
    monkeypatch.setattr(
        validation_queue,
        "run",
        lambda _paths, _mode, *, wait_for_lock, target: 0,
    )
    monkeypatch.setattr(validation_queue.time, "sleep", lambda _seconds: None)

    def _record_exec(executable: str, arguments: list[str]) -> None:
        executed.append((executable, arguments))
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(validation_queue.os, "execv", _record_exec)

    with pytest.raises(RuntimeError, match="exec intercepted"):
        validation_queue.drain(paths)

    assert executed == [
        (
            sys.executable,
            [sys.executable, str(QUEUE_SCRIPT), "drain"],
        )
    ]


def test_drain_reloads_after_failure_when_wake_request_advances(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = SimpleNamespace(wake_lock=tmp_path / "wake.lock")
    requests = iter(("failed-head", "fixed-head"))

    monkeypatch.setattr(validation_queue, "initialize", lambda _paths: None)
    monkeypatch.setattr(validation_queue, "_checkout_heads", lambda _paths: [])
    monkeypatch.setattr(validation_queue, "_wake_request", lambda _paths: next(requests))
    monkeypatch.setattr(
        validation_queue,
        "run",
        lambda _paths, _mode, *, wait_for_lock, target: 1,
    )
    monkeypatch.setattr(validation_queue.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        validation_queue.os,
        "execv",
        lambda _executable, _arguments: (_ for _ in ()).throw(RuntimeError("exec intercepted")),
    )

    with pytest.raises(RuntimeError, match="exec intercepted"):
        validation_queue.drain(paths)


def test_drain_returns_failure_when_wake_request_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = SimpleNamespace(wake_lock=tmp_path / "wake.lock")

    monkeypatch.setattr(validation_queue, "initialize", lambda _paths: None)
    monkeypatch.setattr(validation_queue, "_checkout_heads", lambda _paths: [])
    monkeypatch.setattr(validation_queue, "_wake_request", lambda _paths: "failed-head")
    monkeypatch.setattr(
        validation_queue,
        "run",
        lambda _paths, _mode, *, wait_for_lock, target: 17,
    )
    monkeypatch.setattr(validation_queue.time, "sleep", lambda _seconds: None)

    assert validation_queue.drain(paths) == 17


def test_run_batches_pending_commits_and_records_receipts(git_repo: Path, tmp_path: Path) -> None:
    commit = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", "HEAD^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    revision_range = "HEAD^..HEAD"
    log_path = tmp_path / "validation.log"

    enqueued = _run(git_repo, "python3", str(script), "enqueue", commit)
    blocked = _run(git_repo, "python3", str(script), "check-range", revision_range)
    commit_blocked = _run(git_repo, "python3", str(script), "check-commit", commit)
    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )
    accepted = _run(git_repo, "python3", str(script), "check-range", revision_range)
    commit_accepted = _run(git_repo, "python3", str(script), "check-commit", commit)

    assert enqueued.returncode == 0, enqueued.stderr
    assert blocked.returncode == 1
    assert commit_blocked.returncode == 1
    assert validated.returncode == 0, validated.stderr
    assert accepted.returncode == 0, accepted.stderr
    assert commit_accepted.returncode == 0, commit_accepted.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        f"verify:--fast --diff {parent}..{commit}",
        f"changed:--run {parent}..{commit}",
    ]
    state_root = git_repo / ".git" / "fdai-validation-queue"
    receipt = json.loads((state_root / "receipts" / f"{commit}.json").read_text())
    assert receipt["duration_seconds"] >= 0
    assert [stage["name"] for stage in receipt["stages"]] == [
        "dependency-sync",
        "fast-gates",
        "structural-gates",
        "changed-tests",
    ]
    structural = receipt["stages"][2]
    assert structural["input_digest"]
    structural_accepted = _run(
        git_repo,
        "python3",
        str(script),
        "check-structural-gates",
        commit,
    )
    assert structural_accepted.returncode == 0, structural_accepted.stderr
    structural_runner = git_repo / "scripts" / "automation" / "run-pre-push-structural-gates.sh"
    structural_runner.write_text("#!/usr/bin/env bash\n# changed\n", encoding="utf-8")
    structural_stale = _run(
        git_repo,
        "python3",
        str(script),
        "check-structural-gates",
        commit,
    )
    assert structural_stale.returncode == 1
    assert (state_root / "worktree").is_dir()


def test_run_validates_every_reachable_pending_commit_in_one_snapshot(
    git_repo: Path, tmp_path: Path
) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "batched-validation.log"
    commits: list[str] = []
    for index in range(7):
        (git_repo / "source.txt").write_text(f"change {index}\n", encoding="utf-8")
        assert _run(git_repo, "git", "add", "source.txt").returncode == 0
        assert _run(git_repo, "git", "commit", "--quiet", "-m", f"change {index}").returncode == 0
        commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
        commits.append(commit)
        assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert validated.returncode == 0, validated.stderr
    state_root = git_repo / ".git" / "fdai-validation-queue"
    receipts = [
        json.loads((state_root / "receipts" / f"{commit}.json").read_text()) for commit in commits
    ]
    assert {receipt["validated_head"] for receipt in receipts} == {commits[-1]}
    assert not any((state_root / "pending" / f"{commit}.json").exists() for commit in commits)
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len([line for line in log_lines if line.startswith("verify:")]) == 1


def test_failed_batch_receipts_its_longest_passing_prefix(git_repo: Path, tmp_path: Path) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "localized-validation.log"
    docs_path = git_repo / "docs/guide.md"
    docs_path.parent.mkdir()
    docs_path.write_text("# Guide\n", encoding="utf-8")
    (git_repo / "broken.txt").write_text("broken\n", encoding="utf-8")
    staged = (
        ("docs", str(docs_path)),
        ("source", "source.txt"),
        ("broken", "broken.txt"),
        ("later", "source.txt"),
    )
    commits: list[str] = []
    for message, path in staged:
        (git_repo / "source.txt").write_text(f"{message}\n", encoding="utf-8")
        assert _run(git_repo, "git", "add", path).returncode == 0
        assert _run(git_repo, "git", "commit", "--quiet", "-m", message).returncode == 0
        commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
        commits.append(commit)
        assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_VERIFY_FAIL_WITH_MARKER": "1",
        },
    )

    assert validated.returncode != 0
    state_root = git_repo / ".git" / "fdai-validation-queue"
    passing_receipts = [
        json.loads((state_root / "receipts" / f"{commit}.json").read_text())
        for commit in commits[:2]
    ]
    assert {receipt["validated_head"] for receipt in passing_receipts} == {commits[1]}
    assert all((state_root / "pending" / f"{commit}.json").exists() for commit in commits[2:])
    assert f"first failing pending commit is {commits[2][:12]}" in validated.stdout


def test_full_validation_keeps_one_snapshot_for_all_pending_commits(
    git_repo: Path, tmp_path: Path
) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "full-validation.log"
    commits: list[str] = []
    for index in range(6):
        (git_repo / "source.txt").write_text(f"full {index}\n", encoding="utf-8")
        assert _run(git_repo, "git", "add", "source.txt").returncode == 0
        assert _run(git_repo, "git", "commit", "--quiet", "-m", f"full {index}").returncode == 0
        commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
        commits.append(commit)
        assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        "--all",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert validated.returncode == 0, validated.stderr
    state_root = git_repo / ".git" / "fdai-validation-queue"
    validated_heads = {
        json.loads((state_root / "receipts" / f"{commit}.json").read_text())["validated_head"]
        for commit in commits
    }
    assert validated_heads == {commits[-1]}


def test_a_pending_fix_validates_its_broken_ancestor_in_one_snapshot(
    git_repo: Path, tmp_path: Path
) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "fixed-validation.log"
    commits: list[str] = []
    for index in range(6):
        (git_repo / "source.txt").write_text(f"expanded {index}\n", encoding="utf-8")
        assert _run(git_repo, "git", "add", "source.txt").returncode == 0
        assert _run(git_repo, "git", "commit", "--quiet", "-m", f"expanded {index}").returncode == 0
        commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
        commits.append(commit)
        assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    validated = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_VERIFY_FAIL_AT_HEAD": commits[4],
        },
    )

    assert validated.returncode == 0, validated.stderr
    state_root = git_repo / ".git" / "fdai-validation-queue"
    first_receipt = json.loads((state_root / "receipts" / f"{commits[0]}.json").read_text())
    assert first_receipt["validated_head"] == commits[5]
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len([line for line in log_lines if line.startswith("verify:")]) == 1


def test_linked_worktree_uses_the_shared_git_queue(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    assert (
        _run(git_repo, "git", "worktree", "add", "--quiet", "--detach", str(linked)).returncode == 0
    )
    script = linked / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "linked-validation.log"

    enqueued = _run(linked, "python3", str(script), "enqueue", "HEAD")
    status = _run(git_repo, "python3", str(script), "status")
    validated = _run(
        linked,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert enqueued.returncode == 0, enqueued.stderr
    assert status.returncode == 0, status.stderr
    assert "1 reachable pending commit(s), 0 elsewhere" in status.stdout
    assert validated.returncode == 0, validated.stderr
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    verify_index = next(index for index, line in enumerate(log_lines) if line.startswith("verify:"))
    changed_index = next(
        index for index, line in enumerate(log_lines) if line.startswith("changed:")
    )
    assert verify_index < changed_index


def test_linked_worktree_drain_validates_the_shared_requested_head(
    git_repo: Path, tmp_path: Path
) -> None:
    linked = tmp_path / "linked-drain"
    assert (
        _run(git_repo, "git", "worktree", "add", "--quiet", "--detach", str(linked)).returncode == 0
    )
    requested = _commit_change(git_repo)
    script = linked / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "linked-drain-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", requested).returncode == 0
    paths = queue_paths(linked)
    paths.wake_request.write_text(requested + "\n", encoding="utf-8")

    drained = _run(
        linked,
        "python3",
        str(script),
        "drain",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert drained.returncode == 0, drained.stderr
    receipt = json.loads((paths.receipts / f"{requested}.json").read_text())
    assert receipt["validated_head"] == requested
    assert _run(linked, "git", "rev-parse", "HEAD").stdout.strip() != requested


def test_drain_serves_every_checkout_so_a_branch_cannot_starve_main(
    git_repo: Path, tmp_path: Path
) -> None:
    branch = tmp_path / "branch-lane"
    assert (
        _run(git_repo, "git", "worktree", "add", "--quiet", "-b", "lane", str(branch)).returncode
        == 0
    )
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "lane-validation.log"
    main_commit = _commit_change(git_repo)
    (branch / "source.txt").write_text("branch work\n", encoding="utf-8")
    assert _run(branch, "git", "add", "source.txt").returncode == 0
    assert _run(branch, "git", "commit", "--quiet", "-m", "branch work").returncode == 0
    branch_commit = _run(branch, "git", "rev-parse", "HEAD").stdout.strip()
    for cwd, commit in ((git_repo, main_commit), (branch, branch_commit)):
        assert _run(cwd, "python3", str(script), "enqueue", commit).returncode == 0
    paths = queue_paths(git_repo)
    paths.wake_request.write_text(branch_commit + "\n", encoding="utf-8")

    drained = _run(
        branch,
        "python3",
        str(script),
        "drain",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert drained.returncode == 0, drained.stderr
    assert (paths.receipts / f"{branch_commit}.json").is_file()
    assert (paths.receipts / f"{main_commit}.json").is_file(), (
        "the main checkout must still be validated when a branch owns the wake request"
    )


def test_retry_reuses_sync_and_passed_fast_gates(git_repo: Path, tmp_path: Path) -> None:
    commit = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", "HEAD^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "retry-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    failed = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_CHANGED_TEST_FAIL": "1",
        },
    )
    retried = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert failed.returncode == 1
    assert retried.returncode == 0, retried.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        f"verify:--fast --diff {parent}..{commit}",
        f"changed:--run {parent}..{commit}",
        f"changed:--run {parent}..{commit}",
    ]


def test_fix_commit_resumes_failed_and_delta_changed_tests(git_repo: Path, tmp_path: Path) -> None:
    failed_head = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", f"{failed_head}^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "resume-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", failed_head).returncode == 0

    failed = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_CHANGED_TEST_FAIL": "1",
        },
    )
    (git_repo / "source.txt").write_text("fixed\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "fix").returncode == 0
    fixed_head = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(git_repo, "python3", str(script), "enqueue", fixed_head).returncode == 0

    resumed = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert failed.returncode == 1
    assert resumed.returncode == 0, resumed.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        f"verify:--fast --diff {parent}..{failed_head}",
        f"changed:--run {parent}..{failed_head}",
        f"verify:--fast --diff {parent}..{fixed_head}",
        "changed:--run --include-test tests/test_example.py::test_failure "
        f"{failed_head}..{fixed_head}",
    ]
    state_root = git_repo / ".git" / "fdai-validation-queue"
    receipt = json.loads((state_root / "receipts" / f"{fixed_head}.json").read_text())
    changed_stage = next(stage for stage in receipt["stages"] if stage["name"] == "changed-tests")
    assert changed_stage["resumed_from"] == failed_head
    assert changed_stage["resumed_failures"] == 1


def test_fix_commit_restarts_full_changed_tests_when_resume_control_changes(
    git_repo: Path, tmp_path: Path
) -> None:
    failed_head = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", f"{failed_head}^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "control-change-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", failed_head).returncode == 0
    failed = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_CHANGED_TEST_FAIL": "1",
        },
    )

    selector = git_repo / "scripts" / "automation" / "tests-for-diff.sh"
    selector.write_text(selector.read_text(encoding="utf-8") + "# fixed\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", str(selector)).returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "fix selector").returncode == 0
    fixed_head = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(git_repo, "python3", str(script), "enqueue", fixed_head).returncode == 0

    restarted = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert failed.returncode == 1
    assert restarted.returncode == 0, restarted.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        f"verify:--fast --diff {parent}..{failed_head}",
        f"changed:--run {parent}..{failed_head}",
        f"verify:--fast --diff {parent}..{fixed_head}",
        f"changed:--run {parent}..{fixed_head}",
    ]


def test_local_model_change_invalidates_passed_stage_cache(git_repo: Path, tmp_path: Path) -> None:
    commit = _commit_change(git_repo)
    parent = _run(git_repo, "git", "rev-parse", "HEAD^").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "local-input-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    failed = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={
            "FDAI_VALIDATION_TEST_LOG": str(log_path),
            "FDAI_VALIDATION_VERIFY_FAIL": "1",
        },
    )
    (git_repo / "resolved-models.json").write_text(
        '{"capabilities": {"narrator": {}}}\n', encoding="utf-8"
    )
    retried = _run(
        git_repo,
        "python3",
        str(script),
        "run",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )

    assert failed.returncode == 17
    assert retried.returncode == 0, retried.stderr
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        f"verify:--fast --diff {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
        f"changed:--run {parent}..{commit}",
    ]


def test_status_separates_reachable_and_elsewhere_pending(git_repo: Path) -> None:
    elsewhere = _commit_change(git_repo)
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    assert _run(git_repo, "python3", str(script), "enqueue", elsewhere).returncode == 0
    assert _run(git_repo, "git", "reset", "--hard", "HEAD^").returncode == 0
    (git_repo / "source.txt").write_text("reachable\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "reachable").returncode == 0
    reachable = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(git_repo, "python3", str(script), "enqueue", reachable).returncode == 0

    status = _run(git_repo, "python3", str(script), "status")
    verbose = _run(git_repo, "python3", str(script), "status", "--all")

    assert status.returncode == 0
    assert "1 reachable pending commit(s), 1 elsewhere" in status.stdout
    assert reachable in status.stdout
    assert elsewhere not in status.stdout
    assert f"{elsewhere} (elsewhere)" in verbose.stdout


def test_status_and_commit_check_report_an_active_validator(git_repo: Path) -> None:
    import fcntl

    commit = _commit_change(git_repo)
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0
    lock_path = git_repo / ".git" / "fdai-validation-queue" / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        status = _run(git_repo, "python3", str(script), "status")
        blocked = _run(git_repo, "python3", str(script), "check-commit", commit)

    assert status.returncode == 0
    assert "validator active" in status.stdout
    assert blocked.returncode == 1
    assert "Background validation is active; push does not wait for it." in blocked.stderr


def test_status_and_commit_check_report_the_last_failed_stage(git_repo: Path) -> None:
    commit = _commit_change(git_repo)
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0
    runs = git_repo / ".git" / "fdai-validation-queue" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{commit}.json").write_text(
        json.dumps(
            {
                "status": 1,
                "stages": [
                    {"name": "dependency-sync", "status": 0},
                    {"name": "fast-gates", "status": 1, "detail": "derived-sources"},
                ],
            }
        ),
        encoding="utf-8",
    )

    status = _run(git_repo, "python3", str(script), "status")
    blocked = _run(git_repo, "python3", str(script), "check-commit", commit)

    assert status.returncode == 0
    assert "validator failed at fast-gates/derived-sources" in status.stdout
    assert blocked.returncode == 1
    assert "Last background validation failed at fast-gates/derived-sources." in blocked.stderr


def test_status_reports_a_failed_earlier_pending_cohort(git_repo: Path) -> None:
    failed_commit = _commit_change(git_repo)
    (git_repo / "source.txt").write_text("later change\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "later change").returncode == 0
    later_commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    for commit in (failed_commit, later_commit):
        assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0
    runs = git_repo / ".git" / "fdai-validation-queue" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{failed_commit}.json").write_text(
        json.dumps(
            {
                "status": 1,
                "stages": [
                    {"name": "structural-gates", "status": 1, "detail": None},
                ],
            }
        ),
        encoding="utf-8",
    )

    status = _run(git_repo, "python3", str(script), "status")
    blocked = _run(git_repo, "python3", str(script), "check-commit", later_commit)

    assert "validator failed at structural-gates" in status.stdout
    assert (
        f"Last background validation failed at structural-gates on {failed_commit[:12]}."
        in blocked.stderr
    )


def test_external_readiness_allows_in_flight_commits_on_a_validated_line(
    git_repo: Path,
) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    validated = _commit_change(git_repo)
    assert _run(git_repo, "python3", str(script), "enqueue", validated).returncode == 0
    assert _run(git_repo, "python3", str(script), "run").returncode == 0
    (git_repo / "source.txt").write_text("in flight\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "in flight").returncode == 0
    in_flight = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(git_repo, "python3", str(script), "enqueue", in_flight).returncode == 0

    blocked = _run(git_repo, "python3", str(script), "check-commit", "HEAD")
    ready = _run(git_repo, "python3", str(script), "check-external-readiness", "HEAD")

    assert blocked.returncode == 1
    assert ready.returncode == 0, ready.stderr
    assert f"line validated through {validated[:12]}" in ready.stdout


def test_external_readiness_blocks_a_line_with_a_failed_validation(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    validated = _commit_change(git_repo)
    assert _run(git_repo, "python3", str(script), "enqueue", validated).returncode == 0
    assert _run(git_repo, "python3", str(script), "run").returncode == 0
    (git_repo / "source.txt").write_text("broken\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    assert _run(git_repo, "git", "commit", "--quiet", "-m", "broken").returncode == 0
    broken = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    assert _run(git_repo, "python3", str(script), "enqueue", broken).returncode == 0
    assert (
        _run(
            git_repo,
            "python3",
            str(script),
            "run",
            env={"FDAI_VALIDATION_VERIFY_FAIL": "1"},
        ).returncode
        != 0
    )

    ready = _run(git_repo, "python3", str(script), "check-external-readiness", "HEAD")

    assert ready.returncode == 1
    assert "validation failed at" in ready.stderr


def test_external_readiness_blocks_a_line_that_was_never_validated(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    commit = _commit_change(git_repo)
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0

    ready = _run(git_repo, "python3", str(script), "check-external-readiness", "HEAD")

    assert ready.returncode == 1
    assert "no validated commit yet" in ready.stderr


def test_concurrent_enqueue_of_same_commit_is_atomic(git_repo: Path) -> None:
    script = git_repo / "scripts" / "automation" / "validation_queue.py"

    def enqueue() -> subprocess.CompletedProcess[str]:
        return _run(git_repo, "python3", str(script), "enqueue", "HEAD")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: enqueue(), range(16)))

    assert all(result.returncode == 0 for result in results)
    status = _run(git_repo, "python3", str(script), "status")
    assert "1 reachable pending commit(s), 0 elsewhere" in status.stdout


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
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "uv:sync --frozen --extra dev --extra azure-mcp --python 3.13",
        "verify:--all",
    ]


def test_post_commit_hook_enqueues_and_wakes_background_validation(
    git_repo: Path, tmp_path: Path
) -> None:
    hooks = git_repo / ".githooks"
    hooks.mkdir()
    shutil.copy2(POST_COMMIT_HOOK, hooks / "post-commit")
    (hooks / "post-commit").chmod(0o755)
    assert _run(git_repo, "git", "config", "core.hooksPath", ".githooks").returncode == 0

    log_path = tmp_path / "background-wake.log"
    (git_repo / "source.txt").write_text("changed\n", encoding="utf-8")
    assert _run(git_repo, "git", "add", "source.txt").returncode == 0
    committed = _run(
        git_repo,
        "git",
        "commit",
        "--quiet",
        "-m",
        "change",
        env={"FDAI_VALIDATION_TEST_LOG": str(log_path)},
    )
    assert committed.returncode == 0, committed.stderr
    commit = _run(git_repo, "git", "rev-parse", "HEAD").stdout.strip()
    common_dir = Path(_run(git_repo, "git", "rev-parse", "--git-common-dir").stdout.strip())

    assert (
        git_repo / common_dir / "fdai-validation-queue" / "pending" / f"{commit}.json"
    ).is_file()
    wake = log_path.read_text(encoding="utf-8")
    assert "systemd:--user --quiet --collect" in wake
    assert "--property=Nice=15" in wake
    assert "--property=CPUWeight=10" in wake
    assert "--property=CPUQuota=180%" in wake
    assert "--property=IOWeight=10" in wake
    assert "--property=MemoryHigh=8G" in wake
    assert f"--working-directory={git_repo}" in wake
    assert "--unit=fdai-validation-" in wake
    assert "drain" in wake
    assert "run --wait" not in wake


def test_wait_mode_blocks_until_the_active_validator_releases_lock(
    git_repo: Path, tmp_path: Path
) -> None:
    import fcntl

    commit = _commit_change(git_repo)
    script = git_repo / "scripts" / "automation" / "validation_queue.py"
    log_path = tmp_path / "wait-validation.log"
    assert _run(git_repo, "python3", str(script), "enqueue", commit).returncode == 0
    lock_path = git_repo / ".git" / "fdai-validation-queue" / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        process = subprocess.Popen(  # noqa: S603 - test-controlled command and paths.
            [str(Path(sys.executable).resolve()), str(script), "run", "--wait"],
            cwd=git_repo,
            env={
                **os.environ,
                "PATH": f"{git_repo / 'bin'}:{os.environ['PATH']}",
                "FDAI_VALIDATION_TEST_LOG": str(log_path),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.1)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, f"{stdout}\n{stderr}"
    assert "verify:--fast --diff" in log_path.read_text(encoding="utf-8")


def test_pre_push_requires_central_validation_receipts() -> None:
    hook = PRE_PUSH_HOOK.read_text(encoding="utf-8")
    structural_runner = (
        REPO_ROOT / "scripts" / "automation" / "run-pre-push-structural-gates.sh"
    ).read_text(encoding="utf-8")

    ensure_offset = hook.index('ensure-range "$range"')
    check_offset = hook.index('check-range "$range"')
    evidence_offset = hook.index("exact centralized validation and structural evidence reused")
    worktree_offset = hook.index("git worktree add")

    assert ensure_offset < check_offset < evidence_offset < worktree_offset
    assert "git fetch" not in hook
    assert "while IFS=' ' read -r candidate_local_ref" in hook
    assert 'git merge-base --is-ancestor "$remote_sha" "$local_sha"' in hook
    assert "if [[ $structural_evidence -eq 1 ]]" in hook
    assert 'gate_command=(uv run python "$gate_path")' in structural_runner
    assert 'gate_command=(python3 "$gate_path")' not in structural_runner


def test_pre_push_hook_has_valid_shell_syntax() -> None:
    checked = _run(REPO_ROOT, "bash", "-n", str(PRE_PUSH_HOOK))

    assert checked.returncode == 0, checked.stderr


def test_auto_pull_checks_local_blockers_before_fetching() -> None:
    script = AUTO_PULL_SCRIPT.read_text(encoding="utf-8")

    status_offset = script.index("git status --porcelain")
    validation_offset = script.index("centralized validation is active")
    fetch_offset = script.index("git fetch --quiet")

    assert status_offset < fetch_offset
    assert validation_offset < fetch_offset
    assert 'flock -n "$validation_lock" -c true' in script
    checked = _run(REPO_ROOT, "bash", "-n", str(AUTO_PULL_SCRIPT))
    assert checked.returncode == 0, checked.stderr


def test_validator_agent_is_read_execute_only_and_uses_make_facade() -> None:
    _prefix, frontmatter, body = VALIDATOR_AGENT.read_text(encoding="utf-8").split("---", 2)
    config = yaml.safe_load(frontmatter)
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert config["name"] == "Integration Validator"
    assert config["tools"] == ["read", "execute"]
    assert config["agents"] == []
    assert config["user-invocable"] is True
    assert "Post-commit normally wakes a low-priority background validator" in body
    assert "one newest-first snapshot" in body
    assert "bisects the pending list" in body
    assert "longest passing prefix" in body
    assert "first failing pending commit" in body
    assert "Intermediate stage success is progress metadata" in body
    assert "not a push receipt" in body
    assert "shared wake request" in body
    assert "process worktree never selects the validation branch" in body
    assert "make validation-status" in body
    assert "make validation-run" in body
    assert "do not wait" in body
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
