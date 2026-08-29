#!/usr/bin/env python3
"""Create or safely replace one file in a private release work directory."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

_MAX_INPUT_BYTES = 1024 * 1024


def write_work_file(path: Path, payload: bytes, *, mode: int, replace: bool) -> None:
    """Write one bounded file through a held private-parent descriptor."""

    if path.name in {"", ".", ".."}:
        raise ValueError("release work filename is invalid")
    if len(payload) > _MAX_INPUT_BYTES:
        raise ValueError("release work file exceeds 1048576 bytes")
    if mode not in {0o600, 0o644}:
        raise ValueError("release work file mode is unsupported")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(directory)
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
            raise PermissionError("release work directory MUST be current-UID mode 0700")
        if replace:
            try:
                os.unlink(path.name, dir_fd=directory)
            except FileNotFoundError:
                pass
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(path.name, dir_fd=directory)
            raise
    finally:
        os.close(directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--mode", choices=("600", "644"), required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
        write_work_file(
            args.path,
            payload,
            mode=int(args.mode, 8),
            replace=args.replace,
        )
    except (OSError, ValueError) as exc:
        print(f"release work file failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
