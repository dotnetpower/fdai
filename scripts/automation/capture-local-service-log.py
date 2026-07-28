#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO

_PLAIN_CONTEXT_FIELDS = ("topic", "consumer_group", "client_id", "auth_mechanism")


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
    try:
        for raw in sys.stdin:
            sys.stdout.write(raw)
            sys.stdout.flush()
            rendered = _render_line(raw, args.format)
            entry = f"{_timestamp_lines(rendered, _local_log_timestamp())}\n"
            handle.flush()
            current_bytes = args.log_file.stat().st_size
            entry_bytes = len(entry.encode("utf-8"))
            if current_bytes > 0 and current_bytes + entry_bytes > args.max_bytes:
                handle = _rotate(args.log_file, handle, args.backup_count)
            handle.write(entry)
    finally:
        handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
