"""Private filesystem state primitives for standalone deployment checkpoints."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_deployment_cli.private_output import read_private_bytes, write_private_output


def private_json(path: Path, label: str) -> dict[str, Any]:
    """Read one bounded private JSON object through descriptor-safe I/O."""
    try:
        value = json.loads(read_private_bytes(path, max_bytes=4 * 1024 * 1024))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(  # noqa: TRY004 - normalize untrusted JSON into a stable CLI error
            f"{label} is invalid"
        )
    return {str(key): item for key, item in value.items()}


def replace_private_json(path: Path, value: dict[str, object]) -> None:
    """Atomically replace one private JSON object without reusing a temporary path."""
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    published = False
    try:
        write_private_output(
            temporary,
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        )
        os.replace(temporary, path)
        path.chmod(0o600)
        published = True
    finally:
        if not published:
            temporary.unlink(missing_ok=True)


def replace_or_verify_private_json(path: Path, value: dict[str, object]) -> None:
    """Create one private JSON object or verify its exact retained value."""
    if path.exists():
        if private_json(path, path.name) != value:
            raise ValueError(f"retained {path.name} differs")
        return
    replace_private_json(path, value)


def file_digest(path: Path) -> str:
    """Hash one bounded private artifact without following symlinks."""
    return hashlib.sha256(read_private_bytes(path, max_bytes=512 * 1024 * 1024)).hexdigest()


def executable_digest(path: Path) -> str:
    """Hash one current-UID immutable executable through a held descriptor."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        mode = stat.S_IMODE(details.st_mode)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or not mode & stat.S_IXUSR
            or mode & 0o022
            or details.st_size > 512 * 1024 * 1024
        ):
            raise PermissionError("verified executable permissions are invalid")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def private_directory(path: Path) -> None:
    """Require one absolute current-UID mode-0700 directory."""
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.geteuid()
    ):
        raise PermissionError("standalone host work directory must be current-UID mode 0700")


def acquire_checkpoint_lock(work_dir: Path) -> int:
    """Acquire one nonblocking lock for all stateful managed-host checkpoints."""
    directory = os.open(work_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(
            ".checkpoint.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    details = os.fstat(descriptor)
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        os.close(descriptor)
        raise PermissionError("standalone checkpoint lock is not a private regular file")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise ValueError("another standalone checkpoint is already running") from exc
    return descriptor


def absolute(path: Path) -> Path:
    """Resolve a CLI path relative to the current working directory without dereferencing it."""
    return path if path.is_absolute() else Path.cwd() / path


def moment(value: datetime) -> str:
    """Render one UTC instant in the stable machine format."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_moment(value: str) -> datetime:
    """Parse one timezone-aware approval instant and normalize it to UTC."""
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("approval expiry is invalid") from exc
    if result.tzinfo is None:
        raise ValueError("approval expiry is invalid")
    return result.astimezone(UTC)
