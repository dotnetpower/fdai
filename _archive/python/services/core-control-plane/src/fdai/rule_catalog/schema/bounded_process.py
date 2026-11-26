"""Bounded subprocess output collection for local deterministic tools."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from tempfile import TemporaryFile
from threading import Event, Thread
from typing import BinaryIO


class ProcessOutputLimitError(RuntimeError):
    """Raised after terminating a process whose stdout exceeded its limit."""


@dataclass(frozen=True, slots=True)
class BoundedProcessResult:
    returncode: int
    stdout: bytes


def run_bounded_process(
    command: Sequence[str],
    *,
    input_data: bytes | None = None,
    timeout_seconds: float,
    max_stdout_bytes: int,
) -> BoundedProcessResult:
    """Run argv without a shell while bounding elapsed time and captured stdout."""

    if not command:
        raise ValueError("command MUST be non-empty")
    if max_stdout_bytes <= 0:
        raise ValueError("max_stdout_bytes MUST be positive")

    with TemporaryFile() as input_file:
        stdin: BinaryIO | int
        if input_data is None:
            stdin = subprocess.DEVNULL
        else:
            input_file.write(input_data)
            input_file.seek(0)
            stdin = input_file
        process = subprocess.Popen(  # noqa: S603 - argv only; no shell
            list(command),
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if process.stdout is None:
            process.kill()
            process.wait()
            raise RuntimeError("bounded process stdout pipe was not created")
        stdout_pipe = process.stdout

        output = bytearray()
        output_exceeded = Event()

        def read_stdout() -> None:
            try:
                while chunk := stdout_pipe.read(64 * 1024):
                    if len(output) + len(chunk) > max_stdout_bytes:
                        output_exceeded.set()
                        process.kill()
                        return
                    output.extend(chunk)
            except (OSError, ValueError):
                return

        reader = Thread(target=read_stdout, name="bounded-process-stdout", daemon=True)
        reader.start()
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        finally:
            reader.join()
            stdout_pipe.close()

        if output_exceeded.is_set():
            raise ProcessOutputLimitError(f"process stdout exceeded {max_stdout_bytes} bytes")
        return BoundedProcessResult(returncode=returncode, stdout=bytes(output))


__all__ = [
    "BoundedProcessResult",
    "ProcessOutputLimitError",
    "run_bounded_process",
]
