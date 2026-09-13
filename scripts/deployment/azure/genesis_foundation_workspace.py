"""Compare persistent Foundation execution sources while retaining exact local state paths."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from fdai_deployment_cli.private_output import read_private_bytes

_STATE_PATHS = frozenset(
    {
        "infra/genesis-foundation/terraform.tfstate",
        "infra/genesis-foundation/terraform.tfstate.backup",
    }
)
_MAX_FILE_BYTES = 64 * 1024 * 1024


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
                data = read_private_bytes(path, max_bytes=_MAX_FILE_BYTES)
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
