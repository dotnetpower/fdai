"""Descriptor-safe writes for private deployment CLI artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def write_private_output(path: Path, content: str) -> None:
    """Create one mode-0600 artifact through a held mode-0700 parent."""

    write_private_bytes(path, content.encode("utf-8"))


def write_private_bytes(path: Path, content: bytes) -> None:
    """Exclusively persist binary content through a held private parent."""

    directory = _open_private_parent(path)
    try:
        descriptor = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(path.name, dir_fd=directory)
            raise
    finally:
        os.close(directory)


def read_private_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read bounded current-UID mode-0600 content without following any symlink."""

    if max_bytes <= 0:
        raise ValueError("private input size bound MUST be positive")
    directory = _open_private_parent(path)
    try:
        descriptor = os.open(
            path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            details = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o600
                or details.st_uid != os.geteuid()
                or details.st_nlink != 1
            ):
                raise PermissionError(
                    "private input MUST be a current-UID mode-0600 single-link file"
                )
            if not 0 < details.st_size <= max_bytes:
                raise ValueError("private input is empty or exceeds its size limit")
            content = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            if (
                len(content) != details.st_size
                or after.st_size != details.st_size
                or after.st_mtime_ns != details.st_mtime_ns
                or after.st_ctime_ns != details.st_ctime_ns
            ):
                raise ValueError("private input changed while being read")
            return content
    finally:
        os.close(directory)


def _open_private_parent(path: Path) -> int:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ValueError("private output path MUST be an absolute file path")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    trusted_owners = {0, os.geteuid()}
    try:
        for part in path.parent.parts[1:]:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ValueError("private output path MUST NOT traverse parent directories")
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            details = os.fstat(child)
            if details.st_uid not in trusted_owners:
                os.close(child)
                raise PermissionError("private output path has an unsafe owner")
            mode = stat.S_IMODE(details.st_mode)
            if mode & 0o022 and not details.st_mode & stat.S_ISVTX:
                os.close(child)
                raise PermissionError("private output path has a replaceable ancestor")
            os.close(descriptor)
            descriptor = child
        details = os.fstat(descriptor)
        if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o700:
            raise PermissionError("private output directory MUST be current-UID mode 0700")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise
