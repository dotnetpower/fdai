"""Confined POSIX local review I/O; no symlink traversal, network fallback or overwrites."""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

from .review_contracts import ReviewError, relative_path


def _constant(value: str) -> NoReturn:
    raise ReviewError("review JSON requires finite numbers")


def _number(value: str) -> int | float:
    if len(value) > 64:
        raise ReviewError("review JSON numeric token exceeds its limit")
    if "." not in value and "e" not in value.lower():
        return int(value)
    result = float(value)
    nonzero = any(digit in "123456789" for digit in value.lower().partition("e")[0])
    if not math.isfinite(result) or (result == 0 and nonzero):
        raise ReviewError("review JSON number overflows or underflows")
    return result


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewError("review JSON contains duplicate keys")
        result[key] = value
    return result


def decode_json(content: bytes, maximum: int) -> object:
    """Decode duplicate-free bounded JSON, limiting depth and containers before allocation."""
    if not 0 < len(content) <= maximum:
        raise ReviewError("review JSON exceeds its byte limit")
    try:
        text = content.decode("utf-8")
        depth = tokens = 0
        quoted = escaped = False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                tokens += 1
            elif char in "]}":
                depth -= 1
            elif char in ",:":
                tokens += 1
            if not 0 <= depth <= 32 or tokens > 500_000:
                raise ReviewError("review JSON exceeds its structural limit")
        return json.loads(
            text,
            object_pairs_hook=_object,
            parse_constant=_constant,
            parse_int=_number,
            parse_float=_number,
        )
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise ReviewError("review input must be bounded duplicate-free UTF-8 JSON") from None


@contextmanager
def directory(path: Path) -> Iterator[int]:
    """Pin every directory component without resolving the selected root through links."""
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if len(parts) > 64 or ".." in parts or len(os.fsencode(path)) > 4096:
        raise ReviewError("review root path exceeds its bounds or traverses a parent")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    current = os.open("/" if path.is_absolute() else ".", flags)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


@contextmanager
def parent(root: int, relative: str) -> Iterator[tuple[int, str]]:
    """Open a canonical relative parent under one pinned root without following any links."""
    relative_path(relative)
    parts = relative.split("/")
    current = os.dup(root)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = child
        yield current, parts[-1]
    finally:
        os.close(current)


def read_file(root: int, path: str, maximum: int) -> bytes:
    """Read one stable, regular, singly linked file within a caller-owned byte allowance."""
    with parent(root, path) as (base, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=base)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ReviewError("review input must be a regular file without links")
            if not 0 < before.st_size <= maximum:
                raise ReviewError("review input exceeds the available byte budget")
            data = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            if (len(data), after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
                before.st_size,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ):
                raise ReviewError("review input changed while reading")
            return data


def write_file(root: int, path: str, content: bytes) -> None:
    """Create a private exclusive file; I/O failure never becomes a successful review receipt."""
    with parent(root, path) as (base, name):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=base)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            if stream.write(content) != len(content):
                raise ReviewError("review output write was incomplete")
            stream.flush()
            os.fsync(stream.fileno())


@contextmanager
def new_directory(path: Path) -> Iterator[int]:
    """Reserve a fresh private output directory and retain partial evidence on failure."""
    relative_path(path.name)
    with directory(path.parent) as base:
        os.mkdir(path.name, 0o700, dir_fd=base)
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
        try:
            os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)
