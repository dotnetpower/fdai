"""Digest-bound source handoff from credential-bearing acquisition to an offline scanner.

The caller retains the manifest digest independently. A digest binds input, not scan completion.
Prepared trees reject links and special files rather than silently changing the acquired revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.review_signal import (
    ReviewSource,
    build_review_package,
)
from fdai.delivery.code_security_acquire import AcquiredSource, SourceAcquisitionError
from fdai.rule_catalog.code_security import Exposure

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_MAX_ENTRIES = 200_000
_MAX_BYTES = 2 * 1024**3
_MAX_MANIFEST_BYTES = 8192
_MANIFEST_KEYS = frozenset(
    {"schema_version", "repository_alias", "revision", "tree_id", "source", "tree_digest"}
)


@dataclass(frozen=True, slots=True)
class PreparedSource:
    acquired: AcquiredSource
    repository_alias: str
    source: ReviewSource
    manifest_digest: str
    tree_digest: str

    def verify_tree(self) -> None:
        if source_tree_digest(self.acquired.path) != self.tree_digest:
            raise SourceAcquisitionError("prepared source contents changed")


def _entries(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise SourceAcquisitionError("prepared source tree must be a real directory")
    found: list[Path] = []
    pending = [root]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            mode = path.lstat().st_mode
            if path.name == ".git":
                raise SourceAcquisitionError("prepared sources cannot contain Git metadata")
            if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise SourceAcquisitionError(
                    "prepared sources cannot contain links or special files"
                )
            found.append(path)
            if len(found) > _MAX_ENTRIES:
                raise SourceAcquisitionError("prepared source exceeds the entry limit")
            if stat.S_ISDIR(mode):
                pending.append(path)
    return sorted(found, key=lambda path: path.relative_to(root).as_posix())


def source_tree_digest(root: Path) -> str:
    """Hash sorted relative names, entry types, executable bits, and bounded file contents."""
    digest = hashlib.sha256()
    total = 0
    for path in _entries(root):
        mode = path.lstat().st_mode
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        if stat.S_ISDIR(mode):
            digest.update(b"directory\0")
            continue
        digest.update(f"file:{mode & 0o111:o}\0".encode("ascii"))
        content = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SourceAcquisitionError("prepared source entry is not a regular file")
            while block := stream.read(1024**2):
                total += len(block)
                if total > _MAX_BYTES:
                    raise SourceAcquisitionError("prepared source exceeds the byte limit")
                content.update(block)
        digest.update(content.digest())
    return digest.hexdigest()


def _private_read_only(root: Path) -> None:
    for path in reversed(_entries(root)):
        mode = path.lstat().st_mode
        path.chmod(0o500 if stat.S_ISDIR(mode) else 0o400 | (mode & 0o100))
    root.chmod(0o500)


def export_prepared_source(
    acquired: AcquiredSource, output: Path, *, repository_alias: str, source: ReviewSource
) -> PreparedSource:
    """Export a private, read-only tree; refuse to replace an existing handoff."""
    if output.exists() or output.is_symlink():
        raise SourceAcquisitionError("prepared output already exists")
    source = ReviewSource(
        kind=source.kind,
        provider=source.provider,
        revision_kind=acquired.revision_kind,
        trigger=source.trigger,
        request_id=source.request_id,
    )
    build_review_package(
        (),
        repository_alias=repository_alias,
        revision=acquired.revision,
        exposure=Exposure.UNKNOWN,
        coverage_complete=False,
        source=source,
    )
    before = source_tree_digest(acquired.path)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(tempfile.mkdtemp(prefix=".prepared-", dir=output.parent))
    try:
        tree = temporary / "source"
        shutil.copytree(acquired.path, tree, symlinks=True)
        after = source_tree_digest(tree)
        if before != after or source_tree_digest(acquired.path) != before:
            raise SourceAcquisitionError("source changed while preparing the handoff")
        # Normalize permissions before hashing, so the exported executable bits are canonical.
        _private_read_only(tree)
        manifest = {
            "schema_version": 1,
            "repository_alias": repository_alias,
            "revision": acquired.revision,
            "tree_id": acquired.tree_id,
            "source": source.as_dict(),
            "tree_digest": source_tree_digest(tree),
        }
        encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
        manifest_path = temporary / "manifest.json"
        manifest_path.write_bytes(encoded)
        manifest_path.chmod(0o400)
        if output.exists() or output.is_symlink():
            raise SourceAcquisitionError("prepared output already exists")
        temporary.rename(output)
    finally:
        if temporary.exists():
            for path in temporary.rglob("*"):
                if not path.is_symlink() and path.is_dir():
                    path.chmod(0o700)
            shutil.rmtree(temporary)
    return load_prepared_source(output, hashlib.sha256(encoded).hexdigest())


def _manifest(root: Path, expected_digest: str) -> Mapping[str, object]:
    if _DIGEST.fullmatch(expected_digest) is None:
        raise SourceAcquisitionError("prepared digest must be a SHA-256 hex digest")
    if root.is_symlink() or not root.is_dir():
        raise SourceAcquisitionError("prepared handoff must be a real directory")
    if {path.name for path in root.iterdir()} != {"source", "manifest.json"}:
        raise SourceAcquisitionError("prepared handoff has unexpected entries")
    path = root / "manifest.json"
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SourceAcquisitionError("prepared manifest must be a regular file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SourceAcquisitionError("prepared manifest must be a regular file")
        encoded = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise SourceAcquisitionError("prepared manifest exceeds the byte limit")
    if hashlib.sha256(encoded).hexdigest() != expected_digest:
        raise SourceAcquisitionError("prepared manifest digest does not match")
    try:
        value = json.loads(encoded)
    except (ValueError, RecursionError) as exc:
        raise SourceAcquisitionError("prepared manifest is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise SourceAcquisitionError("prepared manifest fields are invalid")
    return value


def load_prepared_source(root: Path, expected_digest: str) -> PreparedSource:
    """Check the caller-retained manifest digest, attribution, and complete source tree."""
    value = _manifest(root, expected_digest)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise SourceAcquisitionError("prepared schema version is unsupported")
    alias, revision, tree_id = (
        value["repository_alias"],
        value["revision"],
        value["tree_id"],
    )
    raw_source, tree_digest = value["source"], value["tree_digest"]
    if not all(isinstance(item, str) for item in (alias, revision, tree_id, tree_digest)):
        raise SourceAcquisitionError("prepared identity fields must be strings")
    if not isinstance(raw_source, dict) or set(raw_source) != {
        "kind",
        "provider",
        "revision_kind",
        "trigger",
        "request_id",
    }:
        raise SourceAcquisitionError("prepared source attribution fields are invalid")
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        raise SourceAcquisitionError("prepared revision is invalid")
    if not isinstance(tree_id, str) or _REVISION.fullmatch(tree_id) is None:
        raise SourceAcquisitionError("prepared tree id is invalid")
    if not isinstance(tree_digest, str) or _DIGEST.fullmatch(tree_digest) is None:
        raise SourceAcquisitionError("prepared tree digest is invalid")
    # Reuse canonical review validation rather than introducing another source-attribution schema.
    source = ReviewSource(**raw_source)
    validated = build_review_package(
        (),
        repository_alias=str(alias),
        revision=revision,
        exposure=Exposure.UNKNOWN,
        coverage_complete=False,
        source=source,
    )
    prepared = PreparedSource(
        acquired=AcquiredSource(root / "source", revision, tree_id, source.revision_kind),
        repository_alias=str(validated["repository_alias"]),
        source=source,
        manifest_digest=expected_digest,
        tree_digest=tree_digest,
    )
    prepared.verify_tree()
    return prepared
