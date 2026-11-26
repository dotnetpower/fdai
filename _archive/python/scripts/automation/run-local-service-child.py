#!/usr/bin/env python3
"""Exec one local service as a session leader that terminates with its runner."""

from __future__ import annotations

import ctypes
import os
import signal
import sys

_PR_SET_PDEATHSIG = 1


def _bind_parent_death_signal() -> bool:
    parent_pid = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    prctl.restype = ctypes.c_int
    if prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return os.getppid() == parent_pid


def main() -> int:
    """Become a session leader and replace this process with the service command."""
    if len(sys.argv) < 2:
        raise SystemExit("local service child command is required")
    if not _bind_parent_death_signal():
        return 143
    os.setsid()
    os.execvp(  # noqa: S606 - trusted repository task argv is executed without a shell.
        sys.argv[1], sys.argv[1:]
    )
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
