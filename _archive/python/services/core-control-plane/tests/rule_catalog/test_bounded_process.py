"""Executable limits for deterministic local tool subprocesses."""

from __future__ import annotations

import subprocess
import sys

import pytest
from fdai.rule_catalog.schema.bounded_process import (
    ProcessOutputLimitError,
    run_bounded_process,
)


def test_bounded_process_preserves_output_within_limit() -> None:
    result = run_bounded_process(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'bounded')"],
        timeout_seconds=1.0,
        max_stdout_bytes=7,
    )

    assert result.returncode == 0
    assert result.stdout == b"bounded"


def test_bounded_process_forwards_stdin() -> None:
    result = run_bounded_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ],
        input_data=b"canonical-input",
        timeout_seconds=1.0,
        max_stdout_bytes=15,
    )

    assert result.stdout == b"canonical-input"


def test_bounded_process_preserves_nonzero_exit() -> None:
    result = run_bounded_process(
        [sys.executable, "-c", "raise SystemExit(17)"],
        timeout_seconds=1.0,
        max_stdout_bytes=1024,
    )

    assert result.returncode == 17


def test_bounded_process_discards_stderr() -> None:
    result = run_bounded_process(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.buffer.write(b'sensitive' * 100000)",
        ],
        timeout_seconds=1.0,
        max_stdout_bytes=1024,
    )

    assert result.returncode == 0
    assert result.stdout == b""
    assert not hasattr(result, "stderr")


def test_bounded_process_terminates_output_limit_violation() -> None:
    with pytest.raises(ProcessOutputLimitError):
        run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 2048)"],
            timeout_seconds=1.0,
            max_stdout_bytes=1024,
        )


def test_bounded_process_terminates_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_process(
            [sys.executable, "-c", "while True: pass"],
            timeout_seconds=0.1,
            max_stdout_bytes=1024,
        )
