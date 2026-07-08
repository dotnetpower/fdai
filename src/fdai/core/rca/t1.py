"""T1 correlation root-cause analysis.

The middle tier of RCA (observability-and-detection.md section 4),
between T0 (a matched rule names the direct cause) and T2 (grounded LLM
reasoning for a novel case). T1 is **deterministic correlation**: given
the events correlated into one incident, it identifies the most probable
antecedent **change / mutation** that preceded the failure within a
bounded window on a related resource - the "a deploy went out, then the
error rate rose" causal chain an on-call engineer reconstructs by hand.

No model call. The hypothesis is grounded on the antecedent event(s) and
is deterministic (the same event set always yields the same cause).
Because correlation is not proof, confidence is bounded below ``1.0`` and
the tier **abstains** (returns ``None``) when no plausible antecedent
change exists in the window - handing the case to T2 rather than guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.rca.contract import (
    Citation,
    CitationKind,
    RcaTier,
    RootCauseHypothesis,
)


@dataclass(frozen=True, slots=True)
class CorrelatedEvent:
    """One member event of an incident, trimmed to what T1 RCA needs.

    ``is_change`` marks a mutation/deploy/config-change event - the class
    of antecedent that can *cause* a downstream failure. ``resource_ref``
    is an opaque, generic reference (never a raw payload or secret).
    """

    event_id: str
    at: datetime
    resource_ref: str
    is_change: bool


# Correlation confidence is deliberately capped: a temporal antecedent is
# a strong hint, not a proof, so T1 never claims T0-style certainty. The
# floor keeps a weak (far-apart) correlation from looking authoritative.
_MAX_CONFIDENCE = 0.85
_MIN_CONFIDENCE = 0.35


def t1_causal_chain(
    *,
    failure_event_id: str,
    failure_at: datetime,
    failure_resource_ref: str,
    correlated_events: Sequence[CorrelatedEvent],
    window: timedelta,
    same_resource_only: bool = False,
) -> RootCauseHypothesis | None:
    """Return a T1 correlation hypothesis, or ``None`` when none is plausible.

    Selects the **latest change event** that occurred strictly before the
    failure and within ``window`` of it - the closest antecedent mutation
    is the most probable trigger. When ``same_resource_only`` is set, only
    changes on the failing resource itself are considered; otherwise any
    correlated resource's change qualifies (cross-resource causation, e.g.
    a shared dependency deploy).

    Confidence scales with temporal proximity: a change one second before
    the failure scores near ``_MAX_CONFIDENCE``; one at the window edge
    scores near ``_MIN_CONFIDENCE``. Ties on timestamp prefer a
    same-resource change (a more direct cause) and then a stable event-id
    order so the result is deterministic.
    """
    if window <= timedelta(0):
        return None

    candidates = [
        event
        for event in correlated_events
        if event.is_change
        and event.event_id != failure_event_id
        and failure_at - window <= event.at < failure_at
        and (not same_resource_only or event.resource_ref == failure_resource_ref)
    ]
    if not candidates:
        return None

    # Latest antecedent wins; break ties deterministically (same-resource
    # first, then event id) so the hypothesis is reproducible.
    def _rank(event: CorrelatedEvent) -> tuple[datetime, bool, str]:
        return (event.at, event.resource_ref == failure_resource_ref, event.event_id)

    trigger = max(candidates, key=_rank)

    lead = failure_at - trigger.at
    confidence = _proximity_confidence(lead=lead, window=window)
    same_resource = trigger.resource_ref == failure_resource_ref
    scope = "same-resource" if same_resource else "upstream-resource"
    cause = (
        f"correlation cause ({scope}): change event '{trigger.event_id}' on "
        f"'{trigger.resource_ref}' at {trigger.at.isoformat()} preceded the "
        f"failure on '{failure_resource_ref}' by {_format_lead(lead)}"
    )
    citations = (
        Citation(kind=CitationKind.EVENT, ref=trigger.event_id),
        Citation(kind=CitationKind.EVENT, ref=failure_event_id),
    )
    return RootCauseHypothesis(
        tier=RcaTier.T1,
        cause=cause,
        confidence=confidence,
        citations=citations,
        evidence_refs=(trigger.event_id, failure_event_id),
        remediation_ref=None,
    )


def _proximity_confidence(*, lead: timedelta, window: timedelta) -> float:
    """Map temporal proximity to a bounded confidence in the T1 band.

    ``lead`` = 0 maps to the max; ``lead`` = ``window`` maps to the min.
    Linear in between. Never returns outside ``[_MIN, _MAX]``.
    """
    fraction = lead.total_seconds() / window.total_seconds()
    fraction = max(0.0, min(1.0, fraction))
    span = _MAX_CONFIDENCE - _MIN_CONFIDENCE
    return round(_MAX_CONFIDENCE - fraction * span, 4)


def _format_lead(lead: timedelta) -> str:
    seconds = int(lead.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{rem}s"
    hours, rem_min = divmod(minutes, 60)
    return f"{hours}h{rem_min}m"


__all__ = ["CorrelatedEvent", "t1_causal_chain"]
