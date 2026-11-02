"""Durable snapshot mirror - copy one validated collector snapshot tree into
a durable artifact store so its content survives the ephemeral Container
Apps Job filesystem that produced it.

Phase 2 mapping (``docs/roadmap/rules-and-detection/rule-catalog-collection.md``
§ Remaining work: "durable snapshot location"). Pure protocol-based logic -
the Azure Blob adapter lives one layer up in
``fdai.delivery.azure.rule_catalog_snapshot_store``, exactly like
``promotion.py`` keeps the catalog-as-code PR delivery adapter out of the
pipeline stage that decides *what* to promote.

This module never mutates ``rule-catalog/``, never writes to git, and never
decides which source is due - that stays
:class:`~fdai.rule_catalog.pipeline.watcher.SourceWatcher`'s job. It is
handed an already-collected, already-verified snapshot directory and
durably persists a byte-for-byte, content-addressed copy, so the mirrored
artifact is provably identical to what the collector fetched.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fdai.rule_catalog.schema.zstd_codec import (
    DEFAULT_ZSTD_LEVEL,
    compress_bytes,
    decompress_bytes,
    is_zstd_frame,
)

_MAX_SNAPSHOT_FILE_BYTES = 8 * 1024 * 1024
_SAFE_PREFIX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class SnapshotArtifactStore(Protocol):
    """Durable content-addressed write target for one snapshot file."""

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        """Store ``content`` at ``storage_ref``.

        Returns ``True`` when this call durably wrote new content and
        ``False`` when the exact same content was already stored (a
        replayed mirror call). Implementations MUST raise when
        ``storage_ref`` already holds *different* content - a digest
        collision under an immutable path is a hard error, never a
        silent overwrite.
        """
        ...


@dataclass(frozen=True, slots=True)
class MirroredFile:
    """One durably persisted snapshot file."""

    relative_path: str
    storage_ref: str
    digest: str
    size_bytes: int
    newly_written: bool
    compressed_size_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class SnapshotMirrorReceipt:
    """Replayable evidence describing one durable snapshot mirror.

    Every field is derived deterministically from the snapshot tree's own
    bytes: replaying the mirror against the same tree reproduces the exact
    same digests and storage refs. That determinism is what makes this step
    "replayable" - a caller never needs to contact a live provider, or keep
    any separate ledger, to confirm whether a given snapshot was already
    durably persisted; it recomputes :attr:`tree_sha256` and compares.
    """

    source_id: str
    resolved_revision: str
    files: tuple[MirroredFile, ...]

    @property
    def tree_sha256(self) -> str:
        """Digest over the sorted ``(relative_path, digest)`` pairs."""

        payload = "\n".join(
            f"{file.relative_path}:{file.digest}"
            for file in sorted(self.files, key=lambda file: file.relative_path)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SnapshotMirror:
    """Walk one local snapshot directory and durably persist every file."""

    def __init__(
        self,
        *,
        store: SnapshotArtifactStore,
        storage_prefix: str = "rule-catalog-snapshots",
        compress_zstd: bool = False,
        zstd_level: int = DEFAULT_ZSTD_LEVEL,
    ) -> None:
        if _SAFE_PREFIX.fullmatch(storage_prefix) is None:
            raise ValueError("snapshot mirror storage_prefix MUST be a safe lowercase segment")
        self._store = store
        self._prefix = storage_prefix
        self._compress_zstd = bool(compress_zstd)
        self._zstd_level = zstd_level

    async def mirror(
        self,
        *,
        source_id: str,
        resolved_revision: str,
        snapshot_dir: Path,
    ) -> SnapshotMirrorReceipt:
        if not source_id.strip() or not resolved_revision.strip():
            raise ValueError("snapshot mirror requires a non-empty source id and revision")
        if not snapshot_dir.is_dir():
            raise ValueError(f"snapshot directory does not exist: {snapshot_dir}")

        files: list[MirroredFile] = []
        for path in _iter_files(snapshot_dir):
            relative = path.relative_to(snapshot_dir).as_posix()
            content = path.read_bytes()
            if not content or len(content) > _MAX_SNAPSHOT_FILE_BYTES:
                raise ValueError(f"snapshot file size is outside the allowed range: {relative}")
            raw_digest = hashlib.sha256(content).hexdigest()
            if self._compress_zstd:
                envelope = compress_bytes(content, level=self._zstd_level)
                stored_bytes = envelope.compressed_bytes
                stored_digest = hashlib.sha256(stored_bytes).hexdigest()
                storage_ref = f"{self._prefix}/{source_id}/{resolved_revision}/{relative}.zst"
                compressed_size: int | None = len(stored_bytes)
            else:
                stored_bytes = content
                stored_digest = raw_digest
                storage_ref = f"{self._prefix}/{source_id}/{resolved_revision}/{relative}"
                compressed_size = None
            newly_written = await self._store.put(storage_ref, stored_bytes, digest=stored_digest)
            files.append(
                MirroredFile(
                    relative_path=relative,
                    storage_ref=storage_ref,
                    digest=raw_digest,
                    size_bytes=len(content),
                    newly_written=newly_written,
                    compressed_size_bytes=compressed_size,
                )
            )
        return SnapshotMirrorReceipt(
            source_id=source_id,
            resolved_revision=resolved_revision,
            files=tuple(sorted(files, key=lambda file: file.relative_path)),
        )


def decode_mirrored_file_content(
    stored_bytes: bytes,
    *,
    expected_uncompressed_digest: str,
) -> bytes:
    """Restore and SHA-256-verify either raw or Zstd-compressed mirrored file bytes."""
    if len(expected_uncompressed_digest) != 64:
        raise ValueError("expected_uncompressed_digest MUST be a 64-char hex SHA-256")
    if is_zstd_frame(stored_bytes):
        return decompress_bytes(
            stored_bytes,
            max_output_size=_MAX_SNAPSHOT_FILE_BYTES,
            expected_uncompressed_sha256=f"sha256:{expected_uncompressed_digest}",
        )
    if len(stored_bytes) > _MAX_SNAPSHOT_FILE_BYTES:
        raise ValueError("mirrored file exceeds maximum allowed size")
    if hashlib.sha256(stored_bytes).hexdigest() != expected_uncompressed_digest:
        raise ValueError("mirrored file uncompressed SHA-256 mismatch")
    return bytes(stored_bytes)


def _iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


__all__ = [
    "MirroredFile",
    "SnapshotArtifactStore",
    "SnapshotMirror",
    "SnapshotMirrorReceipt",
    "decode_mirrored_file_content",
]
