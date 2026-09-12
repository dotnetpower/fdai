"""Local receipts never certify another tree, dirty inputs, or failed checks."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from scripts.automation import local_validation_cache as cache
from scripts.automation import local_validation_inputs as inputs
from scripts.automation.validation_queue_context import load_stage_cache, write_stage_cache
from scripts.automation.validation_queue_evidence import (
    STRUCTURAL_GATE_INPUTS,
    structural_gate_digest,
)

pytestmark = pytest.mark.no_cover


def _git(root: Path, *arguments: str) -> str:
    return inputs.git(root, *arguments).decode().strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "user.name", "Example User")
    _git(root, "config", "user.email", "user@example.com")
    (root / "source.py").write_text("value = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'example'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "--quiet", "-m", "initial")
    return root


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "invalid",
        {"success": True},
        {"schema_version": True},
        {
            "schema_version": 1,
            "scope": "local-structural",
            "context": "expected",
            "success": True,
            "completed_at": float("nan"),
        },
    ],
)
def test_invalid_receipts_are_misses(tmp_path: Path, value: object) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert not cache.cache_hit(receipt, "expected", now=100.0)


def test_receipt_requires_exact_context_success_and_bounded_age(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    record = {
        "schema_version": 1,
        "scope": "local-structural",
        "context": "expected",
        "success": True,
        "completed_at": 100.0,
    }
    assert cache.write_record(receipt, record)
    assert cache.cache_hit(receipt, "expected", now=101.0)
    assert not cache.cache_hit(receipt, "changed", now=101.0)
    assert not cache.cache_hit(receipt, "expected", now=99.0)
    assert not cache.cache_hit(receipt, "expected", now=100.0 + cache.MAX_AGE_SECONDS + 1)
    record["success"] = False
    assert cache.write_record(receipt, record)
    assert not cache.cache_hit(receipt, "expected", now=101.0)
    receipt.write_bytes(b"\xff")
    assert not cache.cache_hit(receipt, "expected", now=101.0)


def test_same_content_new_commit_preserves_identity(repository: Path) -> None:
    before = inputs.tracked_snapshot(repository)
    original_head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "commit", "--allow-empty", "--quiet", "-m", "metadata only")
    assert _git(repository, "rev-parse", "HEAD") != original_head
    assert inputs.tracked_snapshot(repository) == before


@pytest.mark.parametrize(
    "path",
    [
        "source.py",
        "pyproject.toml",
        "uv.lock",
        "scripts/quality/architecture/check-venue-capability-contract.py",
        "scripts/lib/design-routes.json",
    ],
)
def test_content_checker_config_dependency_changes_invalidate_tree(
    repository: Path,
    path: str,
) -> None:
    before, _ = inputs.tracked_snapshot(repository)
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")
    _git(repository, "add", path)
    _git(repository, "commit", "--quiet", "-m", "input change")
    after, _ = inputs.tracked_snapshot(repository)
    assert after != before


def test_dirty_bytes_cannot_poison_committed_identity(repository: Path) -> None:
    _git(repository, "update-index", "--assume-unchanged", "source.py")
    (repository / "source.py").write_text("value = 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bytes differ"):
        inputs.tracked_snapshot(repository)


def test_snapshot_refuses_missing_and_external_inputs(repository: Path) -> None:
    (repository / "source.py").unlink()
    with pytest.raises(OSError):
        inputs.tracked_snapshot(repository)
    (repository / "source.py").symlink_to(repository.parent / "external.py")
    with pytest.raises(ValueError, match="external input"):
        inputs.tracked_snapshot(repository)


def test_scratch_isolation_preserves_dirty_parent(repository: Path) -> None:
    state = repository / ".git" / "structural-state"
    state.mkdir()
    head = _git(repository, "rev-parse", "HEAD")
    (repository / "source.py").write_text("dirty parent\n", encoding="utf-8")
    worktree = cache.prepare_worktree(repository, state, head)
    assert (worktree / "source.py").read_text(encoding="utf-8") == "value = 1\n"
    assert (repository / "source.py").read_text(encoding="utf-8") == "dirty parent\n"
    assert inputs.tracked_snapshot(worktree)


def test_environment_identity_verifies_installed_content(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_bytes(b"interpreter")
    package = venv / "package.py"
    package.write_bytes(b"original")
    before = inputs.installed_digest(venv)
    package.write_bytes(b"modified")
    assert inputs.installed_digest(venv) != before
    package.unlink()
    assert inputs.installed_digest(venv) != before


def test_installed_directory_cannot_hide_external_inputs(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin/python").write_bytes(b"interpreter")
    external = tmp_path / "external"
    external.mkdir()
    (venv / "hidden-package").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="directory escapes"):
        inputs.installed_digest(venv)


def test_runner_digest_includes_venue_and_helpers(repository: Path) -> None:
    assert (
        "scripts/quality/architecture/check-venue-capability-contract.py" in STRUCTURAL_GATE_INPUTS
    )
    assert "scripts/automation/local_validation_inputs.py" in STRUCTURAL_GATE_INPUTS
    before = structural_gate_digest(repository)
    (repository / "source.py").write_text("changed source\n", encoding="utf-8")
    assert structural_gate_digest(repository) != before


def test_dependency_identity_covers_workspace_configuration() -> None:
    files = {"pyproject.toml": "root", "uv.lock": "lock", "packages/example/pyproject.toml": "old"}
    before = inputs.dependency_digest(files)
    files["packages/example/pyproject.toml"] = "new"
    assert inputs.dependency_digest(files) != before
    del files["uv.lock"]
    with pytest.raises(ValueError, match="missing"):
        inputs.dependency_digest(files)


def test_unwritable_cache_is_optional(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    assert not cache.write_record(blocked / "receipt.json", {"success": True})


def test_dependency_sync_is_reused_only_with_verified_installed_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    calls: list[list[str]] = []

    def sync(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        binary = state / "venv" / "bin" / "python"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"verified interpreter")
        (state / "venv" / "package.py").write_bytes(b"verified dependency")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(cache.subprocess, "run", sync)
    first = cache.prepare_environment(tmp_path, state, {}, "dependency", "tools")
    assert cache.prepare_environment(tmp_path, state, {}, "dependency", "tools") == first
    assert len(calls) == 1
    (state / "venv" / "package.py").write_bytes(b"modified dependency")
    assert cache.prepare_environment(tmp_path, state, {}, "dependency", "tools") == first
    assert len(calls) == 2
    cache.prepare_environment(tmp_path, state, {}, "changed-lock", "tools")
    assert len(calls) == 3
    assert "--frozen" in calls[0]
    assert "--no-install-workspace" in calls[0]


@pytest.mark.parametrize("value", [None, [], "not an object"])
def test_queue_retry_cache_rejects_non_objects(tmp_path: Path, value: object) -> None:
    path = tmp_path / "queue.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_stage_cache(path, {}) == set()


def test_queue_retry_cache_write_failure_does_not_erase_pass(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    write_stage_cache(blocked / "receipt.json", {}, {"fast-gates"})


def test_structural_reuse_and_failed_execution(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = repository / ".git" / "cache"
    state.mkdir()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    calls: list[list[str]] = []
    result = 0

    @contextmanager
    def lock(_root: Path) -> Iterator[Path]:
        yield state

    real_run = subprocess.run

    def execute(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if arguments[0] == "git":
            return real_run(arguments, **_kwargs)
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, result)

    monkeypatch.setattr(cache, "locked_state", lock)
    monkeypatch.setattr(cache, "prepare_worktree", lambda *_args: repository)
    monkeypatch.setattr(cache, "execution_environment", lambda _state: ({}, "tools"))
    monkeypatch.setattr(cache, "prepare_environment", lambda *_args: "installed")
    monkeypatch.setattr(cache, "installed_digest", lambda _path: "installed")
    monkeypatch.setattr(cache.subprocess, "run", execute)
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert calls == [["gate"]]
    receipt = next((state / "receipts").glob("*.json"))
    receipt.write_text("[]", encoding="utf-8")
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert calls == [["gate"], ["gate"]]
    _git(repository, "commit", "--allow-empty", "--quiet", "-m", "metadata")
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert calls == [["gate"], ["gate"]]
    (repository / "source.py").write_text("changed\n", encoding="utf-8")
    _git(repository, "add", "source.py")
    _git(repository, "commit", "--quiet", "-m", "changed")
    result = 1
    assert cache.run(repository, ["gate"], structural=True) == 1
    assert cache.run(repository, ["gate"], structural=True) == 1
    assert calls == [["gate"], ["gate"], ["gate"], ["gate"]]
    # Deliberately no receipt can convert either failed execution into a hit.
    assert len(list((state / "receipts").glob("*.json"))) == 1
    result = 0
    monkeypatch.setattr(cache, "write_record", lambda *_args: False)
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert len(calls) == 6
    monkeypatch.setattr(cache, "write_record", lambda *_args: True)
    monkeypatch.setenv("CI", "true")
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert cache.run(repository, ["gate"], structural=True) == 0
    assert len(calls) == 8


def test_controlled_environment_drops_caller_python_and_queue_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "tool"
    executable.write_bytes(b"tool")
    monkeypatch.setattr(inputs.shutil, "which", lambda _name, **_kwargs: str(executable))
    monkeypatch.setenv("PYTHONPATH", "/unrelated/dirty/checkout")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/unrelated/environment")
    monkeypatch.setenv("FDAI_DATABASE_URL", "postgresql://example.invalid/database")
    monkeypatch.setenv("FILE_LOC_MODE", "warn")
    environment, before = inputs.execution_environment(tmp_path)
    assert "PYTHONPATH" not in environment
    assert "FDAI_DATABASE_URL" not in environment
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "venv")
    monkeypatch.setenv("FILE_LOC_MODE", "enforce")
    assert inputs.execution_environment(tmp_path)[1] != before
    executable.write_bytes(b"changed tool")
    assert inputs.execution_environment(tmp_path)[1] != before
