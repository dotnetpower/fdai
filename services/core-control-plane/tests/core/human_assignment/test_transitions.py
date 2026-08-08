from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.human_assignment.model import (
    AssignmentCase,
    AssignmentIntent,
    AssignmentState,
    DutyBinding,
    EffectKind,
    EffectReceipt,
    ProviderSubject,
    ReviewDecision,
    ReviewReceipt,
)
from fdai.core.human_assignment.transitions import (
    ALLOWED_TRANSITIONS,
    AssignmentTransitionError,
    StaleAssignmentRevisionError,
    TransitionIntent,
    validate_transition,
)
from fdai.core.rbac.roles import Role
from fdai.core.stewardship.model import Duty

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def case(state: AssignmentState = AssignmentState.DRAFT) -> AssignmentCase:
    intent = AssignmentIntent(
        idempotency_key="assignment-1",
        subject=ProviderSubject("entra", "target-1"),
        requested_role=Role.READER,
        duty_bindings=(DutyBinding("Odin", Duty.PRIMARY, "scope:platform"),),
        goal_refs=(),
        requester_ref="requester-1",
        justification="Assign platform ownership and bounded console access.",
    )
    return AssignmentCase(case_id="case-1", intent=intent, state=state)


def candidate(
    current: AssignmentCase,
    state: AssignmentState,
    *,
    intent: AssignmentIntent | None = None,
    reviews: tuple[ReviewReceipt, ...] | None = None,
    effect_receipts: tuple[EffectReceipt, ...] | None = None,
) -> AssignmentCase:
    return replace(
        current,
        intent=current.intent if intent is None else intent,
        state=state,
        revision=current.revision + 1,
        reviews=current.reviews if reviews is None else reviews,
        effect_receipts=(current.effect_receipts if effect_receipts is None else effect_receipts),
    )


def test_state_transition_table_is_closed_and_complete() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(AssignmentState)
    assert AssignmentState.APPROVED not in ALLOWED_TRANSITIONS[AssignmentState.DRAFT]
    assert AssignmentState.ACTIVE not in ALLOWED_TRANSITIONS[AssignmentState.APPROVED]
    assert not ALLOWED_TRANSITIONS[AssignmentState.REJECTED]
    assert not ALLOWED_TRANSITIONS[AssignmentState.SUPERSEDED]


def test_transition_rejects_stale_revision_and_intent_changes() -> None:
    current = case()
    pending = candidate(current, AssignmentState.PENDING_REVIEW)

    with pytest.raises(StaleAssignmentRevisionError, match="stale"):
        validate_transition(current, pending, TransitionIntent(0, pending.state))
    changed = replace(
        pending,
        intent=replace(current.intent, justification="A different immutable assignment intent."),
    )
    with pytest.raises(AssignmentTransitionError, match="intent are immutable"):
        validate_transition(current, changed, TransitionIntent(current.revision, changed.state))


def test_approval_and_ownership_cannot_be_skipped() -> None:
    draft = case()
    ownership = EffectReceipt(EffectKind.OWNERSHIP, "pr:1", "digest-pr", NOW)
    iam = EffectReceipt(EffectKind.IAM, "iam:1", "digest-iam", NOW)
    candidates = (
        candidate(draft, AssignmentState.APPROVED),
        candidate(
            draft,
            AssignmentState.ACTIVE,
            effect_receipts=(ownership, iam),
        ),
    )
    for skipped in candidates:
        with pytest.raises(AssignmentTransitionError, match="not allowed"):
            validate_transition(
                draft,
                skipped,
                TransitionIntent(draft.revision, skipped.state),
            )

    pending = candidate(draft, AssignmentState.PENDING_REVIEW)
    validate_transition(draft, pending, TransitionIntent(draft.revision, pending.state))
    approved_without_review = candidate(pending, AssignmentState.APPROVED)
    with pytest.raises(AssignmentTransitionError, match="quorum"):
        validate_transition(
            pending,
            approved_without_review,
            TransitionIntent(pending.revision, approved_without_review.state),
        )


def test_active_transition_requires_both_effect_receipts() -> None:
    current = case(AssignmentState.IAM_APPLYING)
    ownership = EffectReceipt(EffectKind.OWNERSHIP, "pr:1", "digest-pr", NOW)
    current = replace(current, effect_receipts=(ownership,))

    with pytest.raises(ValueError, match="ownership and IAM"):
        candidate(current, AssignmentState.ACTIVE)

    iam = EffectReceipt(EffectKind.IAM, "iam:1", "digest-iam", NOW)
    active = candidate(
        current,
        AssignmentState.ACTIVE,
        effect_receipts=(ownership, iam),
    )
    validate_transition(current, active, TransitionIntent(current.revision, active.state))


def test_approved_transition_accepts_required_review_evidence() -> None:
    pending = case(AssignmentState.PENDING_REVIEW)
    receipt = ReviewReceipt("owner-1", ReviewDecision.APPROVE, NOW)
    approved = candidate(
        pending,
        AssignmentState.APPROVED,
        reviews=(receipt,),
    )

    validate_transition(pending, approved, TransitionIntent(pending.revision, approved.state))
