"""Secure local persistence for secret-free provisioning profiles."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from fdai_deployment_cli.contracts import ProvisionProfile, canonical_bytes, load_json_object


def write_profile(path: Path, profile: ProvisionProfile, *, force: bool = False) -> None:
    """Create a private profile atomically without following links."""

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _require_private_directory(parent)
    if path.exists() or path.is_symlink():
        if not force:
            raise FileExistsError("provision profile already exists")
        _require_regular_private_file(path)
    temporary = parent / f".{path.name}.tmp-{os.getpid()}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(profile.to_mapping()) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        _publish_profile(temporary, path, force=force)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_profile(temporary: Path, destination: Path, *, force: bool) -> None:
    if force:
        os.replace(temporary, destination)
        return
    os.link(temporary, destination, follow_symlinks=False)
    temporary.unlink()


def load_profile(path: Path) -> ProvisionProfile:
    """Read and validate a private regular-file profile."""

    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise PermissionError("provision profile MUST be a mode-0600 regular file")
        payload = stream.read(1_048_577)
    return ProvisionProfile.from_mapping(load_json_object(payload, label="provision profile"))


def _require_private_directory(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o700:
        raise PermissionError("provision profile directory MUST have mode 0700")


def _require_regular_private_file(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode):
        raise PermissionError("provision profile MUST be a regular file")
    if stat.S_IMODE(details.st_mode) != 0o600:
        raise PermissionError("provision profile MUST have mode 0600")
