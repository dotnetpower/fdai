"""Supervise the installed Foundation coordinator without abandoning claimed effects."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path


def _interrupted(signum: int, _frame: object) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def run_foundation_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Preserve terminal I/O and allow nested SIGTERM cleanup before forced termination.

    Return the actual child exit code. Timeout or caller interruption stops the
    process group with a five-second cleanup reserve; neither path grants retry.
    Optional caller-owned output descriptors preserve presentation without changing
    stdin, descriptor ownership, or the process-group termination contract.
    """
    process = subprocess.Popen(  # noqa: S603 - fixed signed Foundation entrypoint.
        command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True
    )
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.signal(signal.SIGTERM, _interrupted)
    try:
        status = process.wait(timeout=timeout)
    except BaseException:
        _stop(process)
        raise
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    return subprocess.CompletedProcess(command, status)


def _stop(process: subprocess.Popen[bytes]) -> None:
    for selected_signal, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 1)):
        try:
            os.killpg(process.pid, selected_signal)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            # A terminated coordinator might have left another direct group member.
            if selected_signal == signal.SIGTERM:
                continue
            return
        except subprocess.TimeoutExpired:
            continue
