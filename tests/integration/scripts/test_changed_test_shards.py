"""Regression tests for parallel changed-test shard isolation."""

from __future__ import annotations

import importlib.util
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
    basetemp = cache_root / "tmp-shard-2"
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


def test_parallel_shard_creates_basetemp_parent(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "missing-cache"
    basetemp = cache_root / "tmp-shard-1"

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
