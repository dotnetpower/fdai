"""Cross-vertical precedence resolver for the P3 unified control loop.

Phase 3 § Unified Control Loop / Cross-vertical conflict handling.

When two verticals target the same resource in the same window
(e.g. a Cost idle-shutdown vs a DR failover rehearsal, or a Change
reconcile vs a rightsizing PR), the loop resolves by fixed precedence:

    Resilience safety hold > Change Safety > Cost Governance

The lower-precedence action is **deferred and re-evaluated** at a later
tick, or **escalated to HIL** if it cannot be safely deferred. Conflicts
never resolve by racing.

Contract
--------

The resolver is a pure function: given a list of proposed actions on the
same resource, return each one's :class:`PrecedenceOutcome`. Callers
persist the outcome + reason on their audit entry so a deferral is
reconstructable.

Scope
-----

This module governs **selection** among competing actions. Actual
serialization on a per-resource key still happens at the executor's
:class:`~fdai.core.executor.lock.ResourceLockManager` - even after
this resolver picks a winner, the executor holds the lock for the whole
action window per phase-3 § Ordering and locking.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class Vertical(StrEnum):
    """The three initial verticals + a `resilience_safety_hold` supra-vertical.

    A safety hold is a Resilience action that MUST NOT be pre-empted
    (e.g. an active failover, an in-progress restore rehearsal). It
    takes precedence over any Change / Cost action.
    """

    RESILIENCE_SAFETY_HOLD = "resilience_safety_hold"
    RESILIENCE = "resilience"
    CHANGE_SAFETY = "change_safety"
    COST = "cost"


class PrecedenceOutcome(StrEnum):
    """Terminal outcome for one candidate action after the resolver runs."""

    WIN = "win"
    """Highest precedence on this resource for this window - proceeds
    to the risk-gate + executor."""

    DEFER = "defer"
    """Lower precedence but safely deferrable - re-evaluated on the
    next tick. Not executed now; audited."""

    ESCALATE_HIL = "escalate_hil"
    """Not safely deferrable - hand to HIL. Executor does NOT act."""


@dataclass(frozen=True, slots=True)
class CandidateAction:
    """Minimal descriptor the resolver needs about a proposed action.

    Kept intentionally small so the resolver stays pure; the
    :class:`~fdai.shared.contracts.models.Action` model itself
    carries the full detail.
    """

    action_id: str
    resource_id: str
    vertical: Vertical
    deferrable: bool = True
    """False when a deferral would violate a safety invariant (e.g. a
    rollback that MUST land before the next drift check). Forced to HIL
    by the resolver when it loses on precedence."""


@dataclass(frozen=True, slots=True)
class PrecedenceDecision:
    """Frozen record per candidate."""

    action_id: str
    vertical: Vertical
    outcome: PrecedenceOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)
    """Empty on WIN; carries the loser's identity/vertical on DEFER /
    ESCALATE_HIL so the audit entry names the conflict."""


# Fixed precedence order (higher index → higher priority).
_PRECEDENCE: dict[Vertical, int] = {
    Vertical.COST: 0,
    Vertical.CHANGE_SAFETY: 1,
    Vertical.RESILIENCE: 2,
    Vertical.RESILIENCE_SAFETY_HOLD: 3,
}


class PrecedenceResolver:
    """Compute per-candidate precedence decisions on shared resources."""

    def resolve(self, candidates: Iterable[CandidateAction]) -> tuple[PrecedenceDecision, ...]:
        """Return one :class:`PrecedenceDecision` per candidate.

        Candidates are grouped by ``resource_id``. Within a group the
        highest-precedence candidate wins; every other candidate is
        deferred (or escalated to HIL when not ``deferrable``). Groups
        of size 1 always win - no conflict.
        """
        candidates_tuple = tuple(candidates)
        decisions: list[PrecedenceDecision] = []
        by_resource: dict[str, list[CandidateAction]] = {}
        for cand in candidates_tuple:
            by_resource.setdefault(cand.resource_id, []).append(cand)

        for resource_id, group in by_resource.items():
            if len(group) == 1:
                sole = group[0]
                decisions.append(
                    PrecedenceDecision(
                        action_id=sole.action_id,
                        vertical=sole.vertical,
                        outcome=PrecedenceOutcome.WIN,
                    )
                )
                continue

            # Winner: highest precedence rank; tie-break by earliest action_id
            # (deterministic ordering when two actions from the same vertical
            # collide - extremely rare, still worth pinning). Precedence is
            # negated so a single ascending sort ranks highest-precedence
            # first while still breaking ties on the SMALLEST action_id
            # (a shared reverse=True would have picked the largest instead).
            group_sorted = sorted(
                group,
                key=lambda c: (-_PRECEDENCE[c.vertical], c.action_id),
            )
            winner = group_sorted[0]
            losers = group_sorted[1:]

            decisions.append(
                PrecedenceDecision(
                    action_id=winner.action_id,
                    vertical=winner.vertical,
                    outcome=PrecedenceOutcome.WIN,
                )
            )
            for loser in losers:
                reason = (
                    f"lost_to:{winner.vertical.value}:"
                    f"resource={resource_id}:winner_action_id={winner.action_id}"
                )
                if loser.deferrable:
                    decisions.append(
                        PrecedenceDecision(
                            action_id=loser.action_id,
                            vertical=loser.vertical,
                            outcome=PrecedenceOutcome.DEFER,
                            reasons=(reason,),
                        )
                    )
                else:
                    decisions.append(
                        PrecedenceDecision(
                            action_id=loser.action_id,
                            vertical=loser.vertical,
                            outcome=PrecedenceOutcome.ESCALATE_HIL,
                            reasons=(reason, "not_safely_deferrable"),
                        )
                    )

        return tuple(decisions)


__all__ = [
    "CandidateAction",
    "PrecedenceDecision",
    "PrecedenceOutcome",
    "PrecedenceResolver",
    "Vertical",
]
