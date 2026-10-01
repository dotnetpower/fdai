"""Content identity of the inputs that a changed-test shard pass depends on.

The identity covers every tracked and untracked, non-ignored working-tree file
and the installed bytes of the project environment that `uv run` selects, which
the structural runner's installed-environment digest computes without the
bytecode caches that tests write. It is read from actual bytes, not from Git stat
caches, so an edit, a new or deleted file, a lock-file change, or a different
installed distribution or interpreter changes it.

A separate stability digest of the working-tree files' status times is never
bound to a pass. The runner compares it before and after the shards so a
working-tree change that was reverted while they ran still prevents a pass from
being recorded. Installed files have no such digest: uv hard-links them from its
cache, so another checkout's sync changes their status times.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.automation.local_validation_inputs import installed_digest


@dataclass(frozen=True)
class InputIdentity:
    """Bound content identities plus the status digest that proves they were stable."""

    worktree: str
    environment: str
    stability: str

    @property
    def bound(self) -> tuple[str, str]:
        """Return the identities a recorded pass binds."""
        return self.worktree, self.environment


def worktree_digests(root: Path, excluded: tuple[Path, ...]) -> tuple[str, str]:
    """Hash the content and status of every tracked and untracked, non-ignored file."""

    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout
    content = hashlib.sha256()
    status = hashlib.sha256()
    for raw_path in sorted(set(listed.split(b"\0")) - {b""}):
        path = root / os.fsdecode(raw_path)
        if any(path.is_relative_to(prefix) for prefix in excluded):
            continue
        content.update(raw_path + b"\0")
        status.update(raw_path + b"\0")
        try:
            attributes = path.lstat()
        except FileNotFoundError:
            content.update(b"missing\0")
            status.update(b"missing\0")
            continue
        status.update(
            f"{attributes.st_ino}\0{attributes.st_mtime_ns}\0{attributes.st_ctime_ns}\0".encode()
        )
        if stat.S_ISLNK(attributes.st_mode):
            content.update(b"link\0" + os.fsencode(os.readlink(path)) + b"\0")
        elif stat.S_ISREG(attributes.st_mode):
            mode = b"x" if attributes.st_mode & stat.S_IXUSR else b"-"
            content.update(b"file\0" + mode + hashlib.sha256(path.read_bytes()).digest())
        else:
            content.update(b"other\0")
    return content.hexdigest(), status.hexdigest()


def environment_digest(root: Path, environment: dict[str, str]) -> str:
    """Hash the installed bytes of the environment `uv run` uses, without bytecode caches.

    An environment without an interpreter has a distinct ``absent`` identity.
    """

    configured = environment.get("UV_PROJECT_ENVIRONMENT", "")
    venv = Path(configured) if configured else root / ".venv"
    if not venv.is_absolute():
        venv = Path.cwd() / venv
    if not (venv / "bin" / "python").is_file():
        return "absent"
    return installed_digest(venv, skip_bytecode=True)


def input_identity(environment: dict[str, str], excluded: tuple[Path, ...]) -> InputIdentity | None:
    """Return the current input identity, or None when it cannot be computed."""

    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.strip()
        root = Path(top).resolve()
        worktree, stability = worktree_digests(root, tuple(path.resolve() for path in excluded))
        return InputIdentity(worktree, environment_digest(root, environment), stability)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
