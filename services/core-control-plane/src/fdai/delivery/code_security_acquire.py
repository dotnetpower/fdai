"""Acquire the exact revision of a repository for scanning (``code-acquire``).

The acquirer fetches one commit by its full id into a private bare repository, verifies that the
fetched commit is exactly the requested one, and extracts its tree (without ``.git``) into a
content-addressed directory that is then made read-only. Analysis never touches the network or
credentials; only this step does, and credentials reach git through environment-only
configuration so they never appear in argv, logs, or the extracted tree.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_MAX_ARCHIVE_BYTES = 2 * 1024**3


class SourceAcquisitionError(RuntimeError):
    """Raised when the exact revision cannot be acquired; nothing is scanned."""


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    path: Path
    revision: str
    tree_id: str


class GitSourceAcquirer:
    """Fetch and extract one exact commit under ``work_root``.

    ``auth_header`` returns an HTTP ``Authorization`` header value (for example a GitHub App
    installation token in Basic form) or ``None`` for unauthenticated or local repositories.
    """

    def __init__(
        self,
        work_root: Path,
        *,
        auth_header: Callable[[], str | None] | None = None,
        timeout_seconds: int = 600,
    ) -> None:
        self._root = work_root
        self._auth_header = auth_header
        self._timeout = timeout_seconds

    def _git(
        self, cwd: Path, *args: str, stdout_bytes: bool = False
    ) -> subprocess.CompletedProcess[Any]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "GIT_TERMINAL_PROMPT": "0"}
        env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": str(cwd)})
        header = self._auth_header() if self._auth_header else None
        if header:
            env.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"Authorization: {header}",
                }
            )
        proc = subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ["git", "-C", str(cwd), *args],  # noqa: S607 - git resolved from PATH by design
            capture_output=True,
            env=env,
            timeout=self._timeout,
            check=False,
            text=not stdout_bytes,
        )
        if proc.returncode != 0:
            stderr = proc.stderr if isinstance(proc.stderr, str) else proc.stderr.decode("replace")
            raise SourceAcquisitionError(f"git {args[0]} failed: {stderr.strip()[:300]}")
        return proc

    def acquire(self, repository: str, revision: str) -> AcquiredSource:
        """Return a read-only extraction of ``revision`` from ``repository``."""
        if _REVISION.fullmatch(revision) is None:
            raise SourceAcquisitionError("revision must be a full lowercase commit id")
        if not repository or repository.startswith("-") or "\x00" in repository:
            raise SourceAcquisitionError("repository location is invalid")
        target = self._root / "sources" / revision
        if target.exists():
            tree_file = self._root / "sources" / f"{revision}.tree"
            if tree_file.exists():
                return AcquiredSource(target, revision, tree_file.read_text().strip())
            _make_writable(target)
            shutil.rmtree(target)
        bare = self._root / "fetch" / revision
        if bare.exists():
            shutil.rmtree(bare)
        bare.mkdir(parents=True, mode=0o700)
        self._git(bare, "init", "--bare", "-q")
        self._git(bare, "fetch", "--depth=1", "--no-tags", "--", repository, revision)
        fetched = self._git(bare, "rev-parse", "--verify", "FETCH_HEAD^{commit}").stdout.strip()
        if fetched != revision:
            raise SourceAcquisitionError("fetched commit does not match the requested revision")
        tree_id = self._git(bare, "rev-parse", f"{revision}^{{tree}}").stdout.strip()
        archive = self._git(bare, "archive", "--format=tar", revision, stdout_bytes=True).stdout
        if len(archive) > _MAX_ARCHIVE_BYTES:
            raise SourceAcquisitionError("source archive exceeds the size limit")
        target.mkdir(parents=True, mode=0o700)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            bundle.extractall(target, filter="data")
        _make_read_only(target)
        (self._root / "sources" / f"{revision}.tree").write_text(tree_id + "\n")
        shutil.rmtree(bare)
        return AcquiredSource(target, revision, tree_id)


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    root.chmod(root.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _make_writable(root: Path) -> None:
    root.chmod(root.stat().st_mode | stat.S_IWUSR)
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


__all__ = ["AcquiredSource", "GitSourceAcquirer", "SourceAcquisitionError"]
