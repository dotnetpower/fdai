"""Bounded current deployment catalog for exact H10 scopes and configured on-call shifts.

The private catalog defines allowed scope references, not observed resources or IAM
authority. Every read validates fresh file bytes; a content-derived revision fences
reviewed plans. No generated defaults, wildcard scopes, or ambient schedule exists.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fdai.core.human_assignment.scoped_duties import (
    ScopeCatalogEntry,
    ScopedDutyValidationError,
    canonical_digest,
    utc_instant,
)
from fdai.shared.providers.oncall_schedule import OnCallShift

_MAX_BYTES = 1_048_576
_MAX_ENTRIES = 1000


def exact_person_id(value: object) -> str:
    """Require the implemented directory's canonical object id before constructing a URL."""
    if not isinstance(value, str):
        raise ScopedDutyValidationError("directory subject MUST be a canonical object id")
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise ScopedDutyValidationError("directory subject MUST be a canonical object id")


@dataclass(frozen=True, slots=True)
class ScopedDutyCatalogSnapshot:
    """Validated immutable configuration; neither scope admission nor a shift grants access."""

    revision: str
    scopes: frozenset[str]
    shifts: tuple[OnCallShift, ...]


@dataclass(frozen=True, slots=True)
class FileScopedDutyCatalog:
    """Read exact scopes and implement the existing OnCallSchedule read contract.

    Construction reads nothing. Runtime composition validates once before binding;
    later reads never reuse a stale startup snapshot. An absent, malformed, replaced,
    or oversized source raises a content-free error rather than admitting old data.
    """

    path: Path

    def validate(self) -> ScopedDutyCatalogSnapshot:
        """Validate current local configuration at startup without changing the file."""
        return _read_snapshot(self.path)

    async def snapshot(self) -> ScopedDutyCatalogSnapshot:
        """Read one bounded regular file off the event loop; no source content is logged."""
        return await asyncio.to_thread(_read_snapshot, self.path)

    async def read_scope(self, scope_ref: str, *, source_revision: str) -> ScopeCatalogEntry | None:
        """Admit only an exact member of the current content-derived catalog revision."""
        current = await self.snapshot()
        if current.revision != source_revision or scope_ref not in current.scopes:
            return None
        return ScopeCatalogEntry(scope_ref, source_revision)

    async def current(self, *, rotation: str, at: datetime) -> OnCallShift | None:
        """Resolve one declared half-open shift; callers separately check current identity."""
        instant = utc_instant(at)
        current = await self.snapshot()
        return next(
            (
                shift
                for shift in current.shifts
                if shift.rotation == rotation and shift.start <= instant < shift.until
            ),
            None,
        )


def _read_snapshot(path: Path) -> ScopedDutyCatalogSnapshot:
    """Reject symlinks, special files, torn reads, duplicate keys, and unbounded config."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BYTES:
                raise ScopedDutyValidationError(
                    "scoped duty catalog MUST be a bounded regular file"
                )
            raw = source.read(_MAX_BYTES + 1)
            after = os.fstat(source.fileno())
        current = path.stat(follow_symlinks=False)
        if len(raw) > _MAX_BYTES or any(
            (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            for item in (after, current)
        ):
            raise ScopedDutyValidationError("scoped duty catalog changed during its read")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        return _decode(value)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ScopedDutyValidationError("scoped duty catalog is unavailable or invalid") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ScopedDutyValidationError("scoped duty catalog contains duplicate keys")
        result[key] = value
    return result


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ScopedDutyValidationError("scoped duty catalog fields do not match its schema")
    return value


def _token(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(not "!" <= char <= "~" for char in value)
    ):
        raise ScopedDutyValidationError("scoped duty catalog references MUST be exact ASCII tokens")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ScopedDutyValidationError("shift times MUST be explicit offset-aware text")
    return utc_instant(datetime.fromisoformat(value))


def _decode(value: object) -> ScopedDutyCatalogSnapshot:
    document = _object(value, {"schema_version", "scopes", "shifts"})
    if document["schema_version"] != "1.0.0":
        raise ScopedDutyValidationError("unsupported scoped duty catalog schema")
    raw_scopes, raw_shifts = document["scopes"], document["shifts"]
    if (
        not isinstance(raw_scopes, list)
        or not 1 <= len(raw_scopes) <= _MAX_ENTRIES
        or not isinstance(raw_shifts, list)
        or len(raw_shifts) > _MAX_ENTRIES
    ):
        raise ScopedDutyValidationError("scoped duty catalog entries exceed their bounds")
    scopes = tuple(_token(item) for item in raw_scopes)
    if len(set(scopes)) != len(scopes):
        raise ScopedDutyValidationError("scoped duty catalog contains duplicate scopes")
    shifts: list[OnCallShift] = []
    for raw in raw_shifts:
        row = _object(raw, {"rotation", "primary_oid", "secondary_oid", "start", "until"})
        shift = OnCallShift(
            rotation=_token(row["rotation"]),
            primary_oid=exact_person_id(row["primary_oid"]),
            secondary_oid=(
                None if row["secondary_oid"] is None else exact_person_id(row["secondary_oid"])
            ),
            start=_timestamp(row["start"]),
            until=_timestamp(row["until"]),
        )
        if (
            shift.rotation != shift.rotation.casefold()
            or shift.start >= shift.until
            or shift.primary_oid == shift.secondary_oid
        ):
            raise ScopedDutyValidationError("shift identity or effective interval is invalid")
        shifts.append(shift)
    ordered = tuple(sorted(shifts, key=lambda shift: (shift.rotation, shift.start)))
    for previous, following in zip(ordered, ordered[1:], strict=False):
        if previous.rotation == following.rotation and previous.until > following.start:
            raise ScopedDutyValidationError("configured rotation shifts MUST NOT overlap")
    revision = "sha256:" + canonical_digest(
        {"schema_version": "1.0.0", "scopes": tuple(sorted(scopes)), "shifts": ordered}
    )
    return ScopedDutyCatalogSnapshot(revision, frozenset(scopes), ordered)


__all__ = ["FileScopedDutyCatalog", "ScopedDutyCatalogSnapshot", "exact_person_id"]
