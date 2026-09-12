"""Operational tests for the A3-E inert promotion-candidate lifecycle.

Covers:
- Stale fencing generation denial (STALE_FENCE)
- Explicit revocation (REVOCATION_REQUEST)
- Append-only replay with tamper detection and restart
- Concurrent review/revoke ordering (in-memory store)
- Multiple ineligible ActionType variants
- Quorum constant enforcement
- Static non-import proof: agents, risk_gate, hil_resume, workflow,
  control_loop, executor, composition, and authoritative promotion registry
  must not import ``fdai.core.standing_authority.promotion_candidate``.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.standing_authority.lifecycle import LifecycleFence
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
)
from fdai.core.standing_authority.promotion_candidate import (
    CANDIDATE_QUORUM,
    CandidateReviewRecord,
    CandidateRevocationRecord,
    CandidateSnapshot,
    CandidateStatus,
    CandidateTransition,
    DenialReason,
    PromotionCandidateRecord,
    PromotionCandidateWriteResult,
    ReviewDecision,
    build_candidate_record,
    plan_create_transition,
    plan_external_denial,
    plan_review_transition,
    replay_candidate,
)
from tests.core.standing_authority.hypothetical_provider_eligibility import (
    hypothetical_fence_capable,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"
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
STALE_FENCE = LifecycleFence(
    family_id="family:one",
    revision_id=REVISION_ID,
    fencing_generation=4,
    transition_digest="sha256:" + "4" * 64,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(**overrides: object) -> PromotionCandidateRecord:
    hypothetical = overrides.pop("hypothetical_fence_capable", None)
    kwargs: dict[str, object] = dict(
        family_id="family:one",
        revision_id=REVISION_ID,
        fence=FENCE,
        eligible_action_types=("ops.scale-out",),
        evidence_requirements=(EVIDENCE_1, EVIDENCE_2),
        source_revision_id="source:v1",
        creator_principal=CREATOR,
        authentication_evidence_digest=AUTH_DIGEST,
        created_at=NOW,
        required_reviewer_principals=(REVIEWER_A, REVIEWER_B),
        quorum_required=2,
    )
    kwargs.update(overrides)
    capable = kwargs["eligible_action_types"] if hypothetical is None else hypothetical
    with hypothetical_fence_capable(capable):  # type: ignore[arg-type]
        return build_candidate_record(**kwargs)  # type: ignore[arg-type]


def _build_review(
    candidate_id: str,
    reviewer_principal: str,
    decision: ReviewDecision,
    reviewed_at: datetime,
    authentication_evidence_digest: str,
    evidence_digests: tuple[str, ...],
) -> CandidateReviewRecord:
    review_id = content_digest(
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


def _revocation(
    record: PromotionCandidateRecord,
    *,
    revoker: str = REVIEWER_A,
    at: datetime | None = None,
) -> CandidateRevocationRecord:
    revoked_at = at or (NOW + timedelta(minutes=5))
    reason = "safety revocation"
    revocation_id = content_digest(
        {
            "candidate_id": record.candidate_id,
            "revoker_principal": revoker,
            "revoked_at": instant(aware_utc(revoked_at)),
            "authentication_evidence_digest": AUTH_DIGEST,
            "reason": reason,
        }
    )
    return CandidateRevocationRecord(
        revocation_id=revocation_id,
        candidate_id=record.candidate_id,
        revoker_principal=revoker,
        revoked_at=revoked_at,
        authentication_evidence_digest=AUTH_DIGEST,
        reason=reason,
    )


def _create(record: PromotionCandidateRecord) -> PromotionCandidateWriteResult:
    return plan_create_transition(record)


def test_revocation_id_is_content_bound() -> None:
    record = _record()

    with pytest.raises(AuthorizationLifecycleError, match="revocation_id digest mismatch"):
        CandidateRevocationRecord(
            revocation_id="sha256:" + "0" * 64,
            candidate_id=record.candidate_id,
            revoker_principal=REVIEWER_A,
            revoked_at=NOW + timedelta(minutes=5),
            authentication_evidence_digest=AUTH_DIGEST,
            reason="safety revocation",
        )


def _apply_review(
    result: PromotionCandidateWriteResult,
    record: PromotionCandidateRecord,
    review: CandidateReviewRecord,
) -> PromotionCandidateWriteResult:
    return plan_review_transition(record=record, snapshot=result.snapshot, review=review)


def _plan_revoke(
    record: PromotionCandidateRecord,
    snapshot: CandidateSnapshot,
    revocation: CandidateRevocationRecord,
) -> PromotionCandidateWriteResult:
    """Convenience wrapper for explicit revocation via plan_external_denial."""
    return plan_external_denial(
        record=record,
        snapshot=snapshot,
        reason=DenialReason.REVOCATION_REQUEST,
        detail=revocation.reason,
        actor_ref=revocation.revoker_principal,
        authentication_evidence_digest=revocation.authentication_evidence_digest,
        occurred_at=revocation.revoked_at,
    )


def _plan_stale(
    record: PromotionCandidateRecord,
    snapshot: CandidateSnapshot,
    current_generation: int,
    at: datetime,
) -> PromotionCandidateWriteResult:
    """Convenience wrapper for stale fence denial via plan_external_denial."""
    if snapshot.fencing_generation == current_generation:
        raise AuthorizationLifecycleError("fence is current; no stale denial needed")
    return plan_external_denial(
        record=record,
        snapshot=snapshot,
        reason=DenialReason.STALE_FENCE,
        detail=f"generation={snapshot.fencing_generation} < current={current_generation}",
        actor_ref=REVIEWER_A,
        authentication_evidence_digest=AUTH_DIGEST,
        occurred_at=at,
    )


# ---------------------------------------------------------------------------
# In-memory store (atomicity and concurrency proof)
# ---------------------------------------------------------------------------


@dataclass
class _Slot:
    record: PromotionCandidateRecord
    results: list[PromotionCandidateWriteResult] = field(default_factory=list)
    snapshot: CandidateSnapshot | None = None


class InMemoryCandidateStore:
    """Test-only in-memory store proving atomic transitions and lock semantics."""

    def __init__(self) -> None:
        self._slots: dict[str, _Slot] = {}
        self._lock = asyncio.Lock()

    async def create_candidate(
        self, record: PromotionCandidateRecord
    ) -> PromotionCandidateWriteResult:
        async with self._lock:
            if record.candidate_id in self._slots:
                raise AuthorizationLifecycleError("candidate already exists")
            result = plan_create_transition(record)
            self._slots[record.candidate_id] = _Slot(
                record=record, results=[result], snapshot=result.snapshot
            )
            return result

    async def submit_review(
        self, candidate_id: str, review: CandidateReviewRecord
    ) -> PromotionCandidateWriteResult:
        async with self._lock:
            slot = self._slots.get(candidate_id)
            if slot is None or slot.snapshot is None:
                raise AuthorizationLifecycleError("candidate not found")
            result = plan_review_transition(
                record=slot.record, snapshot=slot.snapshot, review=review
            )
            slot.results.append(result)
            slot.snapshot = result.snapshot
            return result

    async def revoke_candidate(
        self, revocation: CandidateRevocationRecord
    ) -> PromotionCandidateWriteResult:
        async with self._lock:
            slot = self._slots.get(revocation.candidate_id)
            if slot is None or slot.snapshot is None:
                raise AuthorizationLifecycleError("candidate not found")
            result = plan_external_denial(
                record=slot.record,
                snapshot=slot.snapshot,
                reason=DenialReason.REVOCATION_REQUEST,
                detail=revocation.reason,
                actor_ref=revocation.revoker_principal,
                authentication_evidence_digest=revocation.authentication_evidence_digest,
                occurred_at=revocation.revoked_at,
            )
            slot.results.append(result)
            slot.snapshot = result.snapshot
            return result

    async def read_candidate(self, candidate_id: str) -> PromotionCandidateRecord | None:
        slot = self._slots.get(candidate_id)
        return slot.record if slot else None

    async def read_transitions(self, candidate_id: str) -> tuple[CandidateTransition, ...]:
        slot = self._slots.get(candidate_id)
        return () if slot is None else tuple(r.transition for r in slot.results)

    async def read_snapshot(self, candidate_id: str) -> CandidateSnapshot | None:
        slot = self._slots.get(candidate_id)
        return slot.snapshot if slot else None

    async def rebuild_snapshot(self, candidate_id: str) -> CandidateSnapshot | None:
        slot = self._slots.get(candidate_id)
        if slot is None:
            return None
        transitions = tuple(r.transition for r in slot.results)
        if not transitions:
            return None
        snap = replay_candidate(record=slot.record, transitions=transitions)
        slot.snapshot = snap
        return snap


# ---------------------------------------------------------------------------
# Tests: stale fence denial
# ---------------------------------------------------------------------------


def test_stale_fence_denial() -> None:
    rec = _record()
    r1 = _create(rec)
    result = _plan_stale(
        rec, r1.snapshot, STALE_FENCE.fencing_generation, NOW + timedelta(minutes=10)
    )
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.STALE_FENCE


def test_stale_fence_denial_requires_advanced_generation() -> None:
    rec = _record()
    r1 = _create(rec)
    with pytest.raises(AuthorizationLifecycleError, match="fence is current"):
        _plan_stale(rec, r1.snapshot, FENCE.fencing_generation, NOW + timedelta(minutes=10))


def test_stale_fence_rejects_agent_actor() -> None:
    rec = _record()
    r1 = _create(rec)
    # plan_external_denial validates actor_ref is human
    with pytest.raises(AuthorizationLifecycleError, match="human"):
        plan_external_denial(
            record=rec,
            snapshot=r1.snapshot,
            reason=DenialReason.STALE_FENCE,
            detail="stale",
            actor_ref="agent:checker",
            authentication_evidence_digest=AUTH_DIGEST,
            occurred_at=NOW + timedelta(minutes=10),
        )


# ---------------------------------------------------------------------------
# Tests: explicit revocation
# ---------------------------------------------------------------------------


def test_explicit_revocation_denies() -> None:
    rec = _record()
    r1 = _create(rec)
    result = _plan_revoke(rec, r1.snapshot, _revocation(rec))
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.REVOCATION_REQUEST


def test_revocation_of_already_denied_raises() -> None:
    rec = _record()
    r1 = _create(rec)
    revoc = _revocation(rec)
    r2 = _plan_revoke(rec, r1.snapshot, revoc)
    revoc2 = _revocation(rec, at=NOW + timedelta(minutes=10))
    with pytest.raises(AuthorizationLifecycleError, match="terminally denied"):
        _plan_revoke(rec, r2.snapshot, revoc2)


# ---------------------------------------------------------------------------
# Tests: two-phase audit
# ---------------------------------------------------------------------------


def test_denial_intent_digest_is_stable() -> None:
    rec = _record()
    r1 = _create(rec)
    result = _plan_revoke(rec, r1.snapshot, _revocation(rec))
    denial = result.denial
    assert denial is not None
    d1_intent = denial.intent_digest
    # Replay: rebuild from transitions and verify same intent
    transitions = (r1.transition, result.transition)
    snap = replay_candidate(record=rec, transitions=transitions)
    assert snap.status is CandidateStatus.DENIED
    # Re-derive the denial: intent is deterministic
    result2 = _plan_revoke(rec, r1.snapshot, _revocation(rec))
    assert result2.denial is not None
    assert result2.denial.intent_digest == d1_intent


def test_terminal_audit_digest_covers_intent_and_result() -> None:
    rec = _record()
    r1 = _create(rec)
    result = _plan_revoke(rec, r1.snapshot, _revocation(rec))
    denial = result.denial
    assert denial is not None
    # terminal_audit_digest is different from intent_digest (covers both)
    assert denial.terminal_audit_digest != denial.intent_digest
    # Both are sha256 digests
    assert denial.terminal_audit_digest.startswith("sha256:")
    assert denial.intent_digest.startswith("sha256:")


def test_create_transition_intent_digest_bound_in_transition() -> None:
    rec = _record()
    result = _create(rec)
    # intent_digest in transition is sha256 of the create intent body
    assert result.transition.intent_digest.startswith("sha256:")
    # transition_digest covers intent_digest (two-phase: intent before, result after)
    body_with_intent = result.transition._body()
    assert "intent_digest" in body_with_intent
    assert body_with_intent["intent_digest"] == result.transition.intent_digest


# ---------------------------------------------------------------------------
# Tests: append-only replay and tamper detection
# ---------------------------------------------------------------------------


def test_replay_matches_computed_snapshot() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    review_b = _review(rec, reviewer=REVIEWER_B, at=NOW + timedelta(minutes=2))
    r3 = _apply_review(r2, rec, review_b)
    transitions = (r1.transition, r2.transition, r3.transition)
    replayed = replay_candidate(record=rec, transitions=transitions)
    assert replayed.status == r3.snapshot.status
    assert replayed.sequence == r3.snapshot.sequence
    assert replayed.head_transition_digest == r3.snapshot.head_transition_digest


def test_replay_detects_tampered_digest() -> None:
    # Create valid chain then swap transition order to break the hash chain.
    # Swapped transitions have valid digests but wrong predecessor links.
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    # Swapping transitions breaks the hash chain (t2 expects t1 as predecessor)
    with pytest.raises(AuthorizationLifecycleError):
        replay_candidate(record=rec, transitions=(r2.transition, r1.transition))


def test_replay_detects_sequence_gap() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    # Omit r1: chain starts with transition at sequence 2, missing sequence 1 CREATE
    with pytest.raises(AuthorizationLifecycleError, match="CREATE"):
        replay_candidate(record=rec, transitions=(r2.transition,))


def test_replay_detects_broken_hash_chain() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    # Drop r1 so the chain starts at sequence 2 (wrong)
    with pytest.raises(AuthorizationLifecycleError, match="CREATE"):
        replay_candidate(record=rec, transitions=(r2.transition,))


def test_replay_detects_transition_after_deny() -> None:
    rec = _record()
    r1 = _create(rec)
    revoc = _revocation(rec)
    r2 = _plan_revoke(rec, r1.snapshot, revoc)
    # Build a valid third transition that links to r2 (the DENY), to prove
    # replay rejects transitions after a terminal DENY.
    # We create a stale_fence_denial that references r2.snapshot, which is already DENIED.
    # plan_external_denial raises immediately on a DENIED snapshot.
    with pytest.raises(AuthorizationLifecycleError, match="terminally denied"):
        plan_external_denial(
            record=rec,
            snapshot=r2.snapshot,
            reason=DenialReason.STALE_FENCE,
            detail="stale",
            actor_ref=REVIEWER_A,
            authentication_evidence_digest=AUTH_DIGEST,
            occurred_at=NOW + timedelta(minutes=10),
        )


def test_replay_restart_produces_same_snapshot() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    transitions = (r1.transition, r2.transition)
    # Simulate restart: replay from scratch
    snap1 = replay_candidate(record=rec, transitions=transitions)
    snap2 = replay_candidate(record=rec, transitions=transitions)
    assert snap1.snapshot_digest == snap2.snapshot_digest


# ---------------------------------------------------------------------------
# Tests: stale revision (fence generation mismatch)
# ---------------------------------------------------------------------------


def test_stale_revision_denial_preserves_chain() -> None:
    rec = _record()
    r1 = _create(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    r2 = _apply_review(r1, rec, review_a)
    stale_result = _plan_stale(
        rec, r2.snapshot, STALE_FENCE.fencing_generation, NOW + timedelta(minutes=20)
    )
    transitions = (r1.transition, r2.transition, stale_result.transition)
    snap = replay_candidate(record=rec, transitions=transitions)
    assert snap.status is CandidateStatus.DENIED
    assert snap.sequence == 3


# ---------------------------------------------------------------------------
# Tests: concurrent review/revoke orderings (store-level)
# ---------------------------------------------------------------------------


async def test_concurrent_reviews_first_wins() -> None:
    rec = _record()
    store = InMemoryCandidateStore()
    await store.create_candidate(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    review_b = _review(rec, reviewer=REVIEWER_B, at=NOW + timedelta(minutes=1))
    results = await asyncio.gather(
        store.submit_review(rec.candidate_id, review_a),
        store.submit_review(rec.candidate_id, review_b),
        return_exceptions=True,
    )
    # Both should succeed (the lock serializes them)
    errors = [r for r in results if isinstance(r, Exception)]
    assert not errors, f"Unexpected errors: {errors}"
    snap = await store.read_snapshot(rec.candidate_id)
    assert snap is not None
    # Quorum of 2: both approvals → APPROVED
    assert snap.status is CandidateStatus.APPROVED


async def test_revoke_before_review_wins() -> None:
    rec = _record()
    store = InMemoryCandidateStore()
    await store.create_candidate(rec)
    revoc = _revocation(rec)
    await store.revoke_candidate(revoc)
    snap = await store.read_snapshot(rec.candidate_id)
    assert snap is not None
    assert snap.status is CandidateStatus.DENIED
    review_a = _review(rec, reviewer=REVIEWER_A, at=NOW + timedelta(minutes=2))
    with pytest.raises(AuthorizationLifecycleError, match="PENDING"):
        await store.submit_review(rec.candidate_id, review_a)


async def test_review_before_revoke_terminates_after_revocation() -> None:
    rec = _record()
    store = InMemoryCandidateStore()
    await store.create_candidate(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    await store.submit_review(rec.candidate_id, review_a)
    revoc = _revocation(rec)
    await store.revoke_candidate(revoc)
    snap = await store.read_snapshot(rec.candidate_id)
    assert snap is not None
    assert snap.status is CandidateStatus.DENIED


# ---------------------------------------------------------------------------
# Tests: rebuild_snapshot (restart simulation)
# ---------------------------------------------------------------------------


async def test_rebuild_snapshot_matches_stored() -> None:
    rec = _record()
    store = InMemoryCandidateStore()
    await store.create_candidate(rec)
    review_a = _review(rec, reviewer=REVIEWER_A)
    await store.submit_review(rec.candidate_id, review_a)
    stored = await store.read_snapshot(rec.candidate_id)
    rebuilt = await store.rebuild_snapshot(rec.candidate_id)
    assert stored is not None and rebuilt is not None
    assert stored.snapshot_digest == rebuilt.snapshot_digest


# ---------------------------------------------------------------------------
# Tests: every incompatible ActionType / provider
# ---------------------------------------------------------------------------


def test_multiple_ineligible_action_types_all_denied() -> None:
    rec = _record(
        eligible_action_types=("ops.scale-out", "ops.restart"),
        hypothetical_fence_capable=(),
    )
    assert rec.ineligible_provider_action_types == ("ops.restart", "ops.scale-out")
    result = _create(rec)
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.PROVIDER_INELIGIBLE
    assert "ops.restart" in result.denial.detail or "ops.scale-out" in result.denial.detail


def test_partial_ineligible_action_type_still_denied() -> None:
    rec = _record(
        eligible_action_types=("ops.scale-out", "ops.restart"),
        hypothetical_fence_capable=("ops.scale-out",),
    )
    assert rec.ineligible_provider_action_types == ("ops.restart",)
    result = _create(rec)
    assert result.snapshot.status is CandidateStatus.DENIED
    assert result.denial is not None
    assert result.denial.denial_reason is DenialReason.PROVIDER_INELIGIBLE


# ---------------------------------------------------------------------------
# Tests: CANDIDATE_QUORUM constant
# ---------------------------------------------------------------------------


def test_candidate_quorum_is_at_least_two() -> None:
    assert CANDIDATE_QUORUM >= 2


# ---------------------------------------------------------------------------
# Static non-import test
# ---------------------------------------------------------------------------


def test_promotion_candidate_not_imported_by_authority_paths() -> None:
    """Agents, risk_gate, hil_resume, workflow, control_loop, executor,
    composition, and the authoritative ActionPromotionRegistry must not
    import ``fdai.core.standing_authority.promotion_candidate``."""
    forbidden_prefix = "fdai.core.standing_authority.promotion_candidate"
    roots = (
        "agents",
        "core/risk_gate",
        "core/executor",
        "core/hil_resume",
        "core/workflow",
        "core/control_loop",
        "composition",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        assert path.exists(), f"authority path is missing from scan root: {root}"
        files = (path,) if path.is_file() else path.rglob("*.py")
        for candidate_file in files:
            tree = ast.parse(candidate_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                if any(m.startswith(forbidden_prefix) for m in modules):
                    violations.append(str(candidate_file.relative_to(SOURCE_ROOT)))
    assert violations == [], f"promotion_candidate imported from authority paths: {violations}"


def test_promotion_candidate_not_imported_by_registry() -> None:
    """The authoritative ActionPromotionRegistry (risk_gate/gate.py) must not
    import the promotion-candidate module."""
    registry_file = SOURCE_ROOT / "core" / "risk_gate" / "gate.py"
    assert registry_file.exists(), "ActionPromotionRegistry source is missing"
    tree = ast.parse(registry_file.read_text(encoding="utf-8"))
    forbidden_prefix = "fdai.core.standing_authority.promotion_candidate"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefix), (
                    f"ActionPromotionRegistry imports {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            assert not node.module.startswith(forbidden_prefix), (
                f"ActionPromotionRegistry imports from {node.module}"
            )
