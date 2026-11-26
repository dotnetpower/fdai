"""Reconcile provider sources into admitted evidence or explicit holds.

A source is admitted only when it is available, observed no later than the evidence cutoff, and
fresh at that cutoff. Every other outcome becomes a named hold. Nothing here grants activation,
approval, or execution authority.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from fdai.rule_catalog.schema.framework_assessment import canonical_digest


class SourceState(StrEnum):
    """State a provider reports for one evidence source."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    REVOKED = "revoked"
    CONFLICTING = "conflicting"


class HoldReason(StrEnum):
    """Bounded reasons a source cannot support a qualification claim."""

    UNAVAILABLE = "unavailable"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    REVOKED = "revoked"
    CONFLICTING = "conflicting"
    OBSERVED_AFTER_CUTOFF = "observed_after_cutoff"
    MISSING_REQUIRED = "missing_required"
    DUPLICATE_CONFLICT = "duplicate_conflict"


_STATE_HOLD = {
    SourceState.UNAVAILABLE: HoldReason.UNAVAILABLE,
    SourceState.STALE: HoldReason.STALE,
    SourceState.INCOMPLETE: HoldReason.INCOMPLETE,
    SourceState.REVOKED: HoldReason.REVOKED,
    SourceState.CONFLICTING: HoldReason.CONFLICTING,
}


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """One provider observation with authenticated scope and source identity."""

    source_id: str
    scope_id: str
    identity_ref: str
    state: SourceState
    observed_at: datetime
    evidence_digest: str

    def __post_init__(self) -> None:
        if not (self.source_id and self.scope_id and self.identity_ref):
            raise ValueError("source observation MUST name its source, scope, and identity")
        if self.observed_at.tzinfo is None:
            raise ValueError("source observation time MUST be timezone-aware")
        if not self.evidence_digest.startswith("sha256:"):
            raise ValueError("source observation MUST carry a sha256 evidence digest")


@dataclass(frozen=True, slots=True)
class SourceHold:
    """A source that cannot support the claim, and why."""

    source_id: str
    reason: HoldReason


@dataclass(frozen=True, slots=True)
class SourceReconciliation:
    """Admitted sources, explicit holds, and a digest binding both to the cutoff."""

    evidence_cutoff: datetime
    admitted: tuple[SourceObservation, ...]
    holds: tuple[SourceHold, ...]
    digest: str

    @property
    def complete(self) -> bool:
        return not self.holds


def reconcile_sources(
    observations: Iterable[SourceObservation],
    *,
    required_source_ids: Sequence[str],
    evidence_cutoff: datetime,
    max_age: timedelta,
) -> SourceReconciliation:
    """Admit fresh available sources and hold everything else by name."""

    if evidence_cutoff.tzinfo is None:
        raise ValueError("evidence cutoff MUST be timezone-aware")
    if max_age <= timedelta(0):
        raise ValueError("maximum source age MUST be positive")
    required = tuple(dict.fromkeys(required_source_ids))
    if not required:
        raise ValueError("at least one required source MUST be named")
    by_source: dict[str, list[SourceObservation]] = defaultdict(list)
    for observation in observations:
        by_source[observation.source_id].append(observation)

    admitted: list[SourceObservation] = []
    holds: list[SourceHold] = []
    for source_id in sorted(set(required) | set(by_source)):
        candidates = by_source.get(source_id, [])
        if not candidates:
            holds.append(SourceHold(source_id, HoldReason.MISSING_REQUIRED))
            continue
        if len({_identity(item) for item in candidates}) > 1:
            holds.append(SourceHold(source_id, HoldReason.DUPLICATE_CONFLICT))
            continue
        observation = candidates[0]
        reason = _hold_reason(observation, evidence_cutoff, max_age)
        if reason is None:
            admitted.append(observation)
        else:
            holds.append(SourceHold(source_id, reason))

    admitted_sorted = tuple(sorted(admitted, key=lambda item: item.source_id))
    holds_sorted = tuple(sorted(holds, key=lambda item: (item.source_id, item.reason.value)))
    digest = canonical_digest(
        {
            "evidence_cutoff": evidence_cutoff.isoformat(),
            "admitted": [
                [item.source_id, item.scope_id, item.identity_ref, item.evidence_digest]
                for item in admitted_sorted
            ],
            "holds": [[hold.source_id, hold.reason.value] for hold in holds_sorted],
        }
    )
    return SourceReconciliation(evidence_cutoff, admitted_sorted, holds_sorted, digest)


def _identity(observation: SourceObservation) -> tuple[str, str, str, str, str]:
    return (
        observation.scope_id,
        observation.identity_ref,
        observation.state.value,
        observation.observed_at.isoformat(),
        observation.evidence_digest,
    )


def _hold_reason(
    observation: SourceObservation, cutoff: datetime, max_age: timedelta
) -> HoldReason | None:
    if observation.state is not SourceState.AVAILABLE:
        return _STATE_HOLD[observation.state]
    if observation.observed_at > cutoff:
        return HoldReason.OBSERVED_AFTER_CUTOFF
    if cutoff - observation.observed_at > max_age:
        return HoldReason.STALE
    return None
