"""Bounded Genesis subprocess heartbeat regressions."""

from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(_SCRIPT_DIR))

from genesis_subprocess import run_with_heartbeat  # noqa: E402


def test_silent_command_prints_periodic_stderr_heartbeat() -> None:
    heartbeat = io.StringIO()

    result = run_with_heartbeat(
        (sys.executable, "-c", "import time; time.sleep(0.06)"),
        cwd=_ROOT,
        timeout=1,
        capture_output=True,
        heartbeat_seconds=0.01,
        heartbeat_stream=heartbeat,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert heartbeat.getvalue().endswith("\n")
    assert heartbeat.getvalue().count(".") >= 2


def test_captured_output_and_json_are_separate_from_heartbeat() -> None:
    heartbeat = io.StringIO()
    command = (
        "import sys,time;"
        'print(\'{"state":"review"}\', flush=True);'
        "print('bounded diagnostic', file=sys.stderr, flush=True);"
        "time.sleep(0.04)"
    )

    result = run_with_heartbeat(
        (sys.executable, "-c", command),
        cwd=_ROOT,
        timeout=1,
        capture_output=True,
        heartbeat_seconds=0.01,
        heartbeat_stream=heartbeat,
    )

    assert result.stdout == '{"state":"review"}\n'
    assert result.stderr == "bounded diagnostic\n"
    assert "." not in result.stdout + result.stderr
    assert heartbeat.getvalue().count(".") >= 1


def test_timeout_preserves_output_and_terminates_the_descendant_group(tmp_path: Path) -> None:
    heartbeat = io.StringIO()
    ready = tmp_path / "descendant-ready"
    terminated = tmp_path / "descendant-terminated"
    child = f"""
import signal
import sys
import time
from pathlib import Path

ready = Path({str(ready)!r})
marker = Path({str(terminated)!r})

def terminate(*_args: object) -> None:
    marker.write_text("terminated", encoding="ascii")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, terminate)
ready.write_text("ready", encoding="ascii")
time.sleep(30)
"""
    parent = f"""
import subprocess
import sys
import time
from pathlib import Path

subprocess.Popen([sys.executable, "-c", {child!r}])
ready = Path({str(ready)!r})
while not ready.exists():
    time.sleep(0.001)
print("parent-ready", flush=True)
print("bounded diagnostic", file=sys.stderr, flush=True)
time.sleep(30)
"""

    with pytest.raises(subprocess.TimeoutExpired) as raised:
        run_with_heartbeat(
            (sys.executable, "-c", parent),
            cwd=_ROOT,
            timeout=0.5,
            capture_output=True,
            heartbeat_seconds=0.05,
            heartbeat_stream=heartbeat,
        )

    assert "parent-ready" in str(raised.value.output)
    assert "bounded diagnostic" in str(raised.value.stderr)
    assert terminated.read_text(encoding="ascii") == "terminated"
    assert heartbeat.getvalue().endswith("\n")


def test_invalid_budget_is_rejected_before_process_start() -> None:
    with pytest.raises(ValueError, match="timeout"):
        run_with_heartbeat((sys.executable, "-c", "pass"), cwd=_ROOT, timeout=0)


def test_private_umask_applies_to_child_outputs(tmp_path: Path) -> None:
    output = tmp_path / "private-output"

    result = run_with_heartbeat(
        (sys.executable, "-c", f"open({str(output)!r}, 'w').write('private')"),
        cwd=_ROOT,
        timeout=1,
        capture_output=True,
        umask=0o077,
    )

    assert result.returncode == 0
    assert output.stat().st_mode & 0o777 == 0o600


def test_private_stdin_reaches_child_without_joining_output() -> None:
    private_input = "short-lived-registration-material"

    result = run_with_heartbeat(
        (
            sys.executable,
            "-c",
            "import sys; value=sys.stdin.read(); print(len(value))",
        ),
        cwd=_ROOT,
        timeout=1,
        capture_output=True,
        input_text=private_input,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == str(len(private_input))
    assert private_input not in result.stdout + result.stderr


def test_nested_genesis_cancellation_stops_inner_effect_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "synthetic-effect-pid"
    child = (
        "import os, signal; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid())); signal.pause()"
    )
    stage = (
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(_SCRIPT_DIR)!r})\n"
        "from genesis_subprocess import run_with_heartbeat\n"
        f"run_with_heartbeat((sys.executable, '-c', {child!r}), "
        "cwd=Path.cwd(), timeout=20, capture_output=True)\n"
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_with_heartbeat(
                (sys.executable, "-c", stage),
                cwd=tmp_path,
                timeout=1,
                capture_output=True,
                heartbeat_stream=io.StringIO(),
            )
        pid = int(pid_file.read_text())
        state = Path(f"/proc/{pid}/stat")
        assert not state.exists() or state.read_text().split()[2] == "Z"
    finally:
        if pid_file.exists():
            try:
                group = os.getpgid(int(pid_file.read_text()))
                if group != os.getpgrp():
                    os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_signal_handler_is_restored_and_worker_thread_reads_still_run() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    run_with_heartbeat((sys.executable, "-c", "pass"), cwd=_ROOT, timeout=2)
    assert signal.getsignal(signal.SIGTERM) == previous
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(
            run_with_heartbeat,
            (sys.executable, "-c", "print('read-only')"),
            cwd=_ROOT,
            timeout=2,
            capture_output=True,
        ).result(timeout=3)
    assert result.stdout == "read-only\n"
    assert signal.getsignal(signal.SIGTERM) == previous
