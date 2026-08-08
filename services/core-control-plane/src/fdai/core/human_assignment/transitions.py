"""Pure revisioned transition validation for assignment cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from fdai.core.human_assignment.coverage import approval_quorum_satisfied
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentState,
    EffectKind,
)


class AssignmentTransitionError(ValueError):
    """Raised when a requested lifecycle transition is not valid."""


class StaleAssignmentRevisionError(AssignmentTransitionError):
    """Raised when a command's expected revision is no longer current."""


@dataclass(frozen=True, slots=True)
class TransitionIntent:
    """Compare-and-set intent for one candidate assignment snapshot."""

    expected_revision: int
    target_state: AssignmentState


ALLOWED_TRANSITIONS: Final[Mapping[AssignmentState, frozenset[AssignmentState]]] = MappingProxyType(
    {
        AssignmentState.DRAFT: frozenset(
            {AssignmentState.PENDING_REVIEW, AssignmentState.SUPERSEDED}
        ),
        AssignmentState.PENDING_REVIEW: frozenset(
            {
                AssignmentState.PENDING_REVIEW,
                AssignmentState.APPROVED,
                AssignmentState.REJECTED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.APPROVED: frozenset(
            {
                AssignmentState.OWNERSHIP_PR_OPEN,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.OWNERSHIP_PR_OPEN: frozenset(
            {
                AssignmentState.OWNERSHIP_MERGED,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.OWNERSHIP_MERGED: frozenset(
            {
                AssignmentState.IAM_APPLYING,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.IAM_APPLYING: frozenset(
            {
                AssignmentState.ACTIVE,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.ACTIVE: frozenset({AssignmentState.DEGRADED, AssignmentState.SUPERSEDED}),
        AssignmentState.REJECTED: frozenset(),
        AssignmentState.DEGRADED: frozenset(
            {
                AssignmentState.OWNERSHIP_PR_OPEN,
                AssignmentState.IAM_APPLYING,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.SUPERSEDED: frozenset(),
    }
)


def validate_transition(
    current: AssignmentCase,
    candidate: AssignmentCase,
    transition: TransitionIntent,
) -> None:
    """Validate state order, immutable intent, evidence, and CAS revision."""

    if transition.expected_revision != current.revision:
        raise StaleAssignmentRevisionError(
            f"stale assignment revision: expected={transition.expected_revision}, "
            f"current={current.revision}"
        )
    if candidate.case_id != current.case_id or candidate.intent != current.intent:
        raise AssignmentTransitionError("assignment identity and intent are immutable")
    if transition.target_state is not candidate.state:
        raise AssignmentTransitionError("candidate state does not match transition intent")
    if candidate.revision != current.revision + 1:
        raise AssignmentTransitionError("candidate revision MUST advance by exactly one")
    if candidate.state not in ALLOWED_TRANSITIONS[current.state]:
        raise AssignmentTransitionError(
            f"assignment transition is not allowed: {current.state.value} -> "
            f"{candidate.state.value}"
        )
    if candidate.reviews[: len(current.reviews)] != current.reviews:
        raise AssignmentTransitionError("assignment review receipts are append-only")
    if candidate.effect_receipts[: len(current.effect_receipts)] != current.effect_receipts:
        raise AssignmentTransitionError("assignment effect receipts are append-only")
    if candidate.state is AssignmentState.APPROVED and not approval_quorum_satisfied(
        candidate.intent,
        candidate.reviews,
    ):
        raise AssignmentTransitionError("assignment approval quorum is not satisfied")
    if candidate.state in {AssignmentState.OWNERSHIP_MERGED, AssignmentState.IAM_APPLYING}:
        if EffectKind.OWNERSHIP not in candidate.effect_kinds:
            raise AssignmentTransitionError("ownership effect receipt is required")
    if candidate.state is AssignmentState.ACTIVE and not candidate.has_required_effects:
        raise AssignmentTransitionError(
            "active assignment requires ownership and IAM effect receipts"
        )
    if candidate.state is AssignmentState.DEGRADED and candidate.degraded_reason is None:
        raise AssignmentTransitionError("degraded assignment requires a reason code")
    if candidate.state is AssignmentState.SUPERSEDED and candidate.superseded_by is None:
        raise AssignmentTransitionError("superseded assignment requires a successor case")
    if current.state is AssignmentState.DEGRADED:
        _validate_recovery(candidate)


def _validate_recovery(candidate: AssignmentCase) -> None:
    if candidate.state is AssignmentState.OWNERSHIP_PR_OPEN:
        if EffectKind.OWNERSHIP in candidate.effect_kinds:
            raise AssignmentTransitionError("ownership recovery cannot reopen a merged effect")
    elif candidate.state is AssignmentState.IAM_APPLYING:
        if EffectKind.OWNERSHIP not in candidate.effect_kinds:
            raise AssignmentTransitionError("IAM recovery requires the ownership effect receipt")


__all__ = [
    "ALLOWED_TRANSITIONS",
    "AssignmentTransitionError",
    "StaleAssignmentRevisionError",
    "TransitionIntent",
    "validate_transition",
]
