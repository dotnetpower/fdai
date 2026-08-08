"""CLI contract tests for the repository verification facade."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_VERIFY = _ROOT / "scripts" / "verify.sh"
_PYTHON_TESTS = _ROOT / "scripts" / "quality" / "ci" / "run-python-tests.sh"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository script with test-controlled arguments
        [str(_VERIFY), *arguments],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603 - test-controlled Git arguments
        [git, *arguments],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_full_requires_a_focused_pytest_path() -> None:
    result = _run("--full")

    assert result.returncode == 2
    assert "--full requires a pytest path" in result.stderr
    assert "--all" in result.stderr


def test_help_distinguishes_focused_and_whole_suite_modes() -> None:
    result = _run("--help")

    assert result.returncode == 0
    assert "--full <path>" in result.stdout
    assert "--all" in result.stdout


def test_diff_scoping_and_gate_cache_use_exact_head(tmp_path: Path) -> None:
    assert _git(tmp_path, "init", "--quiet").returncode == 0
    assert _git(tmp_path, "config", "user.email", "tests@example.com").returncode == 0
    assert _git(tmp_path, "config", "user.name", "FDAI Tests").returncode == 0
    docs = tmp_path / "docs"
    docs.mkdir()
    document = docs / "guide.md"
    document.write_text("initial\n", encoding="utf-8")
    assert _git(tmp_path, "add", ".").returncode == 0
    assert _git(tmp_path, "commit", "--quiet", "-m", "initial").returncode == 0
    document.write_text("changed\n", encoding="utf-8")
    assert _git(tmp_path, "add", ".").returncode == 0
    assert _git(tmp_path, "commit", "--quiet", "-m", "docs").returncode == 0

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"
    fake = bin_dir / "fake"
    fake.write_text(
        '#!/bin/sh\nprintf "%s:%s\\n" "$(basename "$0")" "$*" >> "$FDAI_VERIFY_TEST_LOG"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    for name in ("bash", "python3", "uv"):
        (bin_dir / name).symlink_to(fake)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FDAI_VERIFY_CACHE_DIR": str(tmp_path / "cache"),
        "FDAI_VERIFY_TEST_LOG": str(command_log),
    }
    real_bash = shutil.which("bash", path=os.environ["PATH"])
    assert real_bash is not None
    command = [real_bash, str(_VERIFY), "--fast", "--diff", "HEAD^..HEAD"]

    first = subprocess.run(  # noqa: S603 - fixed script and test-controlled arguments
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    first_commands = command_log.read_text(encoding="utf-8")
    second = subprocess.run(  # noqa: S603 - fixed script and test-controlled arguments
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    environment["FDAI_VERIFY_CONTEXT_DIGEST"] = "changed-local-input"
    third = subprocess.run(  # noqa: S603 - fixed script and test-controlled arguments
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert third.returncode == 0, third.stderr
    assert "ruff format" not in first_commands
    assert "mypy" not in first_commands
    assert "check-translations.sh" in first_commands
    assert command_log.read_text(encoding="utf-8") == first_commands * 2
    assert "CACHED" in second.stdout


def test_diff_is_rejected_outside_fast_mode() -> None:
    result = _run("--all", "--diff", "HEAD^..HEAD")

    assert result.returncode == 2
    assert "supported only with --fast" in result.stderr


def test_verification_entrypoints_prepend_current_checkout_source() -> None:
    contract = (
        'export PYTHONPATH="$repo_root/services/core-control-plane/src:'
        '$repo_root/packages/service-contracts/src${PYTHONPATH:+:$PYTHONPATH}"'
    )

    assert contract in _VERIFY.read_text(encoding="utf-8")
    assert contract in _PYTHON_TESTS.read_text(encoding="utf-8")


def test_safety_core_coverage_includes_dedicated_quality_gate_tests() -> None:
    assert "services/core-control-plane/tests/quality_gate" in _PYTHON_TESTS.read_text(
        encoding="utf-8"
    )


def test_python_test_runner_prefers_current_checkout_at_runtime(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorded = tmp_path / "pythonpath.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        '#!/usr/bin/env bash\nprintf "%s\n" "$PYTHONPATH" > "$RECORDED_PYTHONPATH"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    inherited = str(tmp_path / "other-worktree" / "src")
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - fixed repository script, test-controlled env
        [bash, str(_PYTHON_TESTS), "tests/integration/scripts/test_verify_script.py"],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PYTHONPATH": inherited,
            "RECORDED_PYTHONPATH": str(recorded),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert recorded.read_text(encoding="utf-8").strip().split(":")[:3] == [
        str(_ROOT / "services" / "core-control-plane" / "src"),
        str(_ROOT / "packages" / "service-contracts" / "src"),
        inherited,
    ]


def test_python_test_runner_isolates_database_env_by_phase(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorded = tmp_path / "database-env.txt"
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s|%s|%s\\n" "${FDAI_DATABASE_URL-unset}" '
        '"${FDAI_STATE_STORE_DSN-unset}" "$*" >> "$RECORDED_DATABASE_ENV"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(  # noqa: S603 - fixed repository script, test-controlled env
        [bash, str(_PYTHON_TESTS)],
        cwd=_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FDAI_DATABASE_URL": "postgresql://example.invalid/fdai",
            "FDAI_STATE_STORE_DSN": "postgresql://example.invalid/state",
            "FDAI_PYTEST_MODE": "all",
            "FDAI_PYTEST_SHARD_COUNT": "",
            "FDAI_PYTEST_SHARD_INDEX": "",
            "FDAI_PYTEST_XDIST": "0",
            "RECORDED_DATABASE_ENV": str(recorded),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = recorded.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("unset|unset|run pytest -q -m not integration")
    assert lines[1].startswith(
        "postgresql://example.invalid/fdai|postgresql://example.invalid/state|"
        "run pytest -q -m integration"
    )
