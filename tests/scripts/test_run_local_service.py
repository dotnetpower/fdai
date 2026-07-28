from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

_BASH = "/usr/bin/bash"
_RUNNER = Path(__file__).parents[2] / "scripts" / "automation" / "run-local-service.sh"


def test_runner_preserves_output_permissions_and_exit_status(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "read-api.log"

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "read-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            (
                "import sys; print('stdout-line'); "
                "print('stderr-line', file=sys.stderr); raise SystemExit(7)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 7
    assert "stdout-line" in result.stdout
    assert "stderr-line" in result.stdout
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_file.parent.stat().st_mode) == 0o700
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert "service=read-api event=starting" in lines[0]
    assert lines[-1].endswith("service=read-api event=stopped exit_code=7")


def test_runner_rotates_a_bounded_previous_log(tmp_path: Path) -> None:
    log_file = tmp_path / "core-runtime.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_LOG_MAX_BYTES"] = "512"

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "core-runtime",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "[print(f'line-{index}') for index in range(105)]",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    rotated = Path(f"{log_file}.1")
    assert rotated.is_file()
    assert "line-0" in rotated.read_text(encoding="utf-8")
    current = log_file.read_text(encoding="utf-8")
    assert "line-104" in current
    assert current.splitlines()[-1].endswith("service=core-runtime event=stopped exit_code=0")
