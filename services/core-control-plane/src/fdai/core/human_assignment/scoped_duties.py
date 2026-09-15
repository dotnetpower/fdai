"""Immutable H10 declarations and read-only evidence contracts, without IAM authority.

These types do not extend the global stewardship map. References are exact tokens,
not names to search. Adapters must use one canonical namespace for person references
and return complete expansions rather than truncated pages or inferred future cover.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from fdai.core.stewardship.model import Duty
from fdai.core.stewardship.names import AGENT_NAME_SET

MAX_BINDINGS: Final = 30
MAX_PEOPLE_PER_EXPANSION: Final = 100


class ScopedDutyValidationError(ValueError):
    """Reject malformed declarations or evidence without including private input values."""


class DutySubjectKind(StrEnum):
    """Typed subject categories; PERSON uses the existing wire vocabulary ``user``."""

    PERSON = "user"
    GROUP = "group"
    SCHEDULE = "schedule"


def _reference(value: str) -> None:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(not "!" <= char <= "~" for char in value)
    ):
        raise ScopedDutyValidationError(
            "references MUST be exact nonblank ASCII tokens of at most 256 characters"
        )


def utc_instant(value: datetime) -> datetime:
    """Reject naive or undefined-offset times and return an immutable UTC instant."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ScopedDutyValidationError("timestamps MUST have a defined UTC offset")
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ScopedDutyValidationError("timestamp MUST be representable in UTC") from exc


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return utc_instant(value).isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: getattr(value, item.name) for item in fields(value)}
    raise TypeError("unsupported scoped duty canonical value")


def canonical_json(value: object) -> str:
    """Encode validated review values deterministically without reading or writing a file."""
    return json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_digest(value: object) -> str:
    """Bind exact references, UTC instants, and provenance with a lowercase SHA-256 digest."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DutySubject:
    """An already normalized exact subject; no display-name matching or identity coercion."""

    kind: DutySubjectKind
    ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DutySubjectKind):
            raise ScopedDutyValidationError("subject kind MUST be a DutySubjectKind")
        _reference(self.ref)
        if self.ref != self.ref.casefold():
            raise ScopedDutyValidationError("subject references MUST already be normalized")


@dataclass(frozen=True, slots=True)
class ScopedDutyBinding:
    """One declared duty over [effective_from, effective_until), not an active assignment.

    Only schedules accept a fallback, and they require one exact static PERSON. That
    fallback occupies this same duty on resolution failure; it is not a second person
    for backup coverage and still needs a fresh exact-person resolution receipt.
    """

    subject: DutySubject
    agent_name: str
    scope_ref: str
    duty: Duty
    effective_from: datetime
    effective_until: datetime
    fallback: DutySubject | None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, DutySubject) or not isinstance(self.duty, Duty):
            raise ScopedDutyValidationError("bindings require a typed subject and existing Duty")
        if not isinstance(self.agent_name, str) or self.agent_name not in AGENT_NAME_SET:
            raise ScopedDutyValidationError("binding requires an exact known pantheon agent")
        _reference(self.scope_ref)
        object.__setattr__(self, "effective_from", utc_instant(self.effective_from))
        object.__setattr__(self, "effective_until", utc_instant(self.effective_until))
        if self.effective_from >= self.effective_until:
            raise ScopedDutyValidationError("effective window MUST be nonempty and half-open")
        if self.subject.kind is DutySubjectKind.SCHEDULE:
            if (
                not isinstance(self.fallback, DutySubject)
                or self.fallback.kind is not DutySubjectKind.PERSON
                or self.fallback.ref == self.subject.ref
            ):
                raise ScopedDutyValidationError(
                    "schedule requires a distinct static PERSON fallback"
                )
        elif self.fallback is not None:
            raise ScopedDutyValidationError("only schedules may declare a static PERSON fallback")

    def sort_key(self) -> tuple[str, str, int, str]:
        """Sort by exact agent, scope, explicit duty, then complete declaration identity."""
        order = (Duty.PRIMARY, Duty.BACKUP, Duty.ESCALATION)
        return self.agent_name, self.scope_ref, order.index(self.duty), canonical_json(self)


@dataclass(frozen=True, slots=True)
class ScopedDutyInput:
    """An exact source revision and 1-30 immutable, ordered declarations.

    Mutable and unordered collections are rejected, not silently snapshotted. The
    original order remains available; canonical output sorts declarations explicitly.
    Same subject/agent/scope windows cannot overlap, even across different duties.
    """

    source_revision: str
    bindings: tuple[ScopedDutyBinding, ...]
    supersedes_case_id: str | None = None

    def __post_init__(self) -> None:
        _reference(self.source_revision)
        if self.supersedes_case_id is not None:
            if str(UUID(self.supersedes_case_id)) != self.supersedes_case_id:
                raise ScopedDutyValidationError("superseded case reference MUST be canonical")
        if type(self.bindings) is not tuple or not 1 <= len(self.bindings) <= MAX_BINDINGS:
            raise ScopedDutyValidationError("bindings MUST be an immutable tuple of 1-30 entries")
        if not all(isinstance(binding, ScopedDutyBinding) for binding in self.bindings):
            raise ScopedDutyValidationError("bindings MUST contain only ScopedDutyBinding values")
        for index, binding in enumerate(self.bindings):
            for previous in self.bindings[:index]:
                if (
                    (binding.subject, binding.agent_name, binding.scope_ref)
                    == (previous.subject, previous.agent_name, previous.scope_ref)
                    and binding.effective_from < previous.effective_until
                    and previous.effective_from < binding.effective_until
                ):
                    raise ScopedDutyValidationError(
                        "same subject, agent, and scope MUST NOT have overlapping duty windows"
                    )

    @property
    def ordered_bindings(self) -> tuple[ScopedDutyBinding, ...]:
        """Return a canonical ordering without changing the immutable input tuple."""
        return tuple(sorted(self.bindings, key=ScopedDutyBinding.sort_key))

    @property
    def digest(self) -> str:
        """Bind the exact source revision and declarations, independent of input permutation."""
        return canonical_digest(
            {
                "source_revision": self.source_revision,
                "bindings": self.ordered_bindings,
                **(
                    {"supersedes_case_id": self.supersedes_case_id}
                    if self.supersedes_case_id
                    else {}
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class ScopeCatalogEntry:
    """One exact scope in a pinned catalog revision; absence is never a wildcard match."""

    scope_ref: str
    source_revision: str

    def __post_init__(self) -> None:
        _reference(self.scope_ref)
        _reference(self.source_revision)


@dataclass(frozen=True, slots=True)
class DutyResolution:
    """A source-bound observation, not evidence for an entire declared duty window.

    ``at`` echoes the exact query instant. ``complete`` explicitly distinguishes a
    whole expansion from partial evidence. Empty/incomplete/stale observations may be
    represented but cannot prove coverage. Malformed people or provenance are rejected.
    """

    subject: DutySubject
    at: datetime
    people: tuple[DutySubject, ...]
    observed_at: datetime
    valid_until: datetime
    provenance_ref: str
    provenance_digest: str
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.subject, DutySubject):
            raise ScopedDutyValidationError("resolution MUST bind a typed source subject")
        if type(self.people) is not tuple or len(self.people) > MAX_PEOPLE_PER_EXPANSION:
            raise ScopedDutyValidationError("people MUST be an immutable tuple of at most 100")
        if not all(
            isinstance(person, DutySubject) and person.kind is DutySubjectKind.PERSON
            for person in self.people
        ):
            raise ScopedDutyValidationError("expansion MUST contain only exact PERSON subjects")
        if len({person.ref for person in self.people}) != len(self.people):
            raise ScopedDutyValidationError("expansion MUST NOT contain duplicate people")
        if (
            self.subject.kind is DutySubjectKind.PERSON
            and self.people
            and self.people != (self.subject,)
        ):
            raise ScopedDutyValidationError("PERSON resolution MUST match the exact source person")
        object.__setattr__(
            self, "people", tuple(sorted(self.people, key=lambda person: person.ref))
        )
        for name in ("at", "observed_at", "valid_until"):
            object.__setattr__(self, name, utc_instant(getattr(self, name)))
        if self.observed_at >= self.valid_until:
            raise ScopedDutyValidationError("observation validity window MUST be nonempty")
        if type(self.complete) is not bool:
            raise ScopedDutyValidationError("resolution completeness MUST be an explicit boolean")
        _reference(self.provenance_ref)
        if (
            not isinstance(self.provenance_digest, str)
            or len(self.provenance_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.provenance_digest)
        ):
            raise ScopedDutyValidationError("provenance digest MUST be lowercase SHA-256 hex")

    def is_current(self, *, at: datetime, max_age: timedelta) -> bool:
        """Check half-open freshness at a supplied clock, never widen source validity."""
        instant = utc_instant(at)
        return (
            self.observed_at <= instant < self.valid_until
            and timedelta(0) <= instant - self.observed_at < max_age
        )


@dataclass(frozen=True, slots=True)
class ScopedDutyPolicy:
    """Explicit freshness and per-read deadline; there are no permissive policy defaults.

    Reads are serial and never retried. A total deadline bounds the whole plan independently
    of the per-read deadline, including scope, subject, and fallback lookups.
    """

    max_resolution_age: timedelta
    read_timeout_seconds: float
    total_timeout_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(
            self.max_resolution_age, timedelta
        ) or self.max_resolution_age <= timedelta(0):
            raise ScopedDutyValidationError("maximum resolution age MUST be positive")
        if (
            isinstance(self.read_timeout_seconds, bool)
            or not isinstance(self.read_timeout_seconds, (int, float))
            or not 0 < self.read_timeout_seconds <= 30
        ):
            raise ScopedDutyValidationError(
                "read timeout MUST be finite and within (0, 30] seconds"
            )
        if (
            isinstance(self.total_timeout_seconds, bool)
            or not isinstance(self.total_timeout_seconds, int | float)
            or not 0 < self.total_timeout_seconds <= 120
        ):
            raise ScopedDutyValidationError("total plan timeout MUST be within (0, 120] seconds")

    def to_dict(self) -> dict[str, int | float]:
        """Preserve the exact freshness budget and read deadline in replayable review artifacts."""
        age = self.max_resolution_age
        return {
            "max_resolution_age_microseconds": (
                (age.days * 86_400 + age.seconds) * 1_000_000 + age.microseconds
            ),
            "read_timeout_seconds": float(self.read_timeout_seconds),
            "total_timeout_seconds": float(self.total_timeout_seconds),
        }


class DutySubjectResolver(Protocol):
    """Read exact people only; no agent calls, model interpretation, IAM, or writes."""

    async def resolve(self, subject: DutySubject, *, at: datetime) -> DutyResolution | None:
        """Return source/query-bound evidence or None, never a truncated or guessed expansion.

        An adapter must honor cancellation and identify only people actually observed
        for this subject and instant. A current schedule answer is not a future roster.
        """
        ...


class ExactScopeCatalogReader(Protocol):
    """Read scopes by exact reference and source revision, without fuzzy or parent matching."""

    async def read_scope(self, scope_ref: str, *, source_revision: str) -> ScopeCatalogEntry | None:
        """Return the exact pinned entry or None; perform no writes and honor cancellation."""
        ...


__all__ = [
    "MAX_BINDINGS",
    "MAX_PEOPLE_PER_EXPANSION",
    "DutyResolution",
    "DutySubject",
    "DutySubjectKind",
    "DutySubjectResolver",
    "ExactScopeCatalogReader",
    "ScopeCatalogEntry",
    "ScopedDutyBinding",
    "ScopedDutyInput",
    "ScopedDutyPolicy",
    "ScopedDutyValidationError",
    "canonical_digest",
    "canonical_json",
    "utc_instant",
]
