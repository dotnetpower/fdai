"""Deterministic adjudication of repeated authoritative observations of one target.

FDAI-CONST-002 requires conflicting authoritative sources to remain an explicit conflict
that lowers autonomy, and forbids resolving the disagreement by averaging, by preferring
the most recent report, or by weighting one source higher than another. This module is the
adjudication half of that contract: it decides *whether* independently reported claims about
the same target agree, and names the exact disagreements. Consumers of
``StateFactMetadata.conflicts`` already own the demotion half.

The scope is intentionally narrow: two or more observations of the same neutral resource
identity inside one promoted inventory generation. It is pure, provider-neutral, and never
selects a winning value.

An empty conflict tuple means the compared claims agreed. It never means the target was
independently corroborated, and it never proves absence of a conflict that no source
reported.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

#: Bounded conflict evidence. A wider disagreement is truncated to a stable marker so a
#: hostile or malfunctioning source cannot grow the projected metadata without bound.
MAX_OBSERVATION_CONFLICTS = 32
_MAX_CONFLICT_KEY_CHARS = 96
_CANONICAL_PROVIDER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")

CONFLICT_PROPERTY_PREFIX = "observed_property_conflict"
CONFLICT_TRUNCATED = "observed_property_conflict_truncated"
CONFLICT_PROVIDER_REF = "observed_provider_ref_conflict"


class ObservationIdentityConflictError(ValueError):
    """Two observations of one neutral identity disagree on the target's type.

    This is an identity-level contradiction rather than a value disagreement: the
    projection cannot type the object's endpoints, so it fails closed instead of
    publishing a contested type.
    """


@dataclass(frozen=True, slots=True)
class ObservedClaim:
    """One authoritative observation of a single target inside one generation."""

    type: str
    properties: Mapping[str, Any]
    provider_ref: str | None = None
    observed_at: datetime | None = None
    target_id: str | None = None
    generation_id: str | None = None


class ProviderIdentityVerifier(Protocol):
    """Verify one provider identity in the exact target-generation context."""

    def verify(
        self,
        *,
        provider_ref: str,
        target_id: str,
        generation_id: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ObservationVerdict:
    """Adjudicated agreement over repeated observations of one target.

    ``agreed_properties`` holds only the property keys every claim reported with an
    identical value. A contested key is absent, so no consumer can read a contested
    value. ``observed_at`` is the earliest reported observation time, which is the
    conservative choice for freshness; it never selects which claim's values win.
    """

    type: str
    agreed_properties: Mapping[str, Any]
    observed_at: datetime | None
    conflicts: tuple[str, ...]
    target_id: str | None = None
    generation_id: str | None = None

    @property
    def contested(self) -> bool:
        return bool(self.conflicts)


def adjudicate_observations(claims: Sequence[ObservedClaim]) -> ObservationVerdict:
    """Return the agreed content and the explicit conflicts across repeated claims.

    Raises:
        ValueError: ``claims`` is empty.
        ObservationIdentityConflictError: the claims disagree on the observed type.
    """

    return _adjudicate(claims, flag_provider_conflict=True)


def adjudicate_independent_observations(
    claims: Sequence[ObservedClaim],
    *,
    provider_identity_verifier: ProviderIdentityVerifier,
) -> ObservationVerdict:
    """Adjudicate two or more distinct provider observations without selecting a winner.

    Agreement across providers is an empty conflict result, while a differing
    property is withheld and named in the conflict tuple. Provider identity is
    a prerequisite for this mode, not a conflict itself.
    """

    if len(claims) < 2:
        raise ValueError("independent observation adjudication requires at least two claims")
    providers = tuple(claim.provider_ref for claim in claims)
    if any(
        not isinstance(provider, str)
        or provider != provider.strip().casefold()
        or _CANONICAL_PROVIDER.fullmatch(provider) is None
        for provider in providers
    ) or len(set(providers)) != len(claims):
        raise ValueError(
            "independent observations require verified canonical providers for one target "
            "generation"
        )
    target_id = claims[0].target_id
    generation_id = claims[0].generation_id
    if (
        not isinstance(target_id, str)
        or target_id != target_id.strip()
        or not target_id
        or len(target_id) > 1_024
        or any(claim.target_id != target_id for claim in claims)
        or not isinstance(generation_id, str)
        or generation_id != generation_id.strip()
        or not generation_id
        or len(generation_id) > 512
        or any(claim.generation_id != generation_id for claim in claims)
    ):
        raise ValueError(
            "independent observations require verified canonical providers for one target "
            "generation"
        )
    if not all(
        provider_identity_verifier.verify(
            provider_ref=provider,
            target_id=target_id,
            generation_id=generation_id,
        )
        for provider in providers
        if isinstance(provider, str)
    ):
        raise ValueError(
            "independent observations require verified canonical providers for one target "
            "generation"
        )
    return _adjudicate(
        claims,
        flag_provider_conflict=False,
        target_id=target_id,
        generation_id=generation_id,
    )


def _adjudicate(
    claims: Sequence[ObservedClaim],
    *,
    flag_provider_conflict: bool,
    target_id: str | None = None,
    generation_id: str | None = None,
) -> ObservationVerdict:
    if not claims:
        raise ValueError("observation adjudication requires at least one claim")
    types = {claim.type.strip() for claim in claims}
    if len(types) != 1:
        raise ObservationIdentityConflictError(
            "observed target type disagrees across observations in one generation"
        )
    observed_type = types.pop()
    observed_at = _earliest(claim.observed_at for claim in claims)

    if len(claims) == 1:
        return ObservationVerdict(
            type=observed_type,
            agreed_properties=dict(claims[0].properties),
            observed_at=observed_at,
            conflicts=(),
            target_id=target_id,
            generation_id=generation_id,
        )

    conflicts: set[str] = set()
    provider_refs = {claim.provider_ref for claim in claims}
    if flag_provider_conflict and len(provider_refs) != 1:
        conflicts.add(CONFLICT_PROVIDER_REF)

    agreed: dict[str, Any] = {}
    for key in sorted({str(key) for claim in claims for key in claim.properties}):
        encoded = {_canonical(claim.properties.get(key, _ABSENT)) for claim in claims}
        if len(encoded) == 1:
            agreed[key] = claims[0].properties[key]
            continue
        conflicts.add(f"{CONFLICT_PROPERTY_PREFIX}:{_bounded_key(key)}")

    return ObservationVerdict(
        type=observed_type,
        agreed_properties=agreed,
        observed_at=observed_at,
        conflicts=_bounded_conflicts(conflicts),
        target_id=target_id,
        generation_id=generation_id,
    )


_ABSENT = object()


def _canonical(value: Any) -> str:
    """Encode one reported value so equality is exact and order-independent."""

    if value is _ABSENT:
        return "\u0000absent"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=repr)


def _bounded_key(key: str) -> str:
    if len(key) <= _MAX_CONFLICT_KEY_CHARS:
        return key
    return key[:_MAX_CONFLICT_KEY_CHARS]


def _bounded_conflicts(conflicts: set[str]) -> tuple[str, ...]:
    ordered = sorted(conflicts)
    if len(ordered) <= MAX_OBSERVATION_CONFLICTS:
        return tuple(ordered)
    return (*ordered[: MAX_OBSERVATION_CONFLICTS - 1], CONFLICT_TRUNCATED)


def _earliest(values: Iterable[datetime | None]) -> datetime | None:
    aware = [value.astimezone(UTC) for value in values if value is not None]
    return min(aware) if aware else None


__all__ = [
    "CONFLICT_PROPERTY_PREFIX",
    "CONFLICT_PROVIDER_REF",
    "CONFLICT_TRUNCATED",
    "MAX_OBSERVATION_CONFLICTS",
    "ObservationIdentityConflictError",
    "ObservationVerdict",
    "ObservedClaim",
    "ProviderIdentityVerifier",
    "adjudicate_independent_observations",
    "adjudicate_observations",
]
