#!/usr/bin/env python3
"""Create or verify private release work directories by held descriptors."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

_MAX_SENTINEL_BYTES = 128


class WorkdirGuardError(RuntimeError):
    """A release work directory is unsafe or not owned by this process."""


def create_owned_workdir(path: Path, *, sentinel: str, value: str) -> None:
    """Create a private directory and sentinel without following their final components."""

    _require_nonreplaceable_parent_chain(path)
    os.mkdir(path, 0o700)
    directory = _open_owned_directory(path)
    try:
        descriptor = os.open(
            sentinel,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(directory)


def verify_owned_workdir(path: Path, *, sentinel: str, value: str) -> None:
    """Verify directory and sentinel ownership, modes, type, and bounded content."""

    _require_nonreplaceable_parent_chain(path)
    directory = _open_owned_directory(path)
    try:
        descriptor = os.open(
            sentinel,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as stream:
            details = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) != 0o600
                or details.st_size > _MAX_SENTINEL_BYTES
            ):
                raise WorkdirGuardError("release workdir sentinel is unsafe")
            content = stream.read(_MAX_SENTINEL_BYTES + 1)
        if content != (value + "\n").encode("ascii"):
            raise WorkdirGuardError("release workdir sentinel does not match")
    finally:
        os.close(directory)


def _open_owned_directory(path: Path) -> int:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    details = os.fstat(descriptor)
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
        os.close(descriptor)
        raise WorkdirGuardError("release workdir MUST be owned by the current UID with mode 0700")
    return descriptor


def _require_nonreplaceable_parent_chain(path: Path) -> None:
    current = path.parent
    while True:
        details = current.lstat()
        if not stat.S_ISDIR(details.st_mode):
            raise WorkdirGuardError("release workdir parent chain MUST contain only directories")
        if details.st_uid not in {0, os.geteuid()}:
            raise WorkdirGuardError("release workdir parent chain has an unsafe owner")
        mode = stat.S_IMODE(details.st_mode)
        if mode & 0o022 and not (details.st_mode & stat.S_ISVTX):
            raise WorkdirGuardError("release workdir parent chain is replaceable")
        if current == current.parent:
            return
        current = current.parent


def main(argv: list[str] | None = None) -> int:
    """Run the guard without printing path or sentinel content."""

    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--sentinel", required=True)
    parser.add_argument("--value", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            create_owned_workdir(args.path, sentinel=args.sentinel, value=args.value)
        else:
            verify_owned_workdir(args.path, sentinel=args.sentinel, value=args.value)
    except (OSError, UnicodeError, WorkdirGuardError) as exc:
        print(f"workdir guard failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
