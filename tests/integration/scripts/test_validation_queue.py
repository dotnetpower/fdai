from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_cover

REPO_ROOT = Path(__file__).resolve().parents[3]
QUEUE_SCRIPT = REPO_ROOT / "scripts" / "automation" / "validation_queue.py"
QUEUE_CONTEXT = REPO_ROOT / "scripts" / "automation" / "validation_queue_context.py"
QUEUE_RESUME = REPO_ROOT / "scripts" / "automation" / "validation_queue_resume.py"
QUEUE_RUNNER = REPO_ROOT / "scripts" / "automation" / "validation_queue_runner.py"
QUEUE_SUPPORT = REPO_ROOT / "scripts" / "automation" / "validation_queue_support.py"
POST_COMMIT_HOOK = REPO_ROOT / ".githooks" / "post-commit"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"
VALIDATOR_AGENT = REPO_ROOT / ".github" / "agents" / "integration-validator.agent.md"


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
    (repo / "scripts" / "automation").mkdir(parents=True)
    for source in (QUEUE_SCRIPT, QUEUE_CONTEXT, QUEUE_RESUME, QUEUE_RUNNER, QUEUE_SUPPORT):
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
        '[[ "${FDAI_VALIDATION_VERIFY_FAIL:-0}" != 1 ]] || exit 17\n',
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
        f"changed:--run {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
    ]
    state_root = git_repo / ".git" / "fdai-validation-queue"
    receipt = json.loads((state_root / "receipts" / f"{commit}.json").read_text())
    assert receipt["duration_seconds"] >= 0
    assert [stage["name"] for stage in receipt["stages"]] == [
        "dependency-sync",
        "changed-tests",
        "fast-gates",
    ]
    assert (state_root / "worktree").is_dir()


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
    assert log_path.read_text(encoding="utf-8").splitlines()[-1].startswith("verify:--fast --diff ")


def test_retry_reuses_sync_and_passed_changed_tests(git_repo: Path, tmp_path: Path) -> None:
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
            "FDAI_VALIDATION_VERIFY_FAIL": "1",
        },
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
        f"changed:--run {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
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
        f"changed:--run {parent}..{failed_head}",
        "changed:--run --include-test tests/test_example.py::test_failure "
        f"{failed_head}..{fixed_head}",
        f"verify:--fast --diff {parent}..{fixed_head}",
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
        f"changed:--run {parent}..{failed_head}",
        f"changed:--run {parent}..{fixed_head}",
        f"verify:--fast --diff {parent}..{fixed_head}",
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
        f"changed:--run {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
        f"changed:--run {parent}..{commit}",
        f"verify:--fast --diff {parent}..{commit}",
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
    assert 'gate_command=(uv run python "$gate_path")' in hook
    assert 'gate_command=(python3 "$gate_path")' not in hook


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
