"""Pin operator-selected Git inputs without claiming release signature trust."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fdai_deployment_cli.contracts import canonical_digest

_COMMIT = re.compile(r"[0-9a-f]{40}")
_MAX_FILES = 65_536
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceDeploymentInput:
    """Exact source identity; a local content pin, not publisher trust or approval."""

    root: Path
    commit: str
    tree: str
    content_digest: str
    file_count: int

    @property
    def digest(self) -> str:
        """Bind portable source evidence without exposing the local checkout path."""
        return canonical_digest(self.to_mapping())

    def to_mapping(self) -> dict[str, object]:
        """Return secret-free provenance for reviews and retained source runs."""
        return {
            "schema_version": "fdai.source-deployment-input.v1",
            "provenance": "operator-selected-source",
            "source_commit": self.commit,
            "source_tree": self.tree,
            "content_digest": self.content_digest,
            "file_count": self.file_count,
            "release_signature_verified": False,
        }

    def reverify(self) -> None:
        """Reject changed source before another build, transfer, or deployment effect."""
        if inspect_source(self.root, expected_commit=self.commit) != self:
            raise ValueError("source deployment inputs changed; preserve the existing run")


def inspect_source(root: Path, *, expected_commit: str | None = None) -> SourceDeploymentInput:
    """Verify a complete clean checkout against raw Git blobs, without executing its code.

    Git clean filters and index flags cannot hide raw content changes. External links,
    submodules, hardlinks, untracked files and oversized inputs are rejected. Ignored
    files are never part of the evidence and must not enter a later build snapshot.
    """
    if root.is_symlink():
        raise ValueError("source deployment requires a non-symlink checkout root")
    root = root.resolve(strict=True)
    if _git(root, "rev-parse", "--show-toplevel").decode().strip() != str(root):
        raise ValueError("source deployment must select the checkout root")
    commit = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    if _COMMIT.fullmatch(commit) is None or expected_commit not in {None, commit}:
        raise ValueError("source deployment revision differs from the selected commit")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("source deployment requires a clean committed checkout")
    tree = _git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    entries = _git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0")[:-1]
    if not 0 < len(entries) <= _MAX_FILES:
        raise ValueError("source deployment file inventory is empty or exceeds its bound")
    tracked = {entry.split(b"\t", 1)[1].decode("utf-8") for entry in entries}
    records: list[dict[str, str]] = []
    total = 0
    for entry in entries:
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, blob_digest = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError("source deployment does not accept external submodules")
        content = _read_tracked(root, path, mode=mode)
        if mode == "120000":
            try:
                resolved = (root / path).resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError, RuntimeError):
                raise ValueError("source link must resolve inside the checkout") from None
            if resolved not in tracked:
                raise ValueError("source link target must be a tracked file")
        total += len(content)
        if total > _MAX_SOURCE_BYTES:
            raise ValueError("source deployment exceeds its total size bound")
        blob = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        if hashlib.sha1(blob, usedforsecurity=False).hexdigest() != blob_digest:
            raise ValueError("source bytes differ from the committed input")
        records.append({"path": path, "mode": mode, "sha256": hashlib.sha256(content).hexdigest()})
    if _git(root, "rev-parse", "HEAD").decode().strip() != commit:
        raise ValueError("source revision changed during inspection")
    return SourceDeploymentInput(
        root, commit, tree, canonical_digest({"files": records}), len(records)
    )


def _read_tracked(root: Path, relative: str, *, mode: str) -> bytes:
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(part in {".", ".."} for part in parts):
        raise ValueError("source input path is invalid")
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        if mode == "120000":
            before_link = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            target = os.readlink(parts[-1], dir_fd=parent)
            after_link = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if before_link != after_link or Path(target).is_absolute():
                raise ValueError("source link changed or has an absolute target")
            return os.fsencode(target)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_size > _MAX_FILE_BYTES
                or bool(before.st_mode & stat.S_IXUSR) != (mode == "100755")
            ):
                raise ValueError("source input type, mode, or size is invalid")
            content = stream.read(_MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (
                len(content) != before.st_size
                or after.st_size != before.st_size
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns
            ):
                raise ValueError("source input changed during inspection")
            return content
    finally:
        os.close(parent)


def _git(root: Path, *arguments: str) -> bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(
            "source checkout could not be verified; no deployment was started"
        ) from None
    if len(result.stdout) > 16 * 1024 * 1024:
        raise ValueError("source Git response exceeds its size bound")
    return result.stdout
