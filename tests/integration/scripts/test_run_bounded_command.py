from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _REPO_ROOT / "scripts/automation/run-bounded-command.py"


def _run(*command: str, timeout_seconds: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository runner and test commands.
        [
            sys.executable,
            str(_RUNNER),
            "--label",
            "test-stage",
            "--timeout-seconds",
            str(timeout_seconds),
            "--no-progress-seconds",
            "1",
            "--termination-grace-seconds",
            "1",
            "--",
            *command,
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds + 5,
    )


def test_runner_streams_output_and_propagates_success() -> None:
    result = _run(sys.executable, "-c", "print('bounded-ready', flush=True)")

    assert result.returncode == 0
    assert result.stdout == "bounded-ready\n"
    assert result.stderr == ""


def test_runner_propagates_nonzero_exit() -> None:
    result = _run(sys.executable, "-c", "raise SystemExit(7)")

    assert result.returncode == 7
    assert "bounded-command:" not in result.stderr


def test_runner_kills_a_command_that_makes_no_progress() -> None:
    started = time.monotonic()
    result = _run(sys.executable, "-c", "import time; time.sleep(30)")

    assert time.monotonic() - started < 4
    assert result.returncode == 124
    assert (
        "bounded-command: label=test-stage event=failed reason=no-progress-1s exit_code=124"
    ) in result.stderr


def test_runner_enforces_total_budget_while_output_continues() -> None:
    result = _run(
        sys.executable,
        "-u",
        "-c",
        "import time\nwhile True:\n print('progress', flush=True)\n time.sleep(0.1)",
        timeout_seconds=1,
    )

    assert result.returncode == 124
    assert "progress\n" in result.stdout
    assert (
        "bounded-command: label=test-stage event=failed reason=exceeded-total-1s exit_code=124"
    ) in result.stderr
