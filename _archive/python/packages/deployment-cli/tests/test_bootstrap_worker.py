from __future__ import annotations

import multiprocessing
import os
import signal
import subprocess
import sys
import time

import pytest

from fdai_deployment_cli import bootstrap_channel as channel
from fdai_deployment_cli import bootstrap_worker as worker


def _blocked_operation(root, _request):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    channel._write(
        root / "executor",
        {
            "operation_pid": os.getpid(),
            "descendant_pid": child.pid,
        },
        "test-process.json",
    )
    while True:
        time.sleep(1)


def _serve_blocked(root, total_seconds, no_progress=None):
    worker.run_request = _blocked_operation
    if no_progress is not None:
        worker.NO_PROGRESS_SECONDS = no_progress
    worker.serve(root, total_seconds=total_seconds)


def _wait(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Bounded worker observation expired")


def _alive(pid):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("forced", [False, True])
def test_worker_termination_cleans_operation_group_and_descendants(tmp_path, forced):
    process = multiprocessing.get_context("spawn").Process(
        target=_serve_blocked,
        args=(tmp_path, 30),
    )
    process.start()
    pids = {}
    try:
        _wait(lambda: channel._read(tmp_path, "heartbeat.json"))
        channel.submit_request(tmp_path, "inspect", {})
        pids = _wait(lambda: channel._read(tmp_path / "executor", "test-process.json"))
        heartbeat = _wait(
            lambda: (
                value
                if (value := channel._read(tmp_path, "heartbeat.json")).get("operation_pid")
                else None
            )
        )
        assert heartbeat["pid"] == process.pid
        assert heartbeat["operation_pid"] == pids["operation_pid"]
        assert _alive(pids["descendant_pid"])
        if forced:
            process.kill()
        else:
            process.terminate()
        process.join(12)
        assert not process.is_alive()
        _wait(lambda: not _alive(pids["operation_pid"]) and not _alive(pids["descendant_pid"]))
        if not forced:
            assert channel.read_status(tmp_path)["phase"] == "interrupted"
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        if pids:
            try:
                os.killpg(pids["operation_pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.close()


def test_no_progress_and_total_deadlines_are_bounded(tmp_path):
    process = multiprocessing.get_context("spawn").Process(
        target=_serve_blocked,
        args=(tmp_path, 12, 0.1),
    )
    process.start()
    try:
        _wait(lambda: channel._read(tmp_path, "heartbeat.json"))
        channel.submit_request(tmp_path, "inspect", {})
        _wait(lambda: channel.read_status(tmp_path)["phase"] == "interrupted")
        status = channel.read_status(tmp_path)
        assert status["deployment_ready"] is False
        assert status["error_code"] == "operation_interrupted"
    finally:
        process.terminate()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
        process.close()
