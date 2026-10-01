"""Regression tests for parallel changed-test shard isolation."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "automation" / "run-changed-test-shards.py"


@pytest.fixture(scope="module")
def shard_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_changed_test_shards", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parallel_shard_uses_clean_isolated_basetemp(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    basetemp = shard_runner._shard_basetemp(cache_root, 2)
    stale = basetemp / "stale"
    stale.mkdir(parents=True)
    observed: list[str] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        observed.extend(argv)
        assert not stale.exists()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shard_runner.subprocess, "run", run)

    result, output = shard_runner._run_shard(
        index=2,
        count=2,
        tests=["tests/example.py"],
        cache_root=cache_root,
        result_root=tmp_path / "results",
        environment={"PYTHONPATH": ""},
    )

    assert result.status == 0
    assert output == ""
    assert f"--basetemp={basetemp}" in observed


def _write_minimal_changed_test_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "example"\n', encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_example.py").write_text(
        "from src.example import VALUE\n\ndef test_example():\n    assert VALUE == 1\n",
        encoding="utf-8",
    )
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init"], cwd=root, check=True, capture_output=True)  # noqa: S603
    subprocess.run([git, "add", "."], cwd=root, check=True, capture_output=True)  # noqa: S603


def _patch_shard_run(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[str]]:
    calls: list[list[str]] = []
    real_run = subprocess.run

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[:1] == ["git"]:
            return real_run(argv, **kwargs)
        del kwargs
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shard_runner.subprocess, "run", run)
    monkeypatch.setattr(shard_runner, "installed_digest", lambda path: f"installed:{path.name}")
    return calls


def _run_identity_checked_shard(
    shard_runner: ModuleType,
    *,
    root: Path,
    cache_root: Path,
    result_root: Path,
) -> tuple[object, str]:
    tests = ["tests/test_example.py"]
    workspace_identity = shard_runner._workspace_identity(root, tests)
    return shard_runner._run_shard(
        index=1,
        count=1,
        tests=tests,
        cache_root=cache_root,
        result_root=result_root,
        environment={"PYTHONPATH": ""},
        workspace_identity=workspace_identity,
    )


def test_changed_source_file_invalidates_shard_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_minimal_changed_test_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _patch_shard_run(shard_runner, monkeypatch)
    cache_root = tmp_path / "cache"
    result_root = tmp_path / "results"

    _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )
    (tmp_path / "src" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    result, _ = _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )

    assert len(calls) == 2
    assert result.cached is False


def test_changed_lock_file_invalidates_shard_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_minimal_changed_test_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _patch_shard_run(shard_runner, monkeypatch)
    cache_root = tmp_path / "cache"
    result_root = tmp_path / "results"

    _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )
    (tmp_path / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    result, _ = _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )

    assert len(calls) == 2
    assert result.cached is False


def test_legacy_command_only_marker_does_not_reuse_shard_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_minimal_changed_test_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _patch_shard_run(shard_runner, monkeypatch)
    result_root = tmp_path / "results"
    result_root.mkdir()
    (result_root / "shard-1.pass").write_text("legacy-command-only-digest\n", encoding="utf-8")

    result, _ = _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=tmp_path / "cache",
        result_root=result_root,
    )

    assert len(calls) == 1
    assert result.cached is False
    assert (result_root / "shard-1.pass").read_text(encoding="utf-8").strip() != (
        "legacy-command-only-digest"
    )


def test_unchanged_rerun_reuses_shard_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_minimal_changed_test_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    calls = _patch_shard_run(shard_runner, monkeypatch)
    cache_root = tmp_path / "cache"
    result_root = tmp_path / "results"

    first, _ = _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )
    second, _ = _run_identity_checked_shard(
        shard_runner,
        root=tmp_path,
        cache_root=cache_root,
        result_root=result_root,
    )

    assert first.cached is False
    assert second.cached is True
    assert len(calls) == 1


def test_parallel_shard_creates_basetemp_parent(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "missing-cache"
    basetemp = shard_runner._shard_basetemp(cache_root, 1)

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        assert basetemp.parent.is_dir()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shard_runner.subprocess, "run", run)

    result, _ = shard_runner._run_shard(
        index=1,
        count=2,
        tests=["tests/example.py"],
        cache_root=cache_root,
        result_root=tmp_path / "results",
        environment={"PYTHONPATH": ""},
    )

    assert result.status == 0
