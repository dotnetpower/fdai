"""Read-only, exact-scope evidence for forecast intervention and exclusion history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ForecastContextRequest:
    """Identify the complete history window needed by one forecast scorer."""

    access_scope_digest: str
    target_digest: str
    horizon_started_at: datetime
    horizon_ended_at: datetime
    as_of: datetime

    def __post_init__(self) -> None:
        for digest in (self.access_scope_digest, self.target_digest):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("forecast context request identities MUST be SHA-256")
        timestamps = (self.horizon_started_at, self.horizon_ended_at, self.as_of)
        if any(
            not isinstance(value, datetime) or value.utcoffset() is None for value in timestamps
        ):
            raise ValueError("forecast context request timestamps MUST be timezone-aware")
        if not self.horizon_started_at < self.horizon_ended_at <= self.as_of:
            raise ValueError("forecast context request timestamps MUST be ordered")


@dataclass(frozen=True, slots=True)
class ForecastContextEvidence:
    """Retained context whose completeness is established by the injected source.

    Complete means all configured intervention, deletion, and excluded-window
    sources cover the exact requested target and interval, not merely that a
    query returned no rows. References resolve to retained source evidence.
    This evidence supplies no approval, policy override, or execution authority.
    """

    access_scope_digest: str
    target_digest: str
    horizon_started_at: datetime
    horizon_ended_at: datetime
    recorded_at: datetime
    valid_until: datetime
    complete: bool
    source_revision: str
    evidence_refs: tuple[str, ...]
    intervention_refs: tuple[str, ...] = ()
    resource_deleted: bool = False
    excluded_window: bool = False

    def __post_init__(self) -> None:
        for digest in (self.access_scope_digest, self.target_digest, self.source_revision):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("forecast context identities MUST be lowercase SHA-256")
        timestamps = (
            self.horizon_started_at,
            self.horizon_ended_at,
            self.recorded_at,
            self.valid_until,
        )
        if any(
            not isinstance(value, datetime) or value.utcoffset() is None for value in timestamps
        ):
            raise ValueError("forecast context timestamps MUST be timezone-aware")
        if (
            not self.horizon_started_at
            < self.horizon_ended_at
            <= self.recorded_at
            < self.valid_until
        ):
            raise ValueError("forecast context timestamps MUST be ordered")
        if any(
            type(value) is not bool
            for value in (self.complete, self.resource_deleted, self.excluded_window)
        ):
            raise ValueError("forecast context state fields MUST be boolean")
        for references, minimum in ((self.evidence_refs, 1), (self.intervention_refs, 0)):
            if (
                not isinstance(references, tuple)
                or not minimum <= len(references) <= 64
                or any(
                    not isinstance(value, str) or not value.strip() or len(value) > 512
                    for value in references
                )
            ):
                raise ValueError("forecast context references MUST be bounded immutable text")
            if len(set(references)) != len(references):
                raise ValueError("forecast context references MUST be unique")

    @property
    def digest(self) -> str:
        """Return the exact canonical content identity used by producers and consumers."""
        value = asdict(self)
        for name in ("horizon_started_at", "horizon_ended_at", "recorded_at", "valid_until"):
            value[name] = getattr(self, name).astimezone(UTC).isoformat()
        for name in ("evidence_refs", "intervention_refs"):
            value[name] = sorted(value[name])
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class ForecastContextUnavailableError(RuntimeError):
    """The source cannot establish complete history for the requested window."""


class ForecastContextProvider(Protocol):
    """Read retained, authorized history without treating absence of rows as completeness."""

    async def read(self, request: ForecastContextRequest) -> ForecastContextEvidence: ...
