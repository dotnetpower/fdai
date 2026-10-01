"""Regression tests for parallel changed-test shard isolation and pass reuse."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "automation" / "run-changed-test-shards.py"
_TESTS = ["tests/test_module.py"]


@pytest.fixture(scope="module")
def shard_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_changed_test_shards", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git plumbing in a temporary repository
        ["git", *arguments],  # noqa: S607 - git resolves from the test PATH
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_module.py").write_text("def test_value(): pass\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text(".pytest_cache/\n", encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "add", ".")
    _git(
        root,
        "-c",
        "user.email=tests@example.com",
        "-c",
        "user.name=FDAI Tests",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    venv = tmp_path / "venv"
    distribution = venv / "lib" / "python3.13" / "site-packages" / "example-1.0.dist-info"
    distribution.mkdir(parents=True)
    (venv / "bin").mkdir()
    (venv / "bin" / "python").write_text("interpreter\n", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("version_info = 3.13\n", encoding="utf-8")
    (distribution / "RECORD").write_text("example/__init__.py,sha256=a,1\n", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(venv))
    return root


def _fake_pytest(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    during_first_run: Callable[[], None] | None = None,
) -> list[list[str]]:
    real_run = subprocess.run
    runs: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[0] != "uv":
            return real_run(argv, **kwargs)  # type: ignore[call-overload,no-any-return]
        runs.append(list(argv))
        if during_first_run is not None and len(runs) == 1:
            during_first_run()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shard_runner.subprocess, "run", run)
    return runs


def _run_cached(shard_runner: ModuleType, state: Path) -> bool:
    status = shard_runner.run(
        tests=_TESTS,
        shard_count=1,
        cache_root=state / "cache",
        result_root=state / "results",
        integration=False,
    )
    assert status == 0
    summary = json.loads((state / "results" / "summary.json").read_text(encoding="utf-8"))
    return bool(summary["shards"][0]["cached"])


def test_unchanged_rerun_reuses_the_recorded_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    runs = _fake_pytest(shard_runner, monkeypatch)
    state = checkout / ".pytest_cache"

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 1


def _append(path: str) -> Callable[[Path], None]:
    def edit(root: Path) -> None:
        target = root / path
        target.write_text(target.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

    return edit


def _record_change(root: Path) -> None:
    record = next(root.parent.joinpath("venv").rglob("RECORD"))
    record.write_text("example/__init__.py,sha256=b,1\n", encoding="utf-8")


def _interpreter_change(root: Path) -> None:
    root.parent.joinpath("venv", "bin", "python").write_text("patched\n", encoding="utf-8")


def _new_module(root: Path) -> None:
    (root / "src" / "added.py").write_text("ADDED = True\n", encoding="utf-8")


def _deleted_source(root: Path) -> None:
    (root / "src" / "module.py").unlink()


@pytest.mark.parametrize(
    "change",
    [
        _append("src/module.py"),
        _append("tests/test_module.py"),
        _append("uv.lock"),
        _new_module,
        _deleted_source,
        _record_change,
        _interpreter_change,
    ],
    ids=[
        "source",
        "selected-test",
        "lock-file",
        "untracked-source",
        "deleted-source",
        "installed-distribution",
        "interpreter",
    ],
)
def test_input_change_invalidates_the_recorded_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
    change: Callable[[Path], None],
) -> None:
    runs = _fake_pytest(shard_runner, monkeypatch)
    state = checkout / ".pytest_cache"
    assert _run_cached(shard_runner, state) is False

    change(checkout)

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 2


def test_interpreter_variable_change_invalidates_the_recorded_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    runs = _fake_pytest(shard_runner, monkeypatch)
    state = checkout / ".pytest_cache"
    assert _run_cached(shard_runner, state) is False

    monkeypatch.setenv("PYTEST_ADDOPTS", "--strict-markers")

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 2


def _prepare_environment(root: Path) -> None:
    prepared = root.parent / "prepared-venv"
    (prepared / "bin").mkdir(parents=True)
    (prepared / "bin" / "python").write_text("interpreter\n", encoding="utf-8")


def _install_distribution(root: Path) -> None:
    site_packages = root.parent / "venv" / "lib" / "python3.13" / "site-packages"
    distribution = site_packages / "weasyprint-70.0.dist-info"
    distribution.mkdir()
    (distribution / "RECORD").write_text("weasyprint/__init__.py,sha256=c,1\n", encoding="utf-8")


def _revert_source(root: Path) -> None:
    source = root / "src" / "module.py"
    original = source.read_text(encoding="utf-8")
    source.write_text("VALUE = 2\n", encoding="utf-8")
    source.write_text(original, encoding="utf-8")


@pytest.mark.parametrize(
    "change",
    [
        _append("src/module.py"),
        _revert_source,
        _install_distribution,
        _prepare_environment,
    ],
    ids=["source", "reverted-source", "installed-distribution", "prepared-environment"],
)
def test_change_while_running_records_no_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
    change: Callable[[Path], None],
) -> None:
    if change is _prepare_environment:
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(checkout.parent / "prepared-venv"))
    runs = _fake_pytest(shard_runner, monkeypatch, during_first_run=lambda: change(checkout))
    state = checkout / ".pytest_cache"

    assert _run_cached(shard_runner, state) is False
    assert not (state / "results" / "shard-1.pass").exists()
    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 2


def test_bytecode_written_while_running_keeps_the_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    def write_bytecode() -> None:
        cache = checkout.parent / "venv" / "lib" / "python3.13" / "site-packages" / "__pycache__"
        cache.mkdir()
        (cache / "example.cpython-313.pyc").write_bytes(b"bytecode")

    runs = _fake_pytest(shard_runner, monkeypatch, during_first_run=write_bytecode)
    state = checkout / ".pytest_cache"

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 1


def test_runner_state_inside_the_checkout_is_not_an_input(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    runs = _fake_pytest(shard_runner, monkeypatch)
    state = checkout / "runner-state"

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is True
    assert len(runs) == 1


def test_unavailable_input_identity_never_reuses_a_pass(
    shard_runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "not-a-checkout"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    runs = _fake_pytest(shard_runner, monkeypatch)
    state = outside / "state"

    assert _run_cached(shard_runner, state) is False
    assert _run_cached(shard_runner, state) is False
    assert not (state / "results" / "shard-1.pass").exists()
    assert len(runs) == 2


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
        inputs=None,
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
        inputs=None,
    )

    assert result.status == 0
