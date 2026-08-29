"""Bounded descriptor-based key reads for release utilities."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_MAX_KEY_BYTES = 65_536


def read_key_file(path: Path, *, private: bool) -> bytes:
    """Read one regular key file without following links or blocking on special files."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("key input MUST be a regular file")
        if details.st_size > _MAX_KEY_BYTES:
            raise ValueError("key input MUST be within 65536 bytes")
        if private and (details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) != 0o600):
            raise PermissionError("private key MUST be current-UID mode 0600")
        payload = stream.read(_MAX_KEY_BYTES + 1)
    if len(payload) > _MAX_KEY_BYTES:
        raise ValueError("key input MUST be within 65536 bytes")
    return payload
