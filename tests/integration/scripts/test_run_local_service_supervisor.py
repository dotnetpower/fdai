"""Keep single-service replacement inside its authorized process scope."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_RUNNER = Path(__file__).parents[3] / "scripts/automation/run-local-service.sh"


@pytest.mark.parametrize(
    ("changed_inputs", "inspectable"), [(False, True), (True, True), (True, False)]
)
def test_stack_owned_service_is_reused_or_refused_without_stopping_siblings(
    tmp_path: Path, changed_inputs: bool, inspectable: bool
) -> None:
    supervisor = tmp_path / "scripts/deployment/local/start-console-services.sh"
    supervisor.parent.mkdir(parents=True)
    sibling_pid_file = tmp_path / "sibling.pid"
    supervisor.write_text(
        "#!/usr/bin/bash\n"
        '"$@" &\n'
        "service_pid=$!\n"
        "sleep 60 &\n"
        "sibling_pid=$!\n"
        'printf "%s" "$sibling_pid" > "$SIBLING_PID_FILE"\n'
        "cleanup() {\n"
        '  kill -TERM "$service_pid" "$sibling_pid" 2>/dev/null || true\n'
        '  wait "$service_pid" "$sibling_pid" 2>/dev/null || true\n'
        "}\n"
        "trap cleanup EXIT\n"
        'trap "exit 130" INT TERM\n'
        'wait -n "$service_pid" "$sibling_pid"\n',
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "FDAI_LOCAL_SERVICE_INPUT_DIGEST": "a" * 64,
        "FDAI_LOCAL_SERVICE_REUSE_EXISTING": "1",
        "FDAI_LOCAL_SERVICE_RESTART_STALE": "1",
        "FDAI_LOCAL_SERVICE_SHUTDOWN_SECONDS": "1",
        "SIBLING_PID_FILE": str(sibling_pid_file),
    }
    log_file = tmp_path / "logs/operator-api.log"
    command = [
        "/usr/bin/bash",
        str(_RUNNER),
        "operator-api",
        str(log_file),
        "--",
        sys.executable,
        "-c",
        "import time; print('test-service-ready', flush=True); time.sleep(60)",
    ]
    process = subprocess.Popen(  # noqa: S603 - fixed local process fixture
        ["/usr/bin/bash", str(supervisor), *command],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while not log_file.exists() or "test-service-ready" not in log_file.read_text():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        original_lock = Path(f"{log_file}.lock").read_text()
        sibling_pid = int(sibling_pid_file.read_text())
        if changed_inputs:
            environment["FDAI_LOCAL_SERVICE_INPUT_DIGEST"] = "b" * 64
        if not inspectable:
            binary_dir = tmp_path / "bin"
            binary_dir.mkdir()
            ps = binary_dir / "ps"
            ps.write_text(
                '#!/bin/sh\nif [ "$2" = "ppid=" ]; then exit 1; fi\nexec /usr/bin/ps "$@"\n',
                encoding="utf-8",
            )
            ps.chmod(0o700)
            environment["PATH"] = f"{binary_dir}:{environment['PATH']}"
        result = subprocess.run(  # noqa: S603 - fixed local process fixture
            command,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if changed_inputs:
            assert result.returncode == 75
            assert "single-service restart blocked" in result.stderr
            expected_reason = (
                "full-stack supervisor" if inspectable else "supervisor scope cannot be verified"
            )
            assert expected_reason in result.stderr
        else:
            assert result.returncode == 0
            assert "event=reused" in result.stdout
        assert process.poll() is None
        os.kill(sibling_pid, 0)
        assert Path(f"{log_file}.lock").read_text() == original_lock
        assert log_file.read_text().count("test-service-ready") == 1
    finally:
        process.terminate()
        process.wait(timeout=5)
        # A regressed launcher may have started a replacement outside the supervisor.
        lock_file = Path(f"{log_file}.lock")
        if lock_file.exists():
            fields = lock_file.read_text().split()
            try:
                os.kill(int(fields[1]), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.killpg(int(fields[2]), signal.SIGTERM)
            except ProcessLookupError:
                pass
