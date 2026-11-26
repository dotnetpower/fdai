"""Run one repository command within total and no-progress deadlines."""

from __future__ import annotations

import argparse
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

TIMEOUT_STATUS = 124
_LABEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _parse_args(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=_positive_int)
    parser.add_argument("--no-progress-seconds", required=True, type=_positive_int)
    parser.add_argument("--termination-grace-seconds", type=_positive_int, default=5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(arguments)
    if not _LABEL_PATTERN.fullmatch(parsed.label):
        parser.error("--label must contain only lowercase ASCII letters, digits, '.', '_', or '-'")
    if parsed.command[:1] == ["--"]:
        parsed.command = parsed.command[1:]
    if not parsed.command:
        parser.error("a command is required after '--'")
    return parsed


def _signal_process_group(process: subprocess.Popen[bytes], signal_number: int) -> None:
    try:
        os.killpg(process.pid, signal_number)
    except ProcessLookupError:
        return


def run_bounded_command(
    command: Sequence[str],
    *,
    label: str,
    timeout_seconds: int,
    no_progress_seconds: int,
    termination_grace_seconds: int,
) -> int:
    """Stream one command and stop its process group when either deadline expires."""
    started = time.monotonic()
    last_progress = started
    process = subprocess.Popen(  # noqa: S603 - callers provide repository-owned commands.
        list(command),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        start_new_session=True,
    )
    if process.stdout is None:
        raise RuntimeError("bounded command stdout pipe was not created")

    forwarded_signal: int | None = None
    forwarded_at: float | None = None

    def forward_signal(signal_number: int, _frame: object) -> None:
        nonlocal forwarded_at, forwarded_signal
        if forwarded_signal is None:
            forwarded_signal = signal_number
            forwarded_at = time.monotonic()
            _signal_process_group(process, signal_number)

    previous_handlers = {
        signal_number: signal.signal(signal_number, forward_signal)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    expired_reason: str | None = None
    force_kill_sent = False
    try:
        while selector.get_map() or process.poll() is None:
            now = time.monotonic()
            if forwarded_signal is None and expired_reason is None:
                if now - started >= timeout_seconds:
                    expired_reason = f"exceeded-total-{timeout_seconds}s"
                    _signal_process_group(process, signal.SIGTERM)
                    forwarded_at = now
                elif now - last_progress >= no_progress_seconds:
                    expired_reason = f"no-progress-{no_progress_seconds}s"
                    _signal_process_group(process, signal.SIGTERM)
                    forwarded_at = now
            if (
                not force_kill_sent
                and forwarded_at is not None
                and now - forwarded_at >= termination_grace_seconds
            ):
                _signal_process_group(process, signal.SIGKILL)
                force_kill_sent = True

            events = selector.select(timeout=0.1)
            for key, _mask in events:
                chunk = os.read(key.fd, 65_536)
                if chunk:
                    last_progress = time.monotonic()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                else:
                    selector.unregister(key.fileobj)
            if force_kill_sent and process.poll() is not None:
                for key in tuple(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
        status = process.wait()
    finally:
        selector.close()
        for signal_number, previous_handler in previous_handlers.items():
            signal.signal(signal_number, previous_handler)

    if expired_reason is not None:
        print(
            f"bounded-command: label={label} event=failed "
            f"reason={expired_reason} exit_code={TIMEOUT_STATUS}",
            file=sys.stderr,
        )
        return TIMEOUT_STATUS
    if forwarded_signal is not None:
        return 128 + forwarded_signal
    return status


def main(arguments: Sequence[str] | None = None) -> int:
    """Parse one bounded command invocation and return its terminal status."""
    parsed = _parse_args(arguments if arguments is not None else sys.argv[1:])
    return run_bounded_command(
        parsed.command,
        label=parsed.label,
        timeout_seconds=parsed.timeout_seconds,
        no_progress_seconds=parsed.no_progress_seconds,
        termination_grace_seconds=parsed.termination_grace_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
