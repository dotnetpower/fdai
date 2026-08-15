from __future__ import annotations

import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

_BASH = "/usr/bin/bash"
_RUNNER = Path(__file__).parents[3] / "scripts" / "automation" / "run-local-service.sh"
_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:\d{2} ")


def test_runner_preserves_output_permissions_and_exit_status(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
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
    assert "service=operator-api event=starting" in lines[0]
    assert _TIMESTAMP_PREFIX.match(lines[0])
    output_lines = [line for line in lines if line.endswith(("stdout-line", "stderr-line"))]
    assert len(output_lines) == 2
    assert all(_TIMESTAMP_PREFIX.match(line) for line in output_lines)
    assert lines[-1].endswith("service=operator-api event=stopped exit_code=7")
    assert _TIMESTAMP_PREFIX.match(lines[-1])


def test_runner_removes_only_stale_output_fifos(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    stale_fifo = log_dir / ".operator-api.output.999999999"
    live_fifo = log_dir / f".operator-api.output.{os.getpid()}"
    regular_file = log_dir / ".operator-api.output.999999998"
    os.mkfifo(stale_fifo)
    os.mkfifo(live_fifo)
    regular_file.touch()

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_dir / "operator-api.log"),
            "--",
            sys.executable,
            "-c",
            "print('ready')",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert not stale_fifo.exists()
    assert live_fifo.exists()
    assert regular_file.exists()


def test_runner_rotates_three_bounded_previous_logs(tmp_path: Path) -> None:
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
            "[print(f'line-{index:03d}-' + 'x' * 80) for index in range(105)]",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    rotated = [Path(f"{log_file}.{generation}") for generation in range(1, 4)]
    assert all(path.is_file() for path in rotated)
    assert not Path(f"{log_file}.4").exists()
    assert all(path.stat().st_size <= 512 for path in rotated)
    current = log_file.read_text(encoding="utf-8")
    assert "line-104" in current
    assert current.splitlines()[-1].endswith("service=core-runtime event=stopped exit_code=0")


def test_runner_uses_one_mibibyte_default_rotation_limit(tmp_path: Path) -> None:
    log_file = tmp_path / "operator-api.log"
    log_file.write_bytes(b"x" * 1_048_576)

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "print('after-default-rotation')",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert Path(f"{log_file}.1").stat().st_size == 1_048_576
    assert "after-default-rotation" in log_file.read_text(encoding="utf-8")


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


def test_runner_preserves_allowlisted_consumer_context_only(tmp_path: Path) -> None:
    log_file = tmp_path / "core-runtime.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_LOG_FORMAT"] = "json-plain"
    payload = (
        '{"level":"INFO","logger":"fdai.delivery.azure.event_bus",'
        '"message":"event_bus_consumer_started","topic":"aw.change.events",'
        '"consumer_group":"fdai-local-pantheon.Huginn",'
        '"client_id":"fdai-core","auth_mechanism":"OAUTHBEARER",'
        '"access_token":"must-not-render"}'
    )

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
    current = log_file.read_text(encoding="utf-8")
    formatted_line = next(
        line for line in current.splitlines() if "event_bus_consumer_started" in line
    )
    assert 'topic="aw.change.events"' in formatted_line
    assert 'consumer_group="fdai-local-pantheon.Huginn"' in formatted_line
    assert 'client_id="fdai-core"' in formatted_line
    assert 'auth_mechanism="OAUTHBEARER"' in formatted_line
    assert "must-not-render" not in current


def test_runner_flushes_output_while_child_is_running(tmp_path: Path) -> None:
    log_file = tmp_path / "operator-api.log"
    process = subprocess.Popen(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
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


def test_runner_isolates_child_from_terminal_process_group(tmp_path: Path) -> None:
    log_file = tmp_path / "operator-api.log"
    process = subprocess.Popen(  # noqa: S603 - fixed test command
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            (
                "import os, time; "
                "print(f'child-process-group={os.getpgrp()}', flush=True); "
                "time.sleep(10)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().rstrip().endswith("event=starting")
        child_group_line = process.stdout.readline().rstrip()
        child_process_group = int(child_group_line.rsplit("=", 1)[1])

        assert child_process_group != os.getpgid(process.pid)
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)


def test_runner_rejects_a_second_instance_of_the_same_service(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    first_process = subprocess.Popen(  # noqa: S603 - fixed test command
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "import time; print('first-ready', flush=True); time.sleep(10)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert first_process.stdout is not None
        assert first_process.stdout.readline().rstrip().endswith("event=starting")
        assert first_process.stdout.readline().rstrip() == "first-ready"

        second_result = subprocess.run(  # noqa: S603 - fixed test command
            [
                _BASH,
                str(_RUNNER),
                "operator-api",
                str(log_file),
                "--",
                sys.executable,
                "-c",
                "print('second-child-ran')",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert second_result.returncode == 75
        assert "service already running: operator-api" in second_result.stderr
        assert "second-child-ran" not in log_file.read_text(encoding="utf-8")
    finally:
        first_process.terminate()
        first_process.wait(timeout=5)


def test_runner_refuses_a_runtime_lock_owned_by_another_checkout(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "core-runtime.log"
    runtime_lock = tmp_path / "core-runtime.lock"
    runtime_lock.touch()

    holder = subprocess.Popen(  # noqa: S603 - fixed test command
        [_BASH, "-c", f'flock "{runtime_lock}" sleep 10'],
    )
    try:
        time.sleep(0.5)
        result = subprocess.run(  # noqa: S603 - fixed test command
            [
                _BASH,
                str(_RUNNER),
                "core-runtime",
                str(log_file),
                "--",
                "env",
                f"FDAI_RUNTIME_LOCK_FILE={runtime_lock}",
                sys.executable,
                "-c",
                "print('child-ran')",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.returncode == 75
    assert f"runtime-lock={runtime_lock}" in result.stderr
    assert not log_file.exists() or "child-ran" not in log_file.read_text(encoding="utf-8")


def test_runner_refuses_a_port_owned_by_another_process(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        result = subprocess.run(  # noqa: S603 - fixed test command
            [
                _BASH,
                str(_RUNNER),
                "operator-api",
                str(log_file),
                "--",
                sys.executable,
                "-c",
                "print('child-ran')",
                "--port",
                str(port),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 75
    assert f"port=127.0.0.1:{port}" in result.stderr
    assert not log_file.exists() or "child-ran" not in log_file.read_text(encoding="utf-8")
