"""Preserve Foundation output descriptors and fail-closed process-group cleanup."""

from __future__ import annotations

import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from fdai_deployment_cli import foundation_process


def test_output_descriptors_preserve_streams_and_actual_exit_code(tmp_path):
    command = [
        sys.executable,
        "-c",
        "import sys; print('machine-output'); print('stage-detail', file=sys.stderr); sys.exit(7)",
    ]
    with (tmp_path / "stdout").open("w+b") as stdout, (tmp_path / "stderr").open("w+b") as stderr:
        result = foundation_process.run_foundation_process(
            command,
            cwd=tmp_path,
            env={},
            timeout=5,
            stdout=stdout.fileno(),
            stderr=stderr.fileno(),
        )
        assert result.returncode == 7
        assert result.stdout is None and result.stderr is None
        stdout.seek(0)
        stderr.seek(0)
        assert stdout.read() == b"machine-output\n"
        assert stderr.read() == b"stage-detail\n"


@pytest.mark.parametrize(
    "failure", [subprocess.TimeoutExpired("synthetic", 1), KeyboardInterrupt()]
)
def test_output_redirection_keeps_cleanup_and_original_failure(tmp_path, monkeypatch, failure):
    calls = []
    signals = []
    launches = []

    def wait(*, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise failure
        return 0

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return SimpleNamespace(pid=123, wait=wait)

    monkeypatch.setattr(foundation_process.subprocess, "Popen", launch)
    monkeypatch.setattr(
        foundation_process.os, "killpg", lambda pid, value: signals.append((pid, value))
    )
    with pytest.raises(type(failure)) as error:
        foundation_process.run_foundation_process(
            ["synthetic"],
            cwd=tmp_path,
            env={},
            timeout=1,
            stdout=subprocess.DEVNULL,
            stderr=9,
        )
    assert error.value is failure
    assert calls == [1, 5, 1]
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert launches[0][1] == {
        "cwd": tmp_path,
        "env": {},
        "stdout": subprocess.DEVNULL,
        "stderr": 9,
        "start_new_session": True,
    }
