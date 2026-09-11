#!/usr/bin/env python3
"""Run bounded Genesis child processes with an stderr heartbeat."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

DEFAULT_HEARTBEAT_SECONDS = 10.0
_TERMINATION_GRACE_SECONDS = 1.0


def run_with_heartbeat(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    heartbeat_stream: TextIO | None = None,
    umask: int = -1,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one command and emit dots without mixing them into captured output.

    The command starts in a new process group. A timeout or caller interruption
    terminates that complete group before returning or raising. Captured stdout
    and stderr remain byte-for-byte text inputs to the caller; heartbeat dots are
    written only to the separate stderr presentation stream.
    """

    if not arguments or any(not isinstance(value, str) or not value for value in arguments):
        raise ValueError("Genesis command arguments must be nonempty strings")
    if timeout <= 0:
        raise ValueError("Genesis command timeout must be positive")
    if heartbeat_seconds <= 0:
        raise ValueError("Genesis heartbeat interval must be positive")
    if umask != -1 and not 0 <= umask <= 0o777:
        raise ValueError("Genesis command umask must be -1 or a valid permission mask")
    if input_text is not None and (not isinstance(input_text, str) or len(input_text) > 8192):
        raise ValueError("Genesis command input must be text within 8192 characters")

    stream = heartbeat_stream if heartbeat_stream is not None else sys.stderr
    command = tuple(arguments)
    process = subprocess.Popen(  # noqa: S603 - callers supply fixed repository/tool commands
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
        start_new_session=True,
        umask=umask,
    )
    deadline = time.monotonic() + timeout
    heartbeat_emitted = False
    pending_input = input_text
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stdout, stderr = _terminate_process_group(process)
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=stdout,
                    stderr=stderr,
                )
            try:
                stdout, stderr = process.communicate(
                    input=pending_input,
                    timeout=min(heartbeat_seconds, remaining),
                )
                pending_input = None
            except subprocess.TimeoutExpired:
                pending_input = None
                stream.write(".")
                stream.flush()
                heartbeat_emitted = True
                continue
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout,
                stderr,
            )
    except BaseException:
        if process.poll() is None:
            _terminate_process_group(process)
        raise
    finally:
        if heartbeat_emitted:
            stream.write("\n")
            stream.flush()


def _terminate_process_group(
    process: subprocess.Popen[str],
) -> tuple[str | None, str | None]:
    """Terminate the complete child group and drain its captured output."""

    _signal_process_group(process.pid, signal.SIGTERM)
    try:
        return process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_process_group(process.pid, signal.SIGKILL)
        return process.communicate()


def _signal_process_group(process_id: int, selected_signal: signal.Signals) -> None:
    try:
        os.killpg(process_id, selected_signal)
    except ProcessLookupError:
        return
