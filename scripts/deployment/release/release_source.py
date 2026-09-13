"""Fence complete-release assembly to unchanged, exact committed source bytes.

Use in a fresh private detached worktree so ignored caller-local inputs cannot
enter a build. The fingerprint binds tracked file identity and change metadata,
not release authority. A mismatch stops assembly; it never repairs the checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 65536


class SourceDriftError(ValueError):
    """A release source snapshot is unavailable or no longer exact."""


def _git(repo: Path, *args: str) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(  # noqa: S603 - fixed local Git read operations.
            ["git", *args],
            cwd=repo,
            env=environment,
            capture_output=True,
            check=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        raise SourceDriftError("release source read failed; preserve the build") from None
    if len(result.stdout) > 16 * 1024 * 1024:
        raise SourceDriftError("release source inventory exceeds its bound")
    return result.stdout


def _identity(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _read_source(repo: Path, relative: str, mode: str) -> tuple[bytes, tuple[int, ...]]:
    """Read a bounded tracked file through held, non-symlink directory descriptors."""
    parent = os.open(repo, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(relative).parts
        if not parts or relative.startswith("/") or any(part in {".", ".."} for part in parts):
            raise SourceDriftError("release source path is invalid")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        name = parts[-1]
        if mode == "120000":
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            target = os.readlink(name, dir_fd=parent)
            if not (repo / relative).resolve().is_relative_to(repo):
                raise SourceDriftError("release source link leaves the checkout")
            data = os.fsencode(target)
            after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        else:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if (
                    mode not in {"100644", "100755"}
                    or not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size > MAX_FILE_BYTES
                    or bool(before.st_mode & stat.S_IXUSR) != (mode == "100755")
                ):
                    raise SourceDriftError("release source file type, mode, or size is invalid")
                data = stream.read(MAX_FILE_BYTES + 1)
                after = os.fstat(stream.fileno())
        if _identity(before) != _identity(after) or len(data) > MAX_FILE_BYTES:
            raise SourceDriftError("release source changed while being read")
        return data, _identity(after)
    finally:
        os.close(parent)


def require_source(repo: Path, commit: str, fingerprint: str | None = None) -> str:
    """Validate exact HEAD, raw Git blobs and unchanged metadata; return a local pin.

    Call before source-consuming stages and again before success/signing. Git's
    assume-unchanged/skip-worktree flags and clean filters cannot hide byte drift.
    The metadata pin also rejects tracked content changed and later restored.
    Generated ignored build outputs are outside this source pin, not certified by it.
    """
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise SourceDriftError("release source must be a pinned SHA-1 commit")
    repo = repo.resolve(strict=True)
    if _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip() != commit:
        raise SourceDriftError("release source revision changed; preserve the build")
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise SourceDriftError("release source checkout must remain clean")
    entries = _git(repo, "ls-tree", "-rz", "--full-tree", commit).split(b"\0")
    if not 1 < len(entries) <= MAX_FILES + 1:
        raise SourceDriftError("release source inventory is empty or exceeds its bound")
    identity = hashlib.sha256(commit.encode())
    total = 0
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, expected = metadata.decode().split()
        if kind != "blob":
            raise SourceDriftError("release source contains an unsupported external input")
        relative = os.fsdecode(raw_path)
        data, details = _read_source(repo, relative, mode)
        total += len(data)
        if total > MAX_SOURCE_BYTES:
            raise SourceDriftError("release source bytes exceed their bound")
        # Git blob identity uses SHA-1; the assembly fingerprint and kit use SHA-256.
        blob = b"blob " + str(len(data)).encode() + b"\0" + data
        actual = hashlib.sha1(blob, usedforsecurity=False).hexdigest()
        if actual != expected:
            raise SourceDriftError("release source bytes differ from the pinned commit")
        identity.update(json.dumps([relative, expected, details], separators=(",", ":")).encode())
    result = identity.hexdigest()
    if fingerprint is not None and result != fingerprint:
        raise SourceDriftError("release source changed during assembly; preserve the build")
    return result


def main(argv: list[str] | None = None) -> int:
    """Report only a source fingerprint, never file paths or raw Git failure output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-fingerprint")
    args = parser.parse_args(argv)
    try:
        result = require_source(args.repo_root, args.source_commit, args.source_fingerprint)
    except (OSError, ValueError, RuntimeError):
        print("release source verification failed; preserve the incomplete build", file=sys.stderr)
        return 3
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
