"""Keep Foundation stderr in the existing display without owning subprocess execution."""

from __future__ import annotations

import codecs
import os
import select
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from fdai_deployment_cli.foundation_progress import FoundationCheckpoint, FoundationProgressStream

_DRAIN_SECONDS = 1.0


class _Reader:
    """Drain one nonblocking pipe; a display failure cannot backpressure the child forever."""

    def __init__(self, descriptor: int, stream: FoundationProgressStream) -> None:
        self.descriptor = descriptor
        self.stream = stream
        self.stop = threading.Event()
        self.failure: BaseException | None = None

    def run(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        drain_deadline: float | None = None
        try:
            while True:
                if self.stop.is_set():
                    if drain_deadline is None:
                        drain_deadline = time.monotonic() + _DRAIN_SECONDS
                    if time.monotonic() >= drain_deadline:
                        self.failure = self.failure or TimeoutError(
                            "Foundation output drain expired"
                        )
                        break
                readable, _, _ = select.select([self.descriptor], [], [], 0.05)
                if not readable:
                    if drain_deadline is not None:
                        break
                    continue
                try:
                    content = os.read(self.descriptor, 4096)
                except BlockingIOError:
                    continue
                if not content:
                    break
                if self.failure is None:
                    try:
                        self.stream.feed(decoder.decode(content))
                    except Exception as exc:  # noqa: BLE001 - rethrow in owner after draining the pipe.
                        self.failure = exc
            if self.failure is None:
                self.stream.feed(decoder.decode(b"", final=True))
                self.stream.finish()
        except Exception as exc:  # noqa: BLE001 - transfer thread failures to the owning context.
            self.failure = self.failure or exc
        finally:
            os.close(self.descriptor)


@contextmanager
def _capture(stream: FoundationProgressStream) -> Iterator[int]:
    """Yield a child stderr descriptor while retaining the caller's run/timeout/exit policy."""
    read_descriptor, write_descriptor = os.pipe()
    try:
        os.set_blocking(read_descriptor, False)
        reader = _Reader(read_descriptor, stream)
        thread = threading.Thread(target=reader.run, name="fdai-foundation-display", daemon=True)
        thread.start()
    except BaseException:
        os.close(read_descriptor)
        os.close(write_descriptor)
        raise
    primary_error: BaseException | None = None
    try:
        yield write_descriptor
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        os.close(write_descriptor)
        reader.stop.set()
        thread.join(timeout=_DRAIN_SECONDS + 1)
        failed = thread.is_alive() or reader.failure is not None
        if failed:
            message = "Foundation display output is incomplete; review retained execution evidence"
            if primary_error is not None:
                primary_error.add_note(message)
            else:
                raise ValueError(message) from reader.failure


@contextmanager
def foundation_output() -> Iterator[int | None]:
    """Compact known presentation only for a live TTY dashboard; preserve all other modes.

    Unknown output temporarily owns the terminal unchanged. Approvals use their separate existing
    path. This adapter neither launches a process nor reads status, stdin, plans, or credentials.
    """
    from fdai_deployment_cli.deployment_progress import _CURRENT, terminal_output

    progress = _CURRENT.get()
    if progress is None or not progress.dynamic:
        with terminal_output("Foundation checkpoint details"):
            yield None
        return

    progress.reset_foundation()
    native = ExitStack()
    native_active = False

    def close_native() -> None:
        nonlocal native_active
        native.close()
        native_active = False

    def output(text: str) -> None:
        nonlocal native_active
        if not native_active:
            native.enter_context(progress.terminal_output("Foundation details"))
            native_active = True
        progress.console.file.write(text)
        progress.console.file.flush()

    def checkpoint(value: FoundationCheckpoint) -> None:
        close_native()
        progress.foundation_checkpoint(value)

    def mode(value: str) -> None:
        close_native()
        progress.foundation_mode(value)

    stream = FoundationProgressStream(
        output=output,
        checkpoint=checkpoint,
        heartbeat=progress.foundation_signal,
        mode=mode,
    )
    try:
        with _capture(stream) as descriptor:
            yield descriptor
    finally:
        original_error = sys.exception()
        try:
            close_native()
        except (OSError, ValueError) as exc:
            if original_error is None:
                raise
            original_error.add_note(f"Foundation display cleanup failed: {type(exc).__name__}")
