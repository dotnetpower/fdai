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

import pytest

_BASH = "/usr/bin/bash"
_RUNNER = Path(__file__).parents[3] / "scripts" / "automation" / "run-local-service.sh"
_INPUT_DIGEST = (
    Path(__file__).parents[3] / "scripts" / "automation" / "local-service-input-digest.py"
)
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


def test_runner_rotation_accounts_for_multibyte_log_bytes(tmp_path: Path) -> None:
    log_file = tmp_path / "core-runtime.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_LOG_MAX_BYTES"] = "256"

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "core-runtime",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "[print('가' * 30) for _ in range(12)]",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert Path(f"{log_file}.1").stat().st_size <= 256
    assert log_file.stat().st_size <= 256


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
        '"message":"event_bus_consumer_started","topic":"fdai.change.events",'
        '"consumer_group":"fdai-local-pantheon.Huginn",'
        '"client_id":"fdai-core","auth_mechanism":"OAUTHBEARER",'
        '"validation_reason":"target-bound causal evidence requires '
        'structured investigation intent",'
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
    assert 'topic="fdai.change.events"' in formatted_line
    assert 'consumer_group="fdai-local-pantheon.Huginn"' in formatted_line
    assert 'client_id="fdai-core"' in formatted_line
    assert 'auth_mechanism="OAUTHBEARER"' in formatted_line
    assert (
        'validation_reason="target-bound causal evidence requires structured investigation intent"'
        in formatted_line
    )
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


def test_runner_keeps_capturing_when_terminal_output_is_backpressured(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "operator-api.log"
    child_completed = tmp_path / "child-completed"
    process = subprocess.Popen(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            (
                "from pathlib import Path; "
                "[print('x' * 1024, flush=True) for _ in range(4096)]; "
                f"Path({str(child_completed)!r}).write_text('done')"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not child_completed.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert child_completed.read_text() == "done"
        assert log_file.stat().st_size > 0
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_runner_bounds_one_oversized_log_entry_and_terminal_line(tmp_path: Path) -> None:
    log_file = tmp_path / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_LOG_MAX_BYTES"] = "4096"

    result = subprocess.run(  # noqa: S603 - command and executable are fixed test inputs
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            sys.executable,
            "-c",
            "print('x' * (5 * 1024 * 1024))",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) < 10_000
    assert "bounded file entry retained" in result.stdout
    assert Path(f"{log_file}.1").stat().st_size <= 4096
    assert log_file.stat().st_size <= 4096


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


def test_runner_forces_a_child_that_exceeds_the_shutdown_deadline(tmp_path: Path) -> None:
    log_file = tmp_path / "operator-api.log"
    child_pid_file = tmp_path / "child.pid"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS"] = "1"
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
                "import os, signal, time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"Path({str(child_pid_file)!r}).write_text(str(os.getpid())); "
                "print('ready', flush=True); time.sleep(10)"
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    assert process.stdout is not None
    assert process.stdout.readline().rstrip().endswith("event=starting")
    assert process.stdout.readline().rstrip() == "ready"
    child_pid = int(child_pid_file.read_text())

    process.terminate()
    process.wait(timeout=4)

    assert process.returncode == 137
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert (
        log_file.read_text(encoding="utf-8")
        .splitlines()[-1]
        .endswith("service=operator-api event=stopped exit_code=137")
    )


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
                "import time; print('first-ready', flush=True); time.sleep(10)",
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


def test_runner_reuses_same_checkout_instance_when_enabled(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
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
        env=environment,
    )
    try:
        assert first_process.stdout is not None
        assert first_process.stdout.readline().rstrip().endswith("event=starting")
        assert first_process.stdout.readline().rstrip() == "first-ready"
        environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"

        second_result = subprocess.run(  # noqa: S603 - fixed test command
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
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        assert second_result.returncode == 0
        assert "service=operator-api event=starting" in second_result.stdout
        assert "service=operator-api event=reused" in second_result.stdout
        current_log = log_file.read_text(encoding="utf-8")
        assert current_log.count("first-ready") == 1
        assert "event=reused" not in current_log
        assert first_process.poll() is None
    finally:
        first_process.terminate()
        first_process.wait(timeout=5)


def test_runner_rejects_reuse_when_launch_inputs_change(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
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
        env=environment,
    )
    try:
        assert first_process.stdout is not None
        assert first_process.stdout.readline().rstrip().endswith("event=starting")
        assert first_process.stdout.readline().rstrip() == "first-ready"
        environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "b" * 64
        environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"

        second_result = subprocess.run(  # noqa: S603 - fixed test command
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
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        assert second_result.returncode == 75
        assert "service restart required: operator-api" in second_result.stderr
        assert log_file.read_text(encoding="utf-8").count("first-ready") == 1
        assert first_process.poll() is None
    finally:
        first_process.terminate()
        first_process.wait(timeout=5)


def test_runner_rejects_reuse_when_recorded_owner_does_not_hold_the_lock(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    log_file.parent.mkdir()
    lock_file = Path(f"{log_file}.lock")
    lock_file.write_text(f"{'a' * 64} {os.getpid()} {os.getpid()}\n", encoding="utf-8")
    holder = subprocess.Popen(  # noqa: S603 - fixed test lock holder
        [_BASH, "-c", f'flock "{lock_file}" sleep 10'],
    )
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
    environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"
    try:
        time.sleep(0.2)
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
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.returncode == 75
    assert "service ownership cannot be verified: operator-api" in result.stderr
    assert "child-ran" not in result.stdout


def test_runner_restarts_a_stale_same_checkout_instance_when_enabled(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
    environment["FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS"] = "1"
    command = [
        _BASH,
        str(_RUNNER),
        "operator-api",
        str(log_file),
        "--",
        sys.executable,
        "-c",
        "import time; print('ready', flush=True); time.sleep(10)",
    ]
    first_process = subprocess.Popen(  # noqa: S603 - fixed test command
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    second_process: subprocess.Popen[str] | None = None
    try:
        assert first_process.stdout is not None
        assert first_process.stdout.readline().rstrip().endswith("event=starting")
        assert first_process.stdout.readline().rstrip() == "ready"
        environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "b" * 64
        environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"
        environment["FDAI_LOCAL_SERVICE_RESTART_STALE"] = "1"

        second_process = subprocess.Popen(  # noqa: S603 - fixed test command
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
        assert second_process.stdout is not None
        lines = [second_process.stdout.readline().rstrip() for _ in range(3)]

        assert lines[0] == "service inputs changed; restarting: operator-api"
        assert lines[1].endswith("service=operator-api event=starting")
        assert lines[2] == "ready"
        assert first_process.wait(timeout=3) == 143
        assert second_process.poll() is None
    finally:
        if second_process is not None and second_process.poll() is None:
            second_process.terminate()
            second_process.wait(timeout=5)
        if first_process.poll() is None:
            first_process.terminate()
            first_process.wait(timeout=5)


def test_runner_restarts_a_stale_orphaned_child_group(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    child_pid_file = tmp_path / "child.pid"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
    environment["FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS"] = "1"
    command = [
        _BASH,
        str(_RUNNER),
        "operator-api",
        str(log_file),
        "--",
        sys.executable,
        "-c",
        (
            "import os, time; from pathlib import Path; "
            f"Path({str(child_pid_file)!r}).write_text(str(os.getpid())); "
            "print('ready', flush=True); time.sleep(10)"
        ),
    ]
    first_process = subprocess.Popen(  # noqa: S603 - fixed test command
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=environment,
    )
    second_process: subprocess.Popen[str] | None = None
    child_pid = 0
    try:
        assert first_process.stdout is not None
        assert first_process.stdout.readline().rstrip().endswith("event=starting")
        assert first_process.stdout.readline().rstrip() == "ready"
        child_pid = int(child_pid_file.read_text())
        first_process.kill()
        assert first_process.wait(timeout=3) == -signal.SIGKILL
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("service child survived its runner")

        environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "b" * 64
        environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"
        environment["FDAI_LOCAL_SERVICE_RESTART_STALE"] = "1"
        second_process = subprocess.Popen(  # noqa: S603 - fixed test command
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )
        assert second_process.stdout is not None
        lines = [second_process.stdout.readline().rstrip() for _ in range(2)]

        assert lines[0].endswith("service=operator-api event=starting")
        assert lines[1] == "ready"
        assert second_process.poll() is None
    finally:
        if second_process is not None and second_process.poll() is None:
            second_process.terminate()
            second_process.wait(timeout=5)
        if first_process.poll() is None:
            first_process.kill()
            first_process.wait(timeout=5)
        if child_pid:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_input_digest_changes_with_source_or_environment(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    module = source / "service.py"
    environment_file = tmp_path / "service.env"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    environment_file.write_text("SETTING=one\n", encoding="utf-8")

    def digest() -> str:
        result = subprocess.run(  # noqa: S603 - fixed repository script
            [sys.executable, str(_INPUT_DIGEST), str(source), str(environment_file)],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    original = digest()
    module.write_text("VALUE = 2\n", encoding="utf-8")
    source_changed = digest()
    environment_file.write_text("SETTING=two\n", encoding="utf-8")

    assert re.fullmatch(r"[a-f0-9]{64}", original)
    assert source_changed != original
    assert digest() != source_changed


def test_input_digest_accepts_paths_only_mode(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("prepared\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed repository script
        [sys.executable, str(_INPUT_DIGEST), "--paths-only", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert re.fullmatch(r"[a-f0-9]{64}", result.stdout.strip())


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


def test_runner_reports_an_unusable_runtime_lock_as_itself(tmp_path: Path) -> None:
    """flock uses 66, not 1, when it cannot open the lock file; that is not contention."""
    log_file = tmp_path / "logs" / "core-runtime.log"
    runtime_lock = tmp_path / "core-runtime.lock"
    runtime_lock.touch()
    runtime_lock.chmod(0o000)

    try:
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
        runtime_lock.chmod(0o600)

    assert result.returncode == 75
    assert f"runtime-lock-unusable={runtime_lock}" in result.stderr
    assert f"runtime-lock={runtime_lock}" not in result.stderr
    assert not log_file.exists() or "child-ran" not in log_file.read_text(encoding="utf-8")


def test_runner_refuses_a_port_owned_by_another_process(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64

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
            env=environment,
        )

    assert result.returncode == 75
    assert f"port=127.0.0.1:{port}" in result.stderr
    assert not log_file.exists() or "child-ran" not in log_file.read_text(encoding="utf-8")


def test_runner_bounds_an_unavailable_loopback_port_probe(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "operator-api.log"
    environment = os.environ.copy()
    environment["FDAI_LOCAL_SERVICE_REUSE_EXISTING"] = "1"
    environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "a" * 64
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

    started = time.monotonic()
    result = subprocess.run(  # noqa: S603 - fixed test command
        [
            _BASH,
            str(_RUNNER),
            "operator-api",
            str(log_file),
            "--",
            _BASH,
            "-c",
            "echo child-ran",
            "--",
            "--port",
            str(port),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
        env=environment,
    )

    assert time.monotonic() - started < 2
    assert result.returncode == 0
    assert "child-ran" in result.stdout
    assert "/dev/tcp" not in _RUNNER.read_text(encoding="utf-8")


def test_runner_refuses_a_port_owned_on_ipv6_loopback(tmp_path: Path) -> None:
    """--host localhost binds IPv6 loopback on a dual-stack host; that still owns the port."""
    log_file = tmp_path / "logs" / "operator-api.log"

    if not socket.has_ipv6:
        pytest.skip("host has no IPv6 support")
    listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        try:
            listener.bind(("::1", 0))
        except OSError:
            pytest.skip("host has no IPv6 loopback")
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
    finally:
        listener.close()

    assert result.returncode == 75
    assert f"port=::1:{port}" in result.stderr
    assert not log_file.exists() or "child-ran" not in log_file.read_text(encoding="utf-8")
