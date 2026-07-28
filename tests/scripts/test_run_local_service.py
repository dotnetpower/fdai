from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

_BASH = "/usr/bin/bash"
_RUNNER = Path(__file__).parents[2] / "scripts" / "automation" / "run-local-service.sh"
_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2} ")


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
    assert _TIMESTAMP_PREFIX.match(lines[0])
    output_lines = [line for line in lines if line.endswith(("stdout-line", "stderr-line"))]
    assert len(output_lines) == 2
    assert all(_TIMESTAMP_PREFIX.match(line) for line in output_lines)
    assert lines[-1].endswith("service=read-api event=stopped exit_code=7")
    assert _TIMESTAMP_PREFIX.match(lines[-1])


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


def test_runner_formats_json_for_file_without_changing_stdout(tmp_path: Path) -> None:
    log_file = tmp_path / "core-runtime.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_LOG_FORMAT"] = "json-plain"
    payload = '{"level":"INFO","logger":"fdai.startup","message":"startup_ok"}'

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "core-runtime",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            f"print({payload!r})",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert payload in result.stdout
    current = log_file.read_text(encoding="utf-8")
    formatted_line = next(line for line in current.splitlines() if "startup_ok" in line)
    assert _TIMESTAMP_PREFIX.match(formatted_line)
    assert formatted_line.endswith("INFO: fdai.startup: startup_ok")
    assert payload not in current


def test_runner_flushes_output_while_child_is_running(tmp_path: Path) -> None:
    log_file = tmp_path / "read-api.log"
    process = subprocess.Popen(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "read-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "import time; print('ready-line', flush=True); time.sleep(10)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().rstrip().endswith("event=starting")
        assert process.stdout.readline().rstrip() == "ready-line"
        for _ in range(100):
            if "ready-line" in log_file.read_text(encoding="utf-8"):
                break
            time.sleep(0.01)
        assert "ready-line" in log_file.read_text(encoding="utf-8")
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)
