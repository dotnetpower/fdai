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


def test_transition_guards_immutability_append_only_recovery_and_inverse_progress() -> None:
    from fdai.core.human_assignment.command_receipt import AssignmentCommandReceipt
    from fdai.core.human_assignment.revocation_intent import AssignmentRevocation
    from fdai_service_contracts.human_access_execution import (
        HumanAccessPreparation,
        human_access_record_digest,
    )

    draft = case()
    pending = candidate(draft, AssignmentState.PENDING_REVIEW)

    # Mismatched transition intent state or bad revision step
    with pytest.raises(AssignmentTransitionError, match="does not match transition intent"):
        validate_transition(draft, pending, TransitionIntent(draft.revision, AssignmentState.DRAFT))
    with pytest.raises(AssignmentTransitionError, match="advance by exactly one"):
        validate_transition(
            draft,
            replace(pending, revision=draft.revision + 2),
            TransitionIntent(draft.revision, pending.state),
        )

    # Append-only reviews, effect_receipts, command_receipts
    r1 = ReviewReceipt("owner-1", ReviewDecision.APPROVE, NOW)
    r2 = ReviewReceipt("owner-2", ReviewDecision.APPROVE, NOW)
    with_rev = replace(pending, reviews=(r1,))
    with pytest.raises(AssignmentTransitionError, match="review receipts are append-only"):
        validate_transition(
            with_rev,
            replace(
                with_rev,
                state=AssignmentState.APPROVED,
                revision=with_rev.revision + 1,
                reviews=(r2,),
            ),
            TransitionIntent(with_rev.revision, AssignmentState.APPROVED),
        )

    own_eff = EffectReceipt(EffectKind.OWNERSHIP, "pr:1", "digest-pr", NOW)
    other_eff = EffectReceipt(EffectKind.OWNERSHIP, "pr:2", "digest-pr2", NOW)
    merged = replace(
        draft,
        state=AssignmentState.OWNERSHIP_MERGED,
        effect_receipts=(own_eff,),
    )
    with pytest.raises(AssignmentTransitionError, match="effect receipts are append-only"):
        validate_transition(
            merged,
            replace(
                merged,
                state=AssignmentState.IAM_APPLYING,
                revision=2,
                effect_receipts=(other_eff,),
            ),
            TransitionIntent(merged.revision, AssignmentState.IAM_APPLYING),
        )

    cmd1 = AssignmentCommandReceipt("operator-" + "a" * 32, "a" * 64)
    cmd2 = AssignmentCommandReceipt("operator-" + "b" * 32, "b" * 64)
    with_cmd = replace(draft, command_receipts=(cmd1,))
    with pytest.raises(AssignmentTransitionError, match="command receipts are append-only"):
        validate_transition(
            with_cmd,
            replace(
                with_cmd,
                state=AssignmentState.PENDING_REVIEW,
                revision=2,
                command_receipts=(cmd2,),
            ),
            TransitionIntent(with_cmd.revision, AssignmentState.PENDING_REVIEW),
        )

    # Immutable iam_preparation and revocation_case_id
    prep1 = HumanAccessPreparation(
        material_digest="a" * 64,
        source_case_digest="b" * 64,
        source_revision=1,
        prepared_revision=2,
    )
    prep2 = HumanAccessPreparation(
        material_digest="c" * 64,
        source_case_digest="b" * 64,
        source_revision=1,
        prepared_revision=2,
    )
    applying = replace(
        merged,
        state=AssignmentState.IAM_APPLYING,
        revision=2,
        iam_preparation=prep1,
    )
    with pytest.raises(AssignmentTransitionError, match="original IAM evidence is immutable"):
        validate_transition(
            applying,
            replace(
                applying,
                state=AssignmentState.DEGRADED,
                revision=3,
                degraded_reason="err",
                iam_preparation=prep2,
            ),
            TransitionIntent(applying.revision, AssignmentState.DEGRADED),
        )

    held = replace(
        merged,
        state=AssignmentState.DEGRADED,
        degraded_reason="revocation_pending",
        revocation_case_id="rev-1",
    )
    with pytest.raises(AssignmentTransitionError, match="revocation hold is immutable"):
        validate_transition(
            held,
            replace(
                held,
                state=AssignmentState.SUPERSEDED,
                revision=2,
                superseded_by="rev-1",
                revocation_case_id="rev-2",
            ),
            TransitionIntent(held.revision, AssignmentState.SUPERSEDED),
        )

    # Missing ownership effect on IAM_APPLYING
    pr_open = replace(draft, state=AssignmentState.OWNERSHIP_PR_OPEN)
    degraded_no_own = replace(pr_open, state=AssignmentState.DEGRADED, degraded_reason="pr_failed")
    with pytest.raises(AssignmentTransitionError, match="ownership effect receipt is required"):
        validate_transition(
            degraded_no_own,
            replace(
                degraded_no_own,
                state=AssignmentState.IAM_APPLYING,
                revision=2,
                degraded_reason=None,
            ),
            TransitionIntent(degraded_no_own.revision, AssignmentState.IAM_APPLYING),
        )

    # Degraded recovery validation for grant and revocation
    degraded_with_own = replace(
        merged, state=AssignmentState.DEGRADED, degraded_reason="iam_failed"
    )
    with pytest.raises(
        AssignmentTransitionError, match="ownership recovery cannot reopen a merged effect"
    ):
        validate_transition(
            degraded_with_own,
            replace(
                degraded_with_own,
                state=AssignmentState.OWNERSHIP_PR_OPEN,
                revision=2,
                degraded_reason=None,
            ),
            TransitionIntent(degraded_with_own.revision, AssignmentState.OWNERSHIP_PR_OPEN),
        )

    rev_intent = replace(
        draft.intent,
        revocation=AssignmentRevocation(
            case_id="old-1",
            revision=4,
            replacement_revisions={"rep-1": 2, "rep-2": 2},
        ),
    )
    rev_approved = AssignmentCase(
        case_id="rev-case",
        intent=rev_intent,
        state=AssignmentState.APPROVED,
        reviews=(r1,),
    )
    rev_pr_open = replace(rev_approved, state=AssignmentState.OWNERSHIP_PR_OPEN)
    rev_merged_bad = replace(rev_pr_open, revision=2)
    object.__setattr__(rev_merged_bad, "state", AssignmentState.OWNERSHIP_MERGED)
    with pytest.raises(
        AssignmentTransitionError, match="revocation cannot enter the grant effect order"
    ):
        validate_transition(
            rev_pr_open,
            rev_merged_bad,
            TransitionIntent(rev_pr_open.revision, AssignmentState.OWNERSHIP_MERGED),
        )
    rev_applying_unreviewed = replace(
        rev_approved,
        state=AssignmentState.IAM_APPLYING,
        revision=2,
    )
    object.__setattr__(rev_applying_unreviewed, "reviews", ())
    rev_approved_unreviewed = replace(rev_approved)
    object.__setattr__(rev_approved_unreviewed, "reviews", ())
    with pytest.raises(
        AssignmentTransitionError, match="revocation requires its own independent review quorum"
    ):
        validate_transition(
            rev_approved_unreviewed,
            rev_applying_unreviewed,
            TransitionIntent(rev_approved_unreviewed.revision, AssignmentState.IAM_APPLYING),
        )

    rev_degraded = replace(
        rev_approved,
        state=AssignmentState.DEGRADED,
        degraded_reason="iam_failed",
    )
    with pytest.raises(
        AssignmentTransitionError, match="duty removal requires a verified IAM removal"
    ):
        validate_transition(
            rev_degraded,
            replace(
                rev_degraded,
                state=AssignmentState.OWNERSHIP_PR_OPEN,
                revision=2,
                degraded_reason=None,
            ),
            TransitionIntent(rev_degraded.revision, AssignmentState.OWNERSHIP_PR_OPEN),
        )

    iam_eff = EffectReceipt(EffectKind.IAM, "iam:1", "digest-iam", NOW)
    rev_degraded_with_iam = replace(rev_degraded, effect_receipts=(iam_eff,))
    with pytest.raises(
        AssignmentTransitionError, match="revocation recovery cannot repeat a verified effect"
    ):
        validate_transition(
            rev_degraded_with_iam,
            replace(
                rev_degraded_with_iam,
                state=AssignmentState.IAM_APPLYING,
                revision=2,
                degraded_reason=None,
            ),
            TransitionIntent(rev_degraded_with_iam.revision, AssignmentState.IAM_APPLYING),
        )

    # Grant cannot enter revocation effect order
    approved_grant = replace(draft, state=AssignmentState.APPROVED, reviews=(r1,))
    with pytest.raises(
        AssignmentTransitionError, match="grant cannot enter the revocation effect order"
    ):
        validate_transition(
            approved_grant,
            replace(approved_grant, state=AssignmentState.IAM_APPLYING, revision=2),
            TransitionIntent(approved_grant.revision, AssignmentState.IAM_APPLYING),
        )

    # Exact inverse progress (DEGRADED -> DEGRADED with recovery prep and effect)
    degraded_from_applying = replace(
        applying,
        state=AssignmentState.DEGRADED,
        revision=3,
        degraded_reason="iam_failed",
    )
    rec_prep = HumanAccessPreparation(
        material_digest="d" * 64,
        source_case_digest=human_access_record_digest(degraded_from_applying.to_dict()),
        source_revision=degraded_from_applying.revision,
        prepared_revision=degraded_from_applying.revision + 1,
    )
    degraded_rec_prep = replace(
        degraded_from_applying,
        revision=degraded_from_applying.revision + 1,
        iam_recovery_preparation=rec_prep,
    )
    validate_transition(
        degraded_from_applying,
        degraded_rec_prep,
        TransitionIntent(degraded_from_applying.revision, AssignmentState.DEGRADED),
    )
    degraded_rec_eff = replace(
        degraded_rec_prep,
        revision=degraded_rec_prep.revision + 1,
        iam_recovery_effect=iam_eff,
    )
    validate_transition(
        degraded_rec_prep,
        degraded_rec_eff,
        TransitionIntent(degraded_rec_prep.revision, AssignmentState.DEGRADED),
    )
    with pytest.raises(AssignmentTransitionError, match="not allowed"):
        validate_transition(
            degraded_from_applying,
            replace(degraded_from_applying, revision=degraded_from_applying.revision + 1),
            TransitionIntent(degraded_from_applying.revision, AssignmentState.DEGRADED),
        )

    # Bypassed model invariants caught by validate_transition (lines 163, 167, 169)
    act_bad = replace(
        applying,
        state=AssignmentState.ACTIVE,
        revision=applying.revision + 1,
        effect_receipts=(own_eff, iam_eff),
    )
    object.__setattr__(act_bad, "effect_receipts", (own_eff,))
    with pytest.raises(AssignmentTransitionError, match="ownership and IAM effect receipts"):
        validate_transition(
            applying, act_bad, TransitionIntent(applying.revision, AssignmentState.ACTIVE)
        )

    deg_bad = replace(
        applying,
        state=AssignmentState.DEGRADED,
        revision=applying.revision + 1,
        degraded_reason="err",
    )
    object.__setattr__(deg_bad, "degraded_reason", None)
    with pytest.raises(AssignmentTransitionError, match="requires a reason code"):
        validate_transition(
            applying, deg_bad, TransitionIntent(applying.revision, AssignmentState.DEGRADED)
        )

    sup_bad = replace(
        draft,
        state=AssignmentState.SUPERSEDED,
        revision=draft.revision + 1,
        superseded_by="succ-1",
    )
    object.__setattr__(sup_bad, "superseded_by", None)
    with pytest.raises(AssignmentTransitionError, match="requires a successor case"):
        validate_transition(
            draft, sup_bad, TransitionIntent(draft.revision, AssignmentState.SUPERSEDED)
        )

    # Valid recovery transitions from DEGRADED (lines 214, 216->exit)
    validate_transition(
        rev_degraded,
        replace(
            rev_degraded,
            state=AssignmentState.IAM_APPLYING,
            revision=rev_degraded.revision + 1,
            degraded_reason=None,
        ),
        TransitionIntent(rev_degraded.revision, AssignmentState.IAM_APPLYING),
    )
    validate_transition(
        degraded_no_own,
        replace(
            degraded_no_own,
            state=AssignmentState.OWNERSHIP_PR_OPEN,
            revision=degraded_no_own.revision + 1,
            degraded_reason=None,
        ),
        TransitionIntent(degraded_no_own.revision, AssignmentState.OWNERSHIP_PR_OPEN),
    )
