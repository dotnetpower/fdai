"""CLI contract tests for the repository verification facade."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
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


def test_verification_entrypoints_prepend_current_checkout_source() -> None:
    contract = 'export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"'

    assert contract in _VERIFY.read_text(encoding="utf-8")
    assert contract in _PYTHON_TESTS.read_text(encoding="utf-8")


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
        [bash, str(_PYTHON_TESTS), "tests/scripts/test_verify_script.py"],
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
    assert recorded.read_text(encoding="utf-8").strip().split(":")[:2] == [
        str(_ROOT / "src"),
        inherited,
    ]
