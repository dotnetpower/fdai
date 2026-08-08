"""Manual-source ingestion seam - deliver siloed manuals to the distiller.

Design contract:
``docs/roadmap/rules-and-detection/manual-distillation.md`` § "Ingesting from
siloed sources". This seam is the *access* front of the compile-side
:mod:`distiller` seam: it discovers manuals that live in SharePoint,
Confluence, Notion, Loop, or email, and hands each one to the
:class:`~fdai.shared.providers.distiller.Distiller` as a
:class:`~fdai.shared.providers.distiller.ManualDocument`.

The reframing that unlocks the auth problem (see the design doc): distillation
is build-time and runs once per manual revision, so FDAI never needs a
continuous broad-read credential. The access model therefore inverts from
*pull* to *push / delegate*, and this seam holds no standing credential of its
own - a fork's connector supplies whatever short-lived, scoped access it needs.

Layering
--------

This module lives under ``shared/providers`` and MUST NOT import ``core/``. It
reuses :class:`ManualDocument` from the sibling :mod:`distiller` seam (the
source produces exactly what the distiller consumes) and declares its own
listing / delta contracts.

Two shapes ship upstream:

- :class:`EmptyManualSource` (the default binding): lists nothing. A source the
  fork has not wired yields no manuals, so distillation degrades to
  "nothing to compile", never to a fabricated candidate.
- :class:`DropDirectoryManualSource`: reads a configured local directory. This
  one generic adapter covers every credential-free access mode in the design
  doc at once - an operator drop, a console upload, an email-in address, and an
  iPaaS (Power Automate / Logic Apps) webhook all land a file in the drop
  directory. Connector adapters that speak to SharePoint / Confluence / Notion,
  or that fetch with an operator's delegated token, are customer data and live
  in the fork behind this same Protocol.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from fdai.shared.providers.distiller import ManualDocument


@dataclass(frozen=True, slots=True)
class ManualCandidate:
    """A discoverable manual a source can offer, before any fetch or triage.

    Listing is a metadata-only operation: the full text is pulled lazily via
    :meth:`ManualSource.fetch` only for candidates that survive the
    deterministic triage stage. The signal fields feed that triage
    (labels / authority / recency); every one is best-effort, so a source that
    cannot supply a signal leaves it at its empty default.

    ``source_ref`` is the citation handle echoed onto every distilled candidate
    so a promoted rule can point back at its provenance. ``metadata`` is
    adapter-neutral and never carries secrets.
    """

    doc_id: str
    source_ref: str
    title: str = ""
    labels: tuple[str, ...] = ()
    space: str = ""
    tree_path: tuple[str, ...] = ()
    verified: bool = False
    view_count: int = 0
    last_edited: str = ""
    inbound_links: int = 0
    content_sha: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise ValueError("ManualCandidate.doc_id MUST be non-empty")
        if not self.source_ref:
            raise ValueError("ManualCandidate.source_ref MUST be non-empty")
        if self.view_count < 0:
            raise ValueError("ManualCandidate.view_count MUST be >= 0")
        if self.inbound_links < 0:
            raise ValueError("ManualCandidate.inbound_links MUST be >= 0")


class ManualChangeType(StrEnum):
    """Whether a delta upserts (new / edited) or removes a manual."""

    UPSERTED = "upserted"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class ManualChange:
    """One entry in a source delta - drives incremental re-distillation.

    A :attr:`ManualChangeType.DELETED` change is the deletion signal the design
    doc calls out: the rules distilled from the removed manual must be retired
    (tombstoned), never left firing on withdrawn guidance.
    """

    change_type: ManualChangeType
    candidate: ManualCandidate


@runtime_checkable
class ManualSource(Protocol):
    """Discover manuals and deliver them to the distiller (build-time, async)."""

    async def list_candidates(self) -> Sequence[ManualCandidate]:
        """Return every manual this source currently offers (metadata only).

        An empty sequence is a valid answer (nothing to distill), NOT an error.
        """
        ...

    async def fetch(self, doc_id: str) -> ManualDocument | None:
        """Return the full :class:`ManualDocument` for ``doc_id``.

        Returns ``None`` when the manual no longer exists (deleted / moved), so
        a stale candidate reference degrades to "nothing to compile" rather than
        raising.
        """
        ...

    async def changes(self, since: str) -> Sequence[ManualChange]:
        """Return manuals changed since the ``since`` cursor (ISO 8601 UTC).

        A source that cannot compute a delta returns an empty sequence; the
        caller then falls back to a full :meth:`list_candidates` pass.
        """
        ...


class EmptyManualSource:
    """Upstream default - offers no manuals.

    A fork that has not wired a connector distills nothing, which is the
    fail-safe: no source means no candidates means nothing to promote.
    """

    async def list_candidates(self) -> Sequence[ManualCandidate]:
        return ()

    async def fetch(self, doc_id: str) -> ManualDocument | None:  # noqa: ARG002
        return None

    async def changes(self, since: str) -> Sequence[ManualChange]:  # noqa: ARG002
        return ()


def _iso_utc(timestamp: float) -> str:
    """Render a POSIX timestamp as an ISO 8601 UTC string (second precision)."""
    return (
        datetime.fromtimestamp(timestamp, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class DropDirectoryManualSource:
    """Read manuals dropped into a configured local directory (upstream generic).

    One adapter for every credential-free access mode: an operator PR into the
    drop folder, a console upload, an email-in gateway, and an iPaaS webhook all
    write a file here. Discovery, hashing, and delta are fully deterministic, so
    this adapter is safe to run upstream without any customer connector.

    ``doc_id`` is the POSIX path of the file relative to ``root``; ``source_ref``
    is ``drop://<doc_id>``. Files are decoded as UTF-8; an undecodable byte is
    replaced and the document is flagged ``decode=lossy`` in its metadata rather
    than dropped, since faithful parsing of rich formats (PDF, images) is a
    downstream open decision, not this adapter's job.

    ``max_bytes`` caps the size of a file this adapter will read: a drop folder
    is an untrusted input boundary, so an oversize or binary blob is skipped
    from the listing rather than read whole into memory (which would OOM the
    build and make the sensitivity scanner chew a single huge line). A text
    manual well exceeding the default is almost certainly not distillable text.
    """

    _SOURCE_SCHEME = "drop://"
    _DEFAULT_MAX_BYTES = 5_000_000

    def __init__(
        self,
        root: Path | str,
        *,
        glob: str = "**/*",
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("DropDirectoryManualSource.max_bytes MUST be positive")
        self._root = Path(root).resolve()
        self._glob = glob
        self._max_bytes = max_bytes

    def _iter_files(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        # Skip symlinks: a dropped symlink must not exfiltrate a file outside
        # the drop root (its real path escapes the directory), and an escaping
        # real path would otherwise crash _rel_id's relative_to(). glob does not
        # recurse into symlinked directories, so filtering symlink entries here
        # is the complete boundary. Oversize files are skipped too (see max_bytes).
        files = [
            p
            for p in self._root.glob(self._glob)
            if p.is_file() and not p.is_symlink() and p.stat().st_size <= self._max_bytes
        ]
        return sorted(files)

    def _rel_id(self, path: Path) -> str:
        return path.resolve().relative_to(self._root).as_posix()

    def _read(self, path: Path) -> tuple[str, str, bool]:
        """Return ``(text, content_sha, lossy)`` for one file, decoded UTF-8."""
        raw = path.read_bytes()
        content_sha = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8")
            lossy = False
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            lossy = True
        return text, content_sha, lossy

    def _candidate(self, path: Path) -> ManualCandidate:
        doc_id = self._rel_id(path)
        _, content_sha, _ = self._read(path)
        stat = path.stat()
        return ManualCandidate(
            doc_id=doc_id,
            source_ref=f"{self._SOURCE_SCHEME}{doc_id}",
            title=path.name,
            last_edited=_iso_utc(stat.st_mtime),
            content_sha=content_sha,
        )

    async def list_candidates(self) -> Sequence[ManualCandidate]:
        return tuple(self._candidate(p) for p in self._iter_files())

    async def fetch(self, doc_id: str) -> ManualDocument | None:
        path = (self._root / doc_id).resolve()
        # Reject a doc_id that escapes the drop root (path traversal), or an
        # oversize file (would OOM the build / stall the scanner - see max_bytes).
        if (
            not path.is_relative_to(self._root)
            or not path.is_file()
            or path.stat().st_size > self._max_bytes
        ):
            return None
        text, content_sha, lossy = self._read(path)
        metadata = {"decode": "lossy"} if lossy else {}
        return ManualDocument(
            doc_id=doc_id,
            text=text,
            source_ref=f"{self._SOURCE_SCHEME}{doc_id}",
            content_sha=content_sha,
            metadata=metadata,
        )

    async def changes(self, since: str) -> Sequence[ManualChange]:
        """Return files modified at or after ``since`` as UPSERTED changes.

        A drop directory has no memory of files that were removed, so deletion
        detection needs the prior-snapshot manifest supplied by the watcher
        (handled where the delta is consumed); this adapter reports upserts by
        modification time only.
        """
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"ManualSource.changes 'since' MUST be ISO 8601, got {since!r}"
            ) from exc
        # A naive cursor (no offset) is interpreted as UTC, not the host's local
        # zone - st_mtime is a UTC epoch, so treating naive as local would shift
        # the cutoff by the local offset and mis-scope the delta.
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        cutoff_ts = cutoff.timestamp()
        out: list[ManualChange] = []
        for path in self._iter_files():
            if path.stat().st_mtime >= cutoff_ts:
                out.append(
                    ManualChange(
                        change_type=ManualChangeType.UPSERTED,
                        candidate=self._candidate(path),
                    )
                )
        return tuple(out)


__all__ = [
    "DropDirectoryManualSource",
    "EmptyManualSource",
    "ManualCandidate",
    "ManualChange",
    "ManualChangeType",
    "ManualSource",
]
