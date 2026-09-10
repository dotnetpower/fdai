"""Record model tests for the A3-E inert promotion-candidate lifecycle.

Covers:
- Candidate creation, field validation, candidate_id digest binding
- Creator/reviewer separation (SELF_REVIEW)
- Duplicate and conflicting reviews (DUPLICATE_REVIEW, CONFLICTING_REVIEW)
- Agent/executor identity rejection at the record boundary
- Evidence gap denial (MISSING_EVIDENCE)
- Rejection denial (REJECTION)
- Provider-ineligible ActionType denial at creation (PROVIDER_INELIGIBLE)
- Lease contract version enforcement (LEASE_INCOMPATIBLE)
- Quorum approval path → APPROVED
- Atomic two-phase audit: intent digest captured before mutation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    instant,
)
from fdai.core.standing_authority.promotion_candidate import (
    LEASE_CONTRACT_VERSION,
    CandidateReviewRecord,
    CandidateStatus,
    CandidateTransitionKind,
    DenialReason,
    PromotionCandidateRecord,
    PromotionCandidateWriteResult,
    ReviewDecision,
    build_candidate_record,
    plan_create_transition,
    plan_review_transition,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
REVISION_ID = "sha256:" + "a" * 64
AUTH_DIGEST = "sha256:" + "f" * 64
EVIDENCE_1 = "sha256:" + "e1" + "0" * 62
EVIDENCE_2 = "sha256:" + "e2" + "0" * 62
EVIDENCE_ALL = (EVIDENCE_1, EVIDENCE_2)
CREATOR = "human:creator"
REVIEWER_A = "human:reviewer-a"
REVIEWER_B = "human:reviewer-b"
REVIEWER_C = "human:reviewer-c"

FENCE = LifecycleFence(
    family_id="family:one",
    revision_id=REVISION_ID,
    fencing_generation=3,
    transition_digest="sha256:" + "d" * 64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(**overrides: object) -> PromotionCandidateRecord:
    kwargs: dict[str, object] = dict(
        family_id="family:one",
        revision_id=REVISION_ID,
        fence=FENCE,
        eligible_action_types=("ops.scale-out",),
        ineligible_provider_action_types=(),
        evidence_requirements=(EVIDENCE_1, EVIDENCE_2),
        source_revision_id="source:v1",
        creator_principal=CREATOR,
        authentication_evidence_digest=AUTH_DIGEST,
        created_at=NOW,
        required_reviewer_principals=(REVIEWER_A, REVIEWER_B),
        quorum_required=2,
    )
    kwargs.update(overrides)
    return build_candidate_record(**kwargs)  # type: ignore[arg-type]


def _build_review(
    candidate_id: str,
    reviewer_principal: str,
    decision: ReviewDecision,
    reviewed_at: datetime,
    authentication_evidence_digest: str,
    evidence_digests: tuple[str, ...],
) -> CandidateReviewRecord:
    from fdai.core.standing_authority.lifecycle_codec import content_digest as _cd

    review_id = _cd(
        {
            "candidate_id": candidate_id,
            "reviewer_principal": reviewer_principal,
            "decision": decision.value,
            "reviewed_at": instant(aware_utc(reviewed_at)),
            "authentication_evidence_digest": authentication_evidence_digest,
            "evidence_digests": sorted(evidence_digests),
        }
    )
    return CandidateReviewRecord(
        review_id=review_id,
        candidate_id=candidate_id,
        reviewer_principal=reviewer_principal,
        decision=decision,
        reviewed_at=reviewed_at,
        authentication_evidence_digest=authentication_evidence_digest,
        evidence_digests=evidence_digests,
    )


def _review(
    record: PromotionCandidateRecord,
    *,
    reviewer: str = REVIEWER_A,
    decision: ReviewDecision = ReviewDecision.APPROVE,
    evidence: tuple[str, ...] = EVIDENCE_ALL,
    at: datetime | None = None,
) -> CandidateReviewRecord:
    return _build_review(
        candidate_id=record.candidate_id,
        reviewer_principal=reviewer,
        decision=decision,
        reviewed_at=at or (NOW + timedelta(minutes=1)),
        authentication_evidence_digest=AUTH_DIGEST,
        evidence_digests=evidence,
    )


def _create(record: PromotionCandidateRecord) -> PromotionCandidateWriteResult:
    return plan_create_transition(record)


def _apply_review(
    result: PromotionCandidateWriteResult,
    record: PromotionCandidateRecord,
    review: CandidateReviewRecord,
) -> PromotionCandidateWriteResult:
    return plan_review_transition(record=record, snapshot=result.snapshot, review=review)


# ---------------------------------------------------------------------------
# Tests: creation and validation
# ---------------------------------------------------------------------------


def test_build_candidate_record_produces_correct_id() -> None:
    rec = _record()
    assert rec.candidate_id.startswith("sha256:")
    assert rec.lease_contract_version == LEASE_CONTRACT_VERSION
    assert rec.execution_authority is False
    assert rec.promotion_authority is False


def test_candidate_id_is_stable_across_builds() -> None:
    assert _record().candidate_id == _record().candidate_id


def test_candidate_builder_canonicalizes_set_shaped_fields() -> None:
    left = _record(
        eligible_action_types=("ops.scale-out", "ops.restart"),
        required_reviewer_principals=(REVIEWER_B, REVIEWER_A),
    )
    right = _record(
        eligible_action_types=("ops.restart", "ops.scale-out"),
        required_reviewer_principals=(REVIEWER_A, REVIEWER_B),
    )

    assert left == right
    assert left.eligible_action_types == ("ops.restart", "ops.scale-out")
    assert left.required_reviewer_principals == (REVIEWER_A, REVIEWER_B)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("eligible_action_types", ("ops.scale-out", "ops.scale-out")),
        ("evidence_requirements", (EVIDENCE_1, EVIDENCE_1)),
        ("required_reviewer_principals", (REVIEWER_A, REVIEWER_A)),
    ],
)
def test_candidate_builder_rejects_duplicate_set_values(
    field: str,
    values: tuple[str, ...],
) -> None:
    with pytest.raises(AuthorizationLifecycleError, match="distinct values"):
        _record(**{field: values})


@pytest.mark.parametrize(
    "evidence_digests",
    [
        (EVIDENCE_2, EVIDENCE_1),
        (EVIDENCE_1, EVIDENCE_1),
    ],
)
def test_review_record_rejects_noncanonical_evidence(
    evidence_digests: tuple[str, ...],
) -> None:
    record = _record()

    with pytest.raises(AuthorizationLifecycleError, match="evidence_digests MUST"):
        _build_review(
            candidate_id=record.candidate_id,
            reviewer_principal=REVIEWER_A,
            decision=ReviewDecision.APPROVE,
            reviewed_at=NOW + timedelta(minutes=1),
            authentication_evidence_digest=AUTH_DIGEST,
            evidence_digests=evidence_digests,
        )


def test_candidate_id_differs_by_fence_generation() -> None:
    fence2 = LifecycleFence(
        family_id="family:one",
        revision_id=REVISION_ID,
        fencing_generation=99,
        transition_digest="sha256:" + "9" * 64,
    )
    assert _record(fence=fence2).candidate_id != _record().candidate_id


def test_wrong_lease_contract_version_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="lease_contract_version"):
        rec = _record()
        # Bypass builder: construct with wrong version
        PromotionCandidateRecord(
            candidate_id=rec.candidate_id,
            family_id=rec.family_id,
            revision_id=rec.revision_id,
            fence=rec.fence,
            lease_contract_version="wrong-version",
            eligible_action_types=rec.eligible_action_types,
            ineligible_provider_action_types=rec.ineligible_provider_action_types,
            evidence_requirements=rec.evidence_requirements,
            source_revision_id=rec.source_revision_id,
            creator_principal=rec.creator_principal,
            authentication_evidence_digest=rec.authentication_evidence_digest,
            created_at=rec.created_at,
            required_reviewer_principals=rec.required_reviewer_principals,
            quorum_required=rec.quorum_required,
        )


def test_agent_creator_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _record(creator_principal="agent:my-agent")


def test_executor_creator_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _record(creator_principal="identity:thor")


def test_insufficient_quorum_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="quorum_required"):
        _record(quorum_required=1)


def test_insufficient_reviewers_for_quorum_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="insufficient distinct reviewers"):
        _record(required_reviewer_principals=(REVIEWER_A,), quorum_required=2)


def test_empty_eligible_action_types_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="eligible_action_types"):
        _record(eligible_action_types=())


def test_empty_evidence_requirements_rejected() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="evidence_requirements"):
        _record(evidence_requirements=())


def test_fence_family_id_mismatch_rejected() -> None:
    bad_fence = LifecycleFence(
        family_id="family:wrong",
        revision_id=REVISION_ID,
        fencing_generation=3,
        transition_digest="sha256:" + "d" * 64,
    )
    with pytest.raises(AuthorizationLifecycleError, match="fence MUST match"):
        _record(fence=bad_fence)


# ---------------------------------------------------------------------------
# Tests: plan_create_transition
# ---------------------------------------------------------------------------


def test_create_transition_produces_pending_status() -> None:
    rec = _record()
    result = _create(rec)
    assert result.snapshot.status is CandidateStatus.PENDING
    assert result.transition.kind is CandidateTransitionKind.CREATE
    assert result.transition.sequence == 1
    assert result.transition.previous_transition_digest is None
    assert result.denial is None
    assert result.snapshot.execution_authority is False
    assert result.snapshot.promotion_authority is False


def test_create_with_ineligible_provider_denies_immediately() -> None:
    rec = _record(ineligible_provider_action_types=("ops.scale-out",))
    result = _create(rec)
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.PROVIDER_INELIGIBLE
    assert result.denial.execution_authority is False
    assert result.denial.promotion_authority is False


def test_create_intent_digest_is_bound_in_transition() -> None:
    rec = _record()
    result = _create(rec)
    # intent_digest must be a valid sha256
    assert result.transition.intent_digest.startswith("sha256:")
    # terminal_audit_digest (two-phase) appears in denial only
    assert result.denial is None


def test_create_ineligible_two_phase_audit() -> None:
    rec = _record(ineligible_provider_action_types=("ops.scale-out",))
    result = _create(rec)
    denial = result.denial
    assert denial is not None
    # intent_digest and terminal_audit_digest are distinct sha256 values
    assert denial.intent_digest.startswith("sha256:")
    assert denial.terminal_audit_digest.startswith("sha256:")
    # terminal_audit_digest covers intent_digest (two-phase audit)
    assert denial.intent_digest != denial.terminal_audit_digest


# ---------------------------------------------------------------------------
# Tests: reviewer validation
# ---------------------------------------------------------------------------


def test_self_review_denied() -> None:
    rec = _record()
    initial = _create(rec)
    review = _review(rec, reviewer=CREATOR)
    result = _apply_review(initial, rec, review)
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.SELF_REVIEW


def test_agent_reviewer_rejected_at_record_creation() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _build_review(
            candidate_id="sha256:" + "c" * 64,
            reviewer_principal="agent:bot",
            decision=ReviewDecision.APPROVE,
            reviewed_at=NOW,
            authentication_evidence_digest=AUTH_DIGEST,
            evidence_digests=EVIDENCE_ALL,
        )


def test_executor_reviewer_rejected_at_record_creation() -> None:
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        _build_review(
            candidate_id="sha256:" + "c" * 64,
            reviewer_principal="identity:thor",
            decision=ReviewDecision.APPROVE,
            reviewed_at=NOW,
            authentication_evidence_digest=AUTH_DIGEST,
            evidence_digests=EVIDENCE_ALL,
        )


def test_human_outside_required_reviewer_set_is_denied() -> None:
    rec = _record()
    initial = _create(rec)

    result = _apply_review(
        initial,
        rec,
        _review(rec, reviewer="human:unassigned-reviewer"),
    )

    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.UNAUTHORIZED_REVIEWER


def test_duplicate_review_denied() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A, at=NOW + timedelta(minutes=1))
    r2 = _apply_review(r1, rec, review_a)
    assert r2.snapshot.status is CandidateStatus.PENDING
    # Same reviewer approves again
    review_a2 = _review(rec, reviewer=REVIEWER_A, at=NOW + timedelta(minutes=2))
    r3 = _apply_review(r2, rec, review_a2)
    assert r3.denial is not None
    assert r3.denial.denial_reason is DenialReason.DUPLICATE_REVIEW


def test_conflicting_review_approve_then_reject() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A, decision=ReviewDecision.APPROVE)
    r2 = _apply_review(r1, rec, review_a)
    review_a_reject = _review(
        rec, reviewer=REVIEWER_A, decision=ReviewDecision.REJECT, at=NOW + timedelta(minutes=2)
    )
    r3 = _apply_review(r2, rec, review_a_reject)
    assert r3.denial is not None
    assert r3.denial.denial_reason is DenialReason.CONFLICTING_REVIEW


def test_rejection_terminates_candidate() -> None:
    rec = _record()
    r1 = _create(rec)
    review = _review(rec, reviewer=REVIEWER_A, decision=ReviewDecision.REJECT)
    result = _apply_review(r1, rec, review)
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.REJECTION


# ---------------------------------------------------------------------------
# Tests: evidence requirements
# ---------------------------------------------------------------------------


def test_missing_evidence_denied() -> None:
    rec = _record()
    r1 = _create(rec)
    review = _review(rec, reviewer=REVIEWER_A, evidence=(EVIDENCE_1,))  # missing EVIDENCE_2
    result = _apply_review(r1, rec, review)
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.MISSING_EVIDENCE


def test_all_evidence_provided_passes() -> None:
    rec = _record()
    r1 = _create(rec)
    review = _review(rec, reviewer=REVIEWER_A, evidence=EVIDENCE_ALL)
    result = _apply_review(r1, rec, review)
    assert result.snapshot.status is CandidateStatus.PENDING
    assert result.denial is None


# ---------------------------------------------------------------------------
# Tests: quorum and APPROVED path
# ---------------------------------------------------------------------------


def test_quorum_approval_produces_approved_status() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    assert r2.snapshot.status is CandidateStatus.PENDING
    review_b = _review(rec, reviewer=REVIEWER_B, at=NOW + timedelta(minutes=2))
    r3 = _apply_review(r2, rec, review_b)
    assert r3.snapshot.status is CandidateStatus.APPROVED
    assert r3.denial is None
    assert len(r3.snapshot.approvals) == 2


def test_approved_status_carries_no_execution_authority() -> None:
    rec = _record()
    r1 = _create(rec)
    r2 = _apply_review(r1, rec, _review(rec, reviewer=REVIEWER_A))
    r3 = _apply_review(r2, rec, _review(rec, reviewer=REVIEWER_B, at=NOW + timedelta(minutes=2)))
    assert r3.snapshot.status is CandidateStatus.APPROVED
    assert r3.snapshot.execution_authority is False
    assert r3.snapshot.promotion_authority is False


def test_cannot_review_approved_candidate() -> None:
    rec = _record(
        required_reviewer_principals=(REVIEWER_A, REVIEWER_B, REVIEWER_C),
        quorum_required=2,
    )
    r1 = _create(rec)
    r2 = _apply_review(r1, rec, _review(rec, reviewer=REVIEWER_A))
    r3 = _apply_review(r2, rec, _review(rec, reviewer=REVIEWER_B, at=NOW + timedelta(minutes=2)))
    assert r3.snapshot.status is CandidateStatus.APPROVED
    review_c = _review(rec, reviewer=REVIEWER_C, at=NOW + timedelta(minutes=3))
    with pytest.raises(AuthorizationLifecycleError, match="PENDING"):
        plan_review_transition(record=rec, snapshot=r3.snapshot, review=review_c)
