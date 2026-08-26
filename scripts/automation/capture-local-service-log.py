#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import os
import select
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO

# Allowlist, not a denylist: an unlisted field never reaches the plain log, so a
# record that carries a secret cannot leak through a newly added logger.
_PLAIN_CONTEXT_FIELDS = (
    "topic",
    "consumer_group",
    "client_id",
    "auth_mechanism",
    "stage",
    "plan_nodes",
    "plan_source",
    "output_shape",
    "failure_type",
    "validation_reason",
    "primary_intent",
    "secondary_intents",
    "discourse_mode",
    "requested_facets",
    "target_count",
    "target_kinds",
    "canonical_target_types",
)
_TERMINAL_BUFFER_LINES = 1_024
_TERMINAL_BUFFER_BYTES = 4 * 1_024 * 1_024
_TERMINAL_DRAIN_SECONDS = 1.0
_ENTRY_TRUNCATION_SUFFIX = "...[local log entry truncated]\n"


class _TerminalBuffer:
    def __init__(self, max_lines: int, max_bytes: int) -> None:
        self._max_lines = max_lines
        self._max_bytes = max_bytes
        self._lines: collections.deque[tuple[str, int]] = collections.deque()
        self._buffered_bytes = 0
        self._dropped = 0
        self._closed = False
        self._abandoned = False
        self._condition = threading.Condition()

    def push(self, line: str) -> None:
        line_bytes = len(line.encode("utf-8", errors="backslashreplace"))
        if line_bytes > self._max_bytes:
            line = (
                f"local log terminal entry exceeded {line_bytes} bytes; "
                "bounded file entry retained\n"
            )
            line_bytes = len(line.encode("utf-8"))
        if line_bytes > self._max_bytes:
            line = "log entry omitted\n"
            line_bytes = len(line.encode("utf-8"))
        if line_bytes > self._max_bytes:
            with self._condition:
                self._dropped += 1
            return
        with self._condition:
            if self._closed or self._abandoned:
                return
            while self._lines and (
                len(self._lines) >= self._max_lines
                or self._buffered_bytes + line_bytes > self._max_bytes
            ):
                _dropped_line, dropped_bytes = self._lines.popleft()
                self._buffered_bytes -= dropped_bytes
                self._dropped += 1
            self._lines.append((line, line_bytes))
            self._buffered_bytes += line_bytes
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def abandon(self) -> None:
        with self._condition:
            self._abandoned = True
            self._lines.clear()
            self._buffered_bytes = 0
            self._condition.notify_all()

    def next_line(self) -> str | None:
        with self._condition:
            while not self._lines and not self._closed and not self._abandoned:
                self._condition.wait()
            if self._abandoned:
                return None
            if self._dropped:
                dropped = self._dropped
                self._dropped = 0
                return (
                    f"local log terminal output dropped {dropped} buffered lines; "
                    "file is complete\n"
                )
            if self._lines:
                line, line_bytes = self._lines.popleft()
                self._buffered_bytes -= line_bytes
                return line
            return None


def _write_terminal(buffer: _TerminalBuffer, done: threading.Event) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    output_fd = sys.stdout.fileno()
    try:
        while (line := buffer.next_line()) is not None:
            payload = line.encode(encoding, errors="backslashreplace")
            written = 0
            while written < len(payload):
                _readable, writable, _exceptional = select.select(
                    [],
                    [output_fd],
                    [],
                    _TERMINAL_DRAIN_SECONDS,
                )
                if not writable:
                    buffer.abandon()
                    return
                written += os.write(output_fd, payload[written : written + 4_096])
    except OSError:
        buffer.abandon()
    finally:
        done.set()


def _render_line(raw: str, output_format: str) -> str:
    line = raw.rstrip("\n")
    if output_format != "json-plain":
        return line
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(payload, dict):
        return line
    level = payload.get("level")
    logger = payload.get("logger")
    message = payload.get("message")
    if not all(isinstance(value, str) for value in (level, logger, message)):
        return line
    rendered = f"{level}: {logger}: {message}"
    context = [
        f"{field}={json.dumps(payload[field], ensure_ascii=True, separators=(',', ':'))}"
        for field in _PLAIN_CONTEXT_FIELDS
        if isinstance(payload.get(field), (str, int, float, bool))
    ]
    if context:
        rendered = f"{rendered} [{', '.join(context)}]"
    exception = payload.get("exception")
    if isinstance(exception, str) and exception:
        rendered = f"{rendered}\n{exception}"
    return rendered


def _timestamp_lines(rendered: str, captured_at: str) -> str:
    return "\n".join(f"{captured_at} {line}" for line in rendered.split("\n"))


def _bound_entry(entry: str, max_bytes: int) -> str:
    encoded = entry.encode("utf-8")
    if len(encoded) <= max_bytes:
        return entry
    suffix = _ENTRY_TRUNCATION_SUFFIX.encode("utf-8")
    if max_bytes <= len(suffix):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    prefix = encoded[: max_bytes - len(suffix)].decode("utf-8", errors="ignore")
    return prefix + _ENTRY_TRUNCATION_SUFFIX


def _local_log_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _open_log(path: Path) -> TextIO:
    path.touch(exist_ok=True)
    os.chmod(path, 0o600)
    return path.open("a", encoding="utf-8", buffering=1)


def _rotate(path: Path, handle: TextIO, backup_count: int) -> TextIO:
    handle.flush()
    handle.close()
    Path(f"{path}.{backup_count}").unlink(missing_ok=True)
    for generation in range(backup_count, 1, -1):
        previous = Path(f"{path}.{generation - 1}")
        if previous.exists():
            previous.replace(Path(f"{path}.{generation}"))
    path.replace(Path(f"{path}.1"))
    return _open_log(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--format", choices=("raw", "json-plain"), default="raw")
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--backup-count", type=int, required=True)
    args = parser.parse_args()

    handle = _open_log(args.log_file)
    current_bytes = args.log_file.stat().st_size
    terminal_buffer = _TerminalBuffer(_TERMINAL_BUFFER_LINES, _TERMINAL_BUFFER_BYTES)
    terminal_done = threading.Event()
    terminal_thread = threading.Thread(
        target=_write_terminal,
        args=(terminal_buffer, terminal_done),
        name="fdai-local-log-terminal",
        daemon=True,
    )
    terminal_thread.start()
    try:
        for raw in sys.stdin:
            rendered = _render_line(raw, args.format)
            entry = f"{_timestamp_lines(rendered, _local_log_timestamp())}\n"
            entry = _bound_entry(entry, args.max_bytes)
            entry_bytes = len(entry.encode("utf-8"))
            if current_bytes > 0 and current_bytes + entry_bytes > args.max_bytes:
                handle = _rotate(args.log_file, handle, args.backup_count)
                current_bytes = 0
            handle.write(entry)
            current_bytes += entry_bytes
            terminal_buffer.push(raw)
    finally:
        handle.close()
        terminal_buffer.close()
        terminal_done.wait(_TERMINAL_DRAIN_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
