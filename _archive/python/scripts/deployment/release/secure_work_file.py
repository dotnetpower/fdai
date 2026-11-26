#!/usr/bin/env python3
"""Create or safely replace one file in a private release work directory."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

_MAX_INPUT_BYTES = 1024 * 1024


def write_work_file(path: Path, payload: bytes, *, mode: int, replace: bool) -> None:
    """Write one bounded file through a held private-parent descriptor."""

    if len(payload) > _MAX_INPUT_BYTES:
        raise ValueError("release work file exceeds 1048576 bytes")
    with open_work_file(path, mode=mode, replace=replace) as stream:
        stream.write(payload)


@contextmanager
def open_work_file(path: Path, *, mode: int, replace: bool) -> Iterator[BinaryIO]:
    """Open one exclusive output while holding its validated parent descriptor."""

    if mode not in {0o600, 0o644}:
        raise ValueError("release work file mode is unsupported")
    directory = _open_parent(path)
    try:
        if replace:
            _unlink(path.name, directory=directory, missing_ok=True)
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                yield stream
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            _unlink(path.name, directory=directory, missing_ok=True)
            raise
    finally:
        os.close(directory)


def remove_work_file(path: Path, *, missing_ok: bool) -> None:
    """Remove only the final entry through its validated parent descriptor."""

    directory = _open_parent(path)
    try:
        _unlink(path.name, directory=directory, missing_ok=missing_ok)
    finally:
        os.close(directory)


def _open_parent(path: Path) -> int:
    if path.name in {"", ".", ".."}:
        raise ValueError("release work filename is invalid")
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    details = os.fstat(descriptor)
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
        os.close(descriptor)
        raise PermissionError("release work directory MUST be current-UID mode 0700")
    return descriptor


def _unlink(name: str, *, directory: int, missing_ok: bool) -> None:
    try:
        os.unlink(name, dir_fd=directory)
    except FileNotFoundError:
        if not missing_ok:
            raise


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
