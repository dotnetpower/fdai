"""Transition planning, replay, and builder for the A3-E promotion-candidate lifecycle.

Contains the pure-function operations: ``build_candidate_record``,
``plan_create_transition``, ``plan_review_transition``, ``plan_external_denial``,
``replay_candidate``, and the internal helpers ``_transition``, ``_snapshot``,
``_deny``. All operations are fail-closed and carry no execution authority.
"""

from __future__ import annotations

from datetime import datetime

from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
)
from fdai.core.standing_authority.promotion_candidate_models import (
    LEASE_CONTRACT_VERSION,
    CandidateReviewRecord,
    CandidateSnapshot,
    CandidateStatus,
    CandidateTransition,
    CandidateTransitionKind,
    DenialReason,
    PromotionCandidateRecord,
    PromotionCandidateWriteResult,
    ReviewDecision,
    TerminalDenialRecord,
    _require_human,
)


def _canonical_values(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise AuthorizationLifecycleError(f"{name} MUST contain distinct values")
    return tuple(sorted(values))


def build_candidate_record(
    *,
    family_id: str,
    revision_id: str,
    fence: LifecycleFence,
    eligible_action_types: tuple[str, ...],
    ineligible_provider_action_types: tuple[str, ...],
    evidence_requirements: tuple[str, ...],
    source_revision_id: str,
    creator_principal: str,
    authentication_evidence_digest: str,
    created_at: datetime,
    required_reviewer_principals: tuple[str, ...],
    quorum_required: int,
) -> PromotionCandidateRecord:
    """Build a creation record, deriving ``candidate_id``."""
    eligible_action_types = _canonical_values(
        "eligible_action_types",
        eligible_action_types,
    )
    ineligible_provider_action_types = _canonical_values(
        "ineligible_provider_action_types",
        ineligible_provider_action_types,
    )
    evidence_requirements = _canonical_values(
        "evidence_requirements",
        evidence_requirements,
    )
    required_reviewer_principals = _canonical_values(
        "required_reviewer_principals",
        required_reviewer_principals,
    )
    cid = content_digest(
        {
            "family_id": family_id,
            "revision_id": revision_id,
            "fence_generation": fence.fencing_generation,
            "fence_transition": fence.transition_digest,
            "lease_contract_version": LEASE_CONTRACT_VERSION,
            "eligible_action_types": eligible_action_types,
            "ineligible_provider_action_types": ineligible_provider_action_types,
            "evidence_requirements": evidence_requirements,
            "source_revision_id": source_revision_id,
            "creator_principal": creator_principal,
            "authentication_evidence_digest": authentication_evidence_digest,
            "created_at": instant(aware_utc(created_at)),
            "quorum_required": quorum_required,
            "required_reviewer_principals": required_reviewer_principals,
        }
    )
    return PromotionCandidateRecord(
        candidate_id=cid,
        family_id=family_id,
        revision_id=revision_id,
        fence=fence,
        lease_contract_version=LEASE_CONTRACT_VERSION,
        eligible_action_types=eligible_action_types,
        ineligible_provider_action_types=ineligible_provider_action_types,
        evidence_requirements=evidence_requirements,
        source_revision_id=source_revision_id,
        creator_principal=creator_principal,
        authentication_evidence_digest=authentication_evidence_digest,
        created_at=created_at,
        required_reviewer_principals=required_reviewer_principals,
        quorum_required=quorum_required,
    )


def plan_create_transition(record: PromotionCandidateRecord) -> PromotionCandidateWriteResult:
    """Compute CREATE transition. Deny immediately for provider-ineligible ActionTypes."""
    src: dict[str, object] = {
        "kind": "create",
        "candidate_id": record.candidate_id,
        "creator_principal": record.creator_principal,
        "created_at": instant(aware_utc(record.created_at)),
    }
    if record.ineligible_provider_action_types:
        return _deny(
            record.candidate_id,
            1,
            record.creator_principal,
            record.authentication_evidence_digest,
            record.created_at,
            None,
            DenialReason.PROVIDER_INELIGIBLE,
            f"ineligible ActionTypes: {sorted(record.ineligible_provider_action_types)}",
            record.revision_id,
            record.fence.fencing_generation,
            (),
            (),
            record.quorum_required,
            src,
        )
    intent = content_digest(src)
    t = _transition(
        record.candidate_id,
        1,
        CandidateTransitionKind.CREATE,
        record.creator_principal,
        record.authentication_evidence_digest,
        record.created_at,
        intent,
        None,
    )
    snap = _snapshot(
        record.candidate_id,
        CandidateStatus.PENDING,
        record.revision_id,
        record.fence.fencing_generation,
        1,
        t.transition_digest,
        (),
        (),
        record.quorum_required,
    )
    return PromotionCandidateWriteResult(transition=t, snapshot=snap)


def plan_review_transition(
    *,
    record: PromotionCandidateRecord,
    snapshot: CandidateSnapshot,
    review: CandidateReviewRecord,
) -> PromotionCandidateWriteResult:
    """Validate and apply a review. Fail-closed on any violation."""
    if snapshot.status is not CandidateStatus.PENDING:
        raise AuthorizationLifecycleError("review requires PENDING status")
    seq, prev = snapshot.sequence + 1, snapshot.head_transition_digest
    actor = review.reviewer_principal
    src: dict[str, object] = {
        "kind": "review",
        "candidate_id": record.candidate_id,
        "reviewer_principal": actor,
        "decision": review.decision.value,
        "reviewed_at": instant(aware_utc(review.reviewed_at)),
    }

    def _d(reason: DenialReason, detail: str) -> PromotionCandidateWriteResult:
        return _deny(
            record.candidate_id,
            seq,
            actor,
            review.authentication_evidence_digest,
            review.reviewed_at,
            prev,
            reason,
            detail,
            snapshot.revision_id,
            snapshot.fencing_generation,
            snapshot.approvals,
            snapshot.rejections,
            snapshot.quorum_required,
            src,
        )

    if actor == record.creator_principal:
        return _d(DenialReason.SELF_REVIEW, "creator cannot review own candidate")
    if actor not in record.required_reviewer_principals:
        return _d(
            DenialReason.UNAUTHORIZED_REVIEWER,
            "reviewer is outside the candidate reviewer set",
        )
    if actor in snapshot.approvals:
        return _d(
            DenialReason.CONFLICTING_REVIEW
            if review.decision is ReviewDecision.REJECT
            else DenialReason.DUPLICATE_REVIEW,
            "reviewer reversal or duplicate",
        )
    if actor in snapshot.rejections:
        return _d(
            DenialReason.CONFLICTING_REVIEW
            if review.decision is ReviewDecision.APPROVE
            else DenialReason.DUPLICATE_REVIEW,
            "reviewer reversal or duplicate",
        )
    missing = [er for er in record.evidence_requirements if er not in set(review.evidence_digests)]
    if missing:
        return _d(DenialReason.MISSING_EVIDENCE, f"missing evidence: {missing}")
    if review.decision is ReviewDecision.REJECT:
        return _d(DenialReason.REJECTION, f"{actor} rejected")
    new_approvals = snapshot.approvals + (actor,)
    new_status = (
        CandidateStatus.APPROVED
        if len(new_approvals) >= snapshot.quorum_required
        else CandidateStatus.PENDING
    )
    intent = content_digest(src)
    t = _transition(
        record.candidate_id,
        seq,
        CandidateTransitionKind.REVIEW,
        actor,
        review.authentication_evidence_digest,
        review.reviewed_at,
        intent,
        prev,
    )
    snap = _snapshot(
        record.candidate_id,
        new_status,
        snapshot.revision_id,
        snapshot.fencing_generation,
        seq,
        t.transition_digest,
        new_approvals,
        snapshot.rejections,
        snapshot.quorum_required,
    )
    return PromotionCandidateWriteResult(transition=t, snapshot=snap)


def plan_external_denial(
    *,
    record: PromotionCandidateRecord,
    snapshot: CandidateSnapshot,
    reason: DenialReason,
    detail: str,
    actor_ref: str,
    authentication_evidence_digest: str,
    occurred_at: datetime,
) -> PromotionCandidateWriteResult:
    """Record an external denial (revocation, stale fence, expiry, etc.)."""
    if snapshot.status is CandidateStatus.DENIED:
        raise AuthorizationLifecycleError("candidate is already terminally denied")
    _require_human("actor_ref", actor_ref)
    require_digest("authentication_evidence_digest", authentication_evidence_digest)
    require_aware("occurred_at", occurred_at)
    return _deny(
        record.candidate_id,
        snapshot.sequence + 1,
        actor_ref,
        authentication_evidence_digest,
        occurred_at,
        snapshot.head_transition_digest,
        reason,
        detail,
        snapshot.revision_id,
        snapshot.fencing_generation,
        snapshot.approvals,
        snapshot.rejections,
        snapshot.quorum_required,
        {
            "kind": "external_denial",
            "candidate_id": record.candidate_id,
            "denial_reason": reason.value,
            "actor_ref": actor_ref,
            "occurred_at": instant(aware_utc(occurred_at)),
        },
    )


def replay_candidate(
    *,
    record: PromotionCandidateRecord,
    transitions: tuple[CandidateTransition, ...],
) -> CandidateSnapshot:
    """Replay hash chain; raise on any gap, tamper, or invalid ordering."""
    if not transitions:
        raise AuthorizationLifecycleError("transition chain is empty")
    first = transitions[0]
    if first.kind is not CandidateTransitionKind.CREATE or first.sequence != 1:
        raise AuthorizationLifecycleError("chain MUST start with CREATE at sequence 1")
    if first.previous_transition_digest is not None or first.candidate_id != record.candidate_id:
        raise AuthorizationLifecycleError("first transition predecessor or candidate_id mismatch")
    snap: CandidateSnapshot | None = None
    for exp_seq, t in enumerate(transitions, start=1):
        if t.sequence != exp_seq or t.candidate_id != record.candidate_id:
            raise AuthorizationLifecycleError(f"sequence/id error: expected {exp_seq}")
        if t.transition_digest != content_digest(t._body()):
            raise AuthorizationLifecycleError("tamper detected: transition digest mismatch")
        if snap is not None:
            if snap.status is CandidateStatus.DENIED:
                raise AuthorizationLifecycleError("transition after terminal DENY not permitted")
            if t.previous_transition_digest != snap.head_transition_digest:
                raise AuthorizationLifecycleError("hash chain broken")
        if t.kind is CandidateTransitionKind.CREATE:
            snap = _snapshot(
                record.candidate_id,
                CandidateStatus.PENDING,
                record.revision_id,
                record.fence.fencing_generation,
                1,
                t.transition_digest,
                (),
                (),
                record.quorum_required,
            )
        elif t.kind is CandidateTransitionKind.REVIEW:
            if snap is None:
                raise AuthorizationLifecycleError("REVIEW before CREATE")
            new_approvals = snap.approvals + (t.actor_ref,)
            new_status = (
                CandidateStatus.APPROVED
                if len(new_approvals) >= snap.quorum_required
                else CandidateStatus.PENDING
            )
            snap = _snapshot(
                record.candidate_id,
                new_status,
                snap.revision_id,
                snap.fencing_generation,
                t.sequence,
                t.transition_digest,
                new_approvals,
                snap.rejections,
                snap.quorum_required,
            )
        elif t.kind is CandidateTransitionKind.DENY:
            if snap is None:
                raise AuthorizationLifecycleError("DENY before CREATE")
            snap = _snapshot(
                record.candidate_id,
                CandidateStatus.DENIED,
                snap.revision_id,
                snap.fencing_generation,
                t.sequence,
                t.transition_digest,
                snap.approvals,
                snap.rejections,
                snap.quorum_required,
            )
        else:
            raise AuthorizationLifecycleError(f"unknown transition kind: {t.kind}")
    if snap is None:
        raise AuthorizationLifecycleError("replay produced no snapshot")
    return snap


def _transition(
    candidate_id: str,
    sequence: int,
    kind: CandidateTransitionKind,
    actor_ref: str,
    auth_digest: str,
    occurred_at: datetime,
    intent: str,
    prev: str | None,
) -> CandidateTransition:
    body: dict[str, object] = {
        "candidate_id": candidate_id,
        "sequence": sequence,
        "kind": kind.value,
        "actor_ref": actor_ref,
        "authentication_evidence_digest": auth_digest,
        "occurred_at": instant(aware_utc(occurred_at)),
        "intent_digest": intent,
        "previous_transition_digest": prev,
    }
    return CandidateTransition(
        candidate_id=candidate_id,
        sequence=sequence,
        kind=kind,
        actor_ref=actor_ref,
        authentication_evidence_digest=auth_digest,
        occurred_at=aware_utc(occurred_at),
        intent_digest=intent,
        previous_transition_digest=prev,
        transition_digest=content_digest(body),
    )


def _snapshot(
    candidate_id: str,
    status: CandidateStatus,
    revision_id: str,
    fencing_gen: int,
    seq: int,
    head: str,
    approvals: tuple[str, ...],
    rejections: tuple[str, ...],
    quorum: int,
) -> CandidateSnapshot:
    body: dict[str, object] = {
        "candidate_id": candidate_id,
        "status": status.value,
        "revision_id": revision_id,
        "fencing_generation": fencing_gen,
        "sequence": seq,
        "head_transition_digest": head,
        "approvals": sorted(approvals),
        "rejections": sorted(rejections),
        "quorum_required": quorum,
    }
    return CandidateSnapshot(
        candidate_id=candidate_id,
        status=status,
        revision_id=revision_id,
        fencing_generation=fencing_gen,
        sequence=seq,
        head_transition_digest=head,
        approvals=tuple(sorted(approvals)),
        rejections=tuple(sorted(rejections)),
        quorum_required=quorum,
        snapshot_digest=content_digest(body),
    )


def _deny(
    candidate_id: str,
    sequence: int,
    actor_ref: str,
    auth_digest: str,
    occurred_at: datetime,
    prev_digest: str | None,
    reason: DenialReason,
    detail: str,
    revision_id: str,
    fencing_gen: int,
    approvals: tuple[str, ...],
    rejections: tuple[str, ...],
    quorum: int,
    intent_src: dict[str, object],
) -> PromotionCandidateWriteResult:
    intent = content_digest(intent_src)
    denial_id = content_digest(
        {"candidate_id": candidate_id, "sequence": sequence, "denial_reason": reason.value}
    )
    terminal_audit_digest = content_digest(
        {
            "intent_digest": intent,
            "denial_reason": reason.value,
            "candidate_id": candidate_id,
            "denial_id": denial_id,
            "denied_at": instant(aware_utc(occurred_at)),
            "detail": detail,
        }
    )
    denial = TerminalDenialRecord(
        denial_id=denial_id,
        candidate_id=candidate_id,
        denial_reason=reason,
        denied_at=aware_utc(occurred_at),
        detail=detail,
        intent_digest=intent,
        terminal_audit_digest=terminal_audit_digest,
    )
    t = _transition(
        candidate_id,
        sequence,
        CandidateTransitionKind.DENY,
        actor_ref,
        auth_digest,
        occurred_at,
        intent,
        prev_digest,
    )
    snap = _snapshot(
        candidate_id,
        CandidateStatus.DENIED,
        revision_id,
        fencing_gen,
        sequence,
        t.transition_digest,
        approvals,
        rejections,
        quorum,
    )
    return PromotionCandidateWriteResult(transition=t, snapshot=snap, denial=denial)


__all__ = [
    "build_candidate_record",
    "plan_create_transition",
    "plan_external_denial",
    "plan_review_transition",
    "replay_candidate",
]
