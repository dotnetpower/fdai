"""Pure revisioned transition validation for assignment cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

from fdai_service_contracts.human_access_execution import human_access_record_digest

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
                AssignmentState.IAM_APPLYING,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.OWNERSHIP_PR_OPEN: frozenset(
            {
                AssignmentState.OWNERSHIP_MERGED,
                AssignmentState.REVOKED,
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
                AssignmentState.IAM_REVOKED,
                AssignmentState.DEGRADED,
                AssignmentState.SUPERSEDED,
            }
        ),
        AssignmentState.ACTIVE: frozenset({AssignmentState.DEGRADED, AssignmentState.SUPERSEDED}),
        AssignmentState.IAM_REVOKED: frozenset(
            {AssignmentState.OWNERSHIP_PR_OPEN, AssignmentState.DEGRADED}
        ),
        AssignmentState.REVOKED: frozenset(),
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

    if (
        not isinstance(transition.expected_revision, int)
        or isinstance(transition.expected_revision, bool)
        or transition.expected_revision != current.revision
    ):
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
    if candidate.state not in ALLOWED_TRANSITIONS[current.state] and not _exact_inverse_progress(
        current, candidate
    ):
        raise AssignmentTransitionError(
            f"assignment transition is not allowed: {current.state.value} -> "
            f"{candidate.state.value}"
        )
    if candidate.reviews[: len(current.reviews)] != current.reviews:
        raise AssignmentTransitionError("assignment review receipts are append-only")
    if candidate.effect_receipts[: len(current.effect_receipts)] != current.effect_receipts:
        raise AssignmentTransitionError("assignment effect receipts are append-only")
    if candidate.command_receipts[: len(current.command_receipts)] != current.command_receipts:
        raise AssignmentTransitionError("assignment command receipts are append-only")
    for name in ("iam_preparation", "iam_recovery_preparation", "iam_recovery_effect"):
        prior = getattr(current, name)
        if prior is not None and getattr(candidate, name) != prior:
            raise AssignmentTransitionError("assignment original IAM evidence is immutable")
    if (
        current.revocation_case_id is not None
        and candidate.revocation_case_id != current.revocation_case_id
    ):
        raise AssignmentTransitionError("assignment revocation hold is immutable")
    _validate_effect_order(current, candidate)
    if candidate.state is AssignmentState.APPROVED and not approval_quorum_satisfied(
        candidate.intent,
        candidate.reviews,
    ):
        raise AssignmentTransitionError("assignment approval quorum is not satisfied")
    if candidate.intent.revocation is None and candidate.state in {
        AssignmentState.OWNERSHIP_MERGED,
        AssignmentState.IAM_APPLYING,
    }:
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


def _exact_inverse_progress(current: AssignmentCase, candidate: AssignmentCase) -> bool:
    """Allow exact inverse preparation or effect append, not general degraded-state mutation."""
    if (
        current.state is not AssignmentState.DEGRADED
        or candidate.state is not AssignmentState.DEGRADED
    ):
        return False
    preparation = candidate.iam_recovery_preparation
    if current.iam_recovery_preparation is None and preparation is not None:
        return (
            preparation.source_revision == current.revision
            and preparation.prepared_revision == candidate.revision
            and preparation.source_case_digest == human_access_record_digest(current.to_dict())
            and candidate
            == replace(current, revision=current.revision + 1, iam_recovery_preparation=preparation)
        )
    if current.iam_recovery_effect is None and candidate.iam_recovery_effect is not None:
        return (
            current.iam_recovery_preparation is not None
            and current.revision == current.iam_recovery_preparation.prepared_revision
            and candidate
            == replace(
                current,
                revision=current.revision + 1,
                iam_recovery_effect=candidate.iam_recovery_effect,
            )
        )
    return False


def _validate_recovery(candidate: AssignmentCase) -> None:
    if candidate.intent.revocation is not None:
        if candidate.state is AssignmentState.OWNERSHIP_PR_OPEN:
            if EffectKind.IAM not in candidate.effect_kinds:
                raise AssignmentTransitionError("duty removal requires a verified IAM removal")
        elif candidate.state is AssignmentState.IAM_APPLYING:
            if EffectKind.IAM in candidate.effect_kinds:
                raise AssignmentTransitionError(
                    "revocation recovery cannot repeat a verified effect"
                )
        return
    if candidate.state is AssignmentState.OWNERSHIP_PR_OPEN:
        if EffectKind.OWNERSHIP in candidate.effect_kinds:
            raise AssignmentTransitionError("ownership recovery cannot reopen a merged effect")
    elif candidate.state is AssignmentState.IAM_APPLYING:
        if EffectKind.OWNERSHIP not in candidate.effect_kinds:
            raise AssignmentTransitionError("IAM recovery requires the ownership effect receipt")


def _validate_effect_order(current: AssignmentCase, candidate: AssignmentCase) -> None:
    """A grant and a revocation share persistence, never their opposite effect orders."""
    revoke = candidate.intent.revocation is not None
    if revoke:
        if candidate.state in {AssignmentState.OWNERSHIP_MERGED, AssignmentState.ACTIVE}:
            raise AssignmentTransitionError("revocation cannot enter the grant effect order")
        if candidate.state is AssignmentState.IAM_APPLYING and not approval_quorum_satisfied(
            candidate.intent, candidate.reviews
        ):
            raise AssignmentTransitionError("revocation requires its own independent review quorum")
        if candidate.state is AssignmentState.OWNERSHIP_PR_OPEN:
            if EffectKind.IAM not in candidate.effect_kinds:
                raise AssignmentTransitionError("duty removal requires a verified IAM removal")
    elif (
        candidate.state in {AssignmentState.IAM_REVOKED, AssignmentState.REVOKED}
        or current.state is AssignmentState.APPROVED
        and candidate.state is AssignmentState.IAM_APPLYING
    ):
        raise AssignmentTransitionError("grant cannot enter the revocation effect order")


__all__ = [
    "ALLOWED_TRANSITIONS",
    "AssignmentTransitionError",
    "StaleAssignmentRevisionError",
    "TransitionIntent",
    "validate_transition",
]
