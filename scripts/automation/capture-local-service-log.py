#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO


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
    exception = payload.get("exception")
    if isinstance(exception, str) and exception:
        rendered = f"{rendered}\n{exception}"
    return rendered


def _timestamp_lines(rendered: str, captured_at: str) -> str:
    return "\n".join(f"{captured_at} {line}" for line in rendered.split("\n"))


def _open_log(path: Path) -> TextIO:
    path.touch(exist_ok=True)
    os.chmod(path, 0o600)
    return path.open("a", encoding="utf-8", buffering=1)


def _rotate(path: Path, handle: TextIO, max_bytes: int) -> TextIO:
    handle.flush()
    if path.stat().st_size < max_bytes:
        return handle
    handle.close()
    rotated = Path(f"{path}.1")
    rotated.unlink(missing_ok=True)
    path.replace(rotated)
    return _open_log(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--format", choices=("raw", "json-plain"), default="raw")
    parser.add_argument("--max-bytes", type=int, required=True)
    args = parser.parse_args()

    handle = _open_log(args.log_file)
    lines_since_check = 0
    try:
        for raw in sys.stdin:
            sys.stdout.write(raw)
            sys.stdout.flush()
            captured_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
            rendered = _render_line(raw, args.format)
            handle.write(_timestamp_lines(rendered, captured_at))
            handle.write("\n")
            lines_since_check += 1
            if lines_since_check >= 100:
                handle = _rotate(args.log_file, handle, args.max_bytes)
                lines_since_check = 0
    finally:
        handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
