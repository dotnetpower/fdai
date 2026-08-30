"""Owner-only append ledger for local Pantheon diagnostic campaigns."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, TextIO

_MAX_LINE_BYTES: Final = 256 * 1024
_MAX_LEDGER_BYTES: Final = 64 * 1024 * 1024


class PrivateJsonlLedger:
    """Append bounded JSON records with owner-only permissions and no symlink following."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: Mapping[str, object]) -> None:
        """Append one durable record atomically or leave the file unchanged."""

        payload = (
            json.dumps(dict(record), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            + "\n"
        ).encode()
        if len(payload) > _MAX_LINE_BYTES:
            raise ValueError("diagnostic ledger record exceeds the byte limit")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory_descriptor = _open_directory_chain(self.path.parent)
        os.fchmod(directory_descriptor, stat.S_IRWXU)
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(
                self.path.name,
                flags,
                stat.S_IRUSR | stat.S_IWUSR,
                dir_fd=directory_descriptor,
            )
        except OSError as error:
            os.close(directory_descriptor)
            if error.errno == errno.ELOOP:
                raise ValueError("diagnostic ledger path MUST NOT be a symlink") from error
            raise
        try:
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            original_size = os.lseek(descriptor, 0, os.SEEK_END)
            if original_size + len(payload) > _MAX_LEDGER_BYTES:
                raise ValueError("diagnostic ledger exceeds the byte limit")
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("diagnostic ledger append made no progress")
                    remaining = remaining[written:]
                os.fsync(descriptor)
            except BaseException:
                os.ftruncate(descriptor, original_size)
                os.fsync(descriptor)
                raise
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            os.close(directory_descriptor)

    def read(self, *, limit: int = 1_000) -> tuple[dict[str, Any], ...]:
        """Read the newest bounded records without following a symlink."""

        if not 1 <= limit <= 10_000:
            raise ValueError("diagnostic ledger read limit MUST be in [1, 10000]")
        if not self.path.exists():
            return ()
        directory_descriptor = _open_directory_chain(self.path.parent)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        records: list[dict[str, Any]] = []
        try:
            descriptor = os.open(self.path.name, flags, dir_fd=directory_descriptor)
            if os.fstat(descriptor).st_size > _MAX_LEDGER_BYTES:
                raise ValueError("diagnostic ledger exceeds the byte limit")
            with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
                for line in stream:
                    if len(line.encode()) > _MAX_LINE_BYTES:
                        raise ValueError("diagnostic ledger record exceeds the byte limit")
                    raw = json.loads(line)
                    if not isinstance(raw, Mapping):
                        raise ValueError("diagnostic ledger record MUST be an object")
                    records.append({str(key): value for key, value in raw.items()})
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory_descriptor)
        return tuple(records[-limit:])


def _open_directory_chain(path: Path) -> int:
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            flags = os.O_RDONLY | os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def open_private_lock(path: Path) -> TextIO | None:
    """Open one owner-only lock without following its directory chain or leaf."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory_descriptor = _open_directory_chain(path.parent)
    os.fchmod(directory_descriptor, stat.S_IRWXU)
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(
            path.name,
            flags,
            stat.S_IRUSR | stat.S_IWUSR,
            dir_fd=directory_descriptor,
        )
    finally:
        os.close(directory_descriptor)
    os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
    handle = os.fdopen(descriptor, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def read_private_text(path: Path, *, max_bytes: int) -> str:
    """Read one owner-only regular file without path-based TOCTOU races."""

    if max_bytes < 1:
        raise ValueError("private file byte limit MUST be positive")
    directory_descriptor = _open_directory_chain(path.parent)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("private file MUST be regular and owner-only")
        if metadata.st_size > max_bytes:
            raise ValueError("private file exceeds the byte limit")
        with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
            return stream.read(max_bytes + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_descriptor)


def private_marker_exists(path: Path) -> bool:
    """Check one marker without following parent or leaf symlinks."""

    if not path.parent.exists():
        return False
    directory_descriptor = _open_directory_chain(path.parent)
    try:
        try:
            metadata = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("private marker MUST NOT be a symlink")
        return stat.S_ISREG(metadata.st_mode)
    finally:
        os.close(directory_descriptor)


def touch_private_marker(path: Path) -> None:
    """Create an owner-only marker without following parent or leaf symlinks."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory_descriptor = _open_directory_chain(path.parent)
    os.fchmod(directory_descriptor, stat.S_IRWXU)
    flags = os.O_WRONLY | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(
            path.name,
            flags,
            stat.S_IRUSR | stat.S_IWUSR,
            dir_fd=directory_descriptor,
        )
        try:
            os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_descriptor)


def remove_private_marker(path: Path) -> None:
    """Remove a regular marker without traversing a symlink."""

    if not path.parent.exists():
        return
    directory_descriptor = _open_directory_chain(path.parent)
    try:
        try:
            metadata = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("private marker MUST be a regular file")
        os.unlink(path.name, dir_fd=directory_descriptor)
    finally:
        os.close(directory_descriptor)


__all__ = [
    "PrivateJsonlLedger",
    "open_private_lock",
    "private_marker_exists",
    "read_private_text",
    "remove_private_marker",
    "touch_private_marker",
]
