"""Compare persistent Foundation execution sources while retaining exact local state paths."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from fdai_deployment_cli.private_output import _open_private_parent, read_private_bytes

_STATE_PATHS = frozenset(
    {
        "infra/genesis-foundation/terraform.tfstate",
        "infra/genesis-foundation/terraform.tfstate.backup",
    }
)
_MAX_FILE_BYTES = 64 * 1024 * 1024


def _read_immutable_file(path: Path) -> bytes:
    """Allow empty authenticated source files without relaxing private-file identity."""
    parent = _open_private_parent(path)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_size > _MAX_FILE_BYTES
            ):
                raise ValueError("Foundation immutable source file identity is invalid")
            data = stream.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (
                len(data) != before.st_size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                raise ValueError("Foundation immutable source changed during verification")
            return data
    finally:
        os.close(parent)


def verify_execution_copy(root: Path, *, authenticated_source: Path) -> None:
    """Match every immutable byte to a freshly verified bundle without deleting state.

    Only the two exact local state paths may be additional private regular files.
    State is recovery data, never authenticated bundle source or permission to apply.
    Manifest, signature, SBOM, HCL, scripts, and all other file membership stay exact.
    """
    expected = {
        path.relative_to(authenticated_source).as_posix(): path
        for path in authenticated_source.rglob("*")
        if path.is_file()
    }
    if not expected or _STATE_PATHS.intersection(expected):
        raise ValueError("Foundation authenticated source inventory is invalid")
    observed: set[str] = set()
    total = 0
    try:
        for directory, directories, names in os.walk(root, followlinks=False):
            base = Path(directory)
            for path in (base, *(base / name for name in directories)):
                details = path.lstat()
                if (
                    not stat.S_ISDIR(details.st_mode)
                    or details.st_uid != os.geteuid()
                    or details.st_mode & 0o077
                ):
                    raise ValueError("Foundation execution directories must remain private")
            for name in names:
                path = base / name
                relative = path.relative_to(root).as_posix()
                if relative not in expected and relative not in _STATE_PATHS:
                    raise ValueError("Foundation execution copy has an undeclared source file")
                data = (
                    _read_immutable_file(path)
                    if relative in expected
                    else read_private_bytes(path, max_bytes=_MAX_FILE_BYTES)
                )
                total += len(data)
                if total > 1024 * 1024 * 1024:
                    raise ValueError("Foundation execution copy exceeds its size bound")
                if relative in expected:
                    if data != expected[relative].read_bytes():
                        raise ValueError("Foundation execution source differs from its bundle")
                    observed.add(relative)
    except OSError:
        raise ValueError("Foundation execution copy is unavailable; preserve state") from None
    if observed != set(expected):
        raise ValueError("Foundation execution copy is missing signed source files")
