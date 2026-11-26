"""Tests for X01 exact-artifact capability-bundle lifecycle lineage (#2315)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.skills import (
    InMemorySkillBundleProposalStore,
    SkillBundleProposal,
    SkillBundleWorkshop,
)
from fdai.delivery.capability_bundle_lifecycle_lineage import (
    BUNDLE_ENABLE_ACTION_TYPE_ID,
    PINNED_MAIN_2940_CI_RECEIPT,
    PINNED_MAIN_2940_CI_SIGNATURE_HEX,
    GovernedSkillBundleLifecycleCoordinator,
    ReviewedBundleEnableAction,
    RevokedCapabilityBundleError,
    TypedBundleEnableActionDispatcher,
    VerifiedSourceCiReceipt,
    build_pinned_fdai_bundle_artifact,
)
from fdai.runtime.skill_source_runtime import (
    InMemorySkillRevocationStore,
    InMemoryTrustedSkillArtifactStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from scripts.deployment.local.rehearse_x01_bundle_lifecycle_lineage import (
    _require_loopback_dsn,
    rehearse_x01_bundle_lifecycle_lineage,
    rehearse_x01_postgres,
)

NOW = datetime(2026, 11, 5, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_x01_bundle_lifecycle_lineage_rehearsal_satisfies_all_seven_criteria() -> None:
    result = await rehearse_x01_bundle_lifecycle_lineage()

    assert all(result["criteria_satisfied"].values())
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["lineage_digest"].startswith("sha256:")
    assert set(result["receipts"]) == {
        "install",
        "enable",
        "disable",
        "revoke",
        "enable_refused_revoked",
        "restart_reconstruct",
    }


def test_reviewed_bundle_enable_action_rejects_self_approval_and_authority_escalation() -> None:
    with pytest.raises(ValueError, match="distinct reviewer"):
        ReviewedBundleEnableAction(
            action_type_id=BUNDLE_ENABLE_ACTION_TYPE_ID,
            requester_actor="same-actor@example.com",
            reviewer_actor="same-actor@example.com",
            review_decision_digest="sha256:" + "a" * 64,
            idempotency_key="key-1",
            reason="Self-review attempt.",
        )

    with pytest.raises(ValueError, match="cannot grant execution or promotion authority"):
        ReviewedBundleEnableAction(
            action_type_id=BUNDLE_ENABLE_ACTION_TYPE_ID,
            requester_actor="requester@example.com",
            reviewer_actor="reviewer@example.com",
            review_decision_digest="sha256:" + "a" * 64,
            idempotency_key="key-2",
            reason="Authority escalation attempt.",
            execution_authority=True,
        )

    with pytest.raises(ValueError, match="MUST use 'tool.run-investigation'"):
        ReviewedBundleEnableAction(
            action_type_id="remediate.tag-add",
            requester_actor="requester@example.com",
            reviewer_actor="reviewer@example.com",
            review_decision_digest="sha256:" + "a" * 64,
            idempotency_key="key-3",
            reason="Wrong registered action type.",
        )

    with pytest.raises(ValueError, match="check_conclusion == 'success'"):
        VerifiedSourceCiReceipt(
            source_revision="b5b201f4d2bf0174ca65d926d5bad251188c261a",
            workflow_run_id="gh-actions-main-2940-b5b201f4d2",
            check_conclusion="failure",
            verified_at="2026-11-04T09:10:20+00:00",
            signature=bytes.fromhex(PINNED_MAIN_2940_CI_SIGNATURE_HEX),
        )
    with pytest.raises(ValueError, match="failed verification against pinned CI issuer key"):
        VerifiedSourceCiReceipt(
            source_revision="b5b201f4d2bf0174ca65d926d5bad251188c261a",
            workflow_run_id="gh-actions-main-2940-b5b201f4d2",
            check_conclusion="success",
            verified_at="2026-11-04T09:10:20+00:00",
            signature=b"\x00" * 64,
        )

    with pytest.raises(ValueError, match="port-5433"):
        _require_loopback_dsn("postgresql://localhost/fdai")
    with pytest.raises(ValueError, match="port-5433"):
        _require_loopback_dsn("postgresql://127.0.0.1:5432/fdai")
    assert (
        _require_loopback_dsn("postgresql+psycopg://127.0.0.1:5433/fdai")
        == "postgresql://127.0.0.1:5433/fdai"
    )


class _Audit:
    async def append(self, _event: object) -> None:
        return None


class _Authorizer:
    def can_review(self, reviewer_id: str) -> bool:
        return reviewer_id == "reviewer@example.com"


@pytest.mark.asyncio
async def test_revocation_blocks_reactivation_and_preserves_saga_audit_chain() -> None:
    spec = build_pinned_fdai_bundle_artifact(
        ci_receipt=PINNED_MAIN_2940_CI_RECEIPT,
    )
    artifact_store = InMemoryTrustedSkillArtifactStore()
    revocation_store = InMemorySkillRevocationStore()
    state_store = InMemoryStateStore()
    dispatcher = TypedBundleEnableActionDispatcher()
    coordinator = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=artifact_store,
        revocation_store=revocation_store,
        state_store=state_store,
        clock=lambda: NOW,
    )

    install_receipt = await coordinator.install_bundle(
        actor="installer@example.com",
        idempotency_key="install-1",
        reason="Initial install.",
        now=NOW,
    )
    # Identical idempotent replay returns same receipt without extra audit entries.
    assert (
        await coordinator.install_bundle(
            actor="installer@example.com",
            idempotency_key="install-1",
            reason="Initial install.",
            now=NOW,
        )
        == install_receipt
    )
    # Conflicting idempotency key payload is rejected before mutation.
    with pytest.raises(ValueError, match="conflicts with a different request"):
        await coordinator.install_bundle(
            actor="different-actor@example.com",
            idempotency_key="install-1",
            reason="Conflicting install.",
            now=NOW,
        )

    workshop = SkillBundleWorkshop(
        store=InMemorySkillBundleProposalStore(),
        audit=_Audit(),
        authorizer=_Authorizer(),
    )
    draft: SkillBundleProposal = await workshop.propose(
        spec.bundle_raw_manifest,
        proposed_by_agent="requester@example.com",
        at=NOW,
    )
    approved = await workshop.review(
        draft.proposal_id,
        reviewer_id="reviewer@example.com",
        approve=True,
        reason="Approved.",
        at=NOW,
    )

    action = ReviewedBundleEnableAction(
        action_type_id=BUNDLE_ENABLE_ACTION_TYPE_ID,
        requester_actor="requester@example.com",
        reviewer_actor="reviewer@example.com",
        review_decision_digest="sha256:" + "b" * 64,
        idempotency_key="enable-after-revoke",
        reason="Should fail closed.",
    )
    # Direct bypass without TypedBundleEnableActionDispatcher is rejected.
    with pytest.raises(PermissionError, match="TypedBundleEnableActionDispatcher"):
        await coordinator.enable_bundle(action, now=NOW)

    await coordinator.revoke_bundle(
        actor="security@example.com",
        idempotency_key="revoke-1",
        reason="Emergency revocation.",
        now=NOW,
    )

    with pytest.raises(RevokedCapabilityBundleError, match="cannot be enabled"):
        await dispatcher.dispatch(
            coordinator,
            action,
            approved_proposal=approved,
            now=NOW,
        )
    # Replaying the same refused enable idempotency key raises without adding another audit row.
    with pytest.raises(RevokedCapabilityBundleError, match="cannot be enabled"):
        await dispatcher.dispatch(
            coordinator,
            action,
            approved_proposal=approved,
            now=NOW,
        )

    assert await state_store.verify_chain() is True
    audit_entries = tuple(state_store.audit_entries)
    assert len(audit_entries) == 3
    assert [item["entry"]["kind"] for item in audit_entries] == [
        "capability-bundle.install",
        "capability-bundle.revoke",
        "capability-bundle.enable_refused_revoked",
    ]


@pytest.mark.asyncio
async def test_live_reservation_blocks_second_coordinator_and_stale_lease_recovers() -> None:
    spec = build_pinned_fdai_bundle_artifact(ci_receipt=PINNED_MAIN_2940_CI_RECEIPT)
    artifact_store = InMemoryTrustedSkillArtifactStore()
    revocation_store = InMemorySkillRevocationStore()
    state_store = InMemoryStateStore()
    clock_now = [NOW]
    coord_a = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=artifact_store,
        revocation_store=revocation_store,
        state_store=state_store,
        clock=lambda: clock_now[0],
        owner_id="coord-a",
        reservation_lease_seconds=60,
    )
    coord_b = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=artifact_store,
        revocation_store=revocation_store,
        state_store=state_store,
        clock=lambda: clock_now[0],
        owner_id="coord-b",
        reservation_lease_seconds=60,
    )

    request_digest = "sha256:8cb82c693bfdd2dc4f7db98643eb9e95a3cb3b51cb76da4787be36222c4e32f0"
    # Simulate coord-a acquiring a live reservation and crashing before completion.
    replayed_a, rev_a = await coord_a._reserve_or_replay_idempotency(
        transition="install",
        idempotency_key="install-live-lease",
        request_digest=request_digest,
    )
    assert replayed_a is None
    assert rev_a == 1

    # While lease is active (NOW + 30s < NOW + 60s), coord-b is blocked from executing.
    clock_now[0] = NOW + timedelta(seconds=30)
    with pytest.raises(RuntimeError, match="currently in-progress under active lease"):
        await coord_b._reserve_or_replay_idempotency(
            transition="install",
            idempotency_key="install-live-lease",
            request_digest=request_digest,
        )


@pytest.mark.asyncio
async def test_post_mutation_pre_finalization_crash_reconciles_without_duplication() -> None:
    spec = build_pinned_fdai_bundle_artifact(ci_receipt=PINNED_MAIN_2940_CI_RECEIPT)
    artifact_store = InMemoryTrustedSkillArtifactStore()
    revocation_store = InMemorySkillRevocationStore()
    state_store = InMemoryStateStore()
    clock_now = [NOW]
    coord_a = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=artifact_store,
        revocation_store=revocation_store,
        state_store=state_store,
        clock=lambda: clock_now[0],
        owner_id="coord-a",
        reservation_lease_seconds=60,
    )
    coord_b = GovernedSkillBundleLifecycleCoordinator(
        spec=spec,
        artifact_store=artifact_store,
        revocation_store=revocation_store,
        state_store=state_store,
        clock=lambda: clock_now[0],
        owner_id="coord-b",
        reservation_lease_seconds=60,
    )

    receipt_a = await coord_a.install_bundle(
        actor="installer@example.com",
        idempotency_key="install-crash-1",
        reason="Initial install before simulated crash.",
        now=NOW,
    )
    audit_count_after_a = len(tuple(state_store.audit_entries))

    # Simulate a crash right before _record_idempotency finalized the reservation:
    # revert the idempotency record back to revision 1 "reserved" while durable artifact
    # and transition-receipt rows are already committed.
    idem_key = f"capability-bundle-lifecycle:v1:{spec.artifact_id}:idempotency:install-crash-1"
    current_idem = await state_store.read_state(idem_key)
    assert current_idem is not None
    await state_store.write_state(
        idem_key,
        {
            "idempotency_key": "install-crash-1",
            "lease_expires_at": (NOW + timedelta(seconds=60)).isoformat(),
            "owner_id": "coord-a",
            "receipt": None,
            "request_digest": current_idem["request_digest"],
            "revision": 1,
            "status": "reserved",
            "transition": "install",
        },
    )

    # Before lease expiry, coord_b refuses concurrent execution even if caller passes a future now.
    clock_now[0] = NOW + timedelta(seconds=10)
    with pytest.raises(RuntimeError, match="currently in-progress under active lease"):
        await coord_b.install_bundle(
            actor="installer@example.com",
            idempotency_key="install-crash-1",
            reason="Initial install before simulated crash.",
            now=NOW + timedelta(hours=2),
        )

    # After trusted clock advances past lease expiry, coord_b atomically takes over via CAS,
    # reconciles durable state without repeating mutations or duplicating audit rows, and finalizes.
    clock_now[0] = NOW + timedelta(seconds=120)
    recovered_receipt = await coord_b.install_bundle(
        actor="installer@example.com",
        idempotency_key="install-crash-1",
        reason="Initial install before simulated crash.",
        now=NOW,
    )
    assert recovered_receipt == receipt_a
    assert len(tuple(state_store.audit_entries)) == audit_count_after_a
    final_idem = await state_store.read_state(idem_key)
    assert final_idem is not None
    assert final_idem["status"] == "completed"
    assert final_idem["owner_id"] == "coord-b"
    assert final_idem["revision"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_x01_bundle_lifecycle_lineage_postgres_parity() -> None:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("FDAI_DATABASE_URL is unset")
    in_memory = await rehearse_x01_bundle_lifecycle_lineage()
    postgres = await rehearse_x01_postgres(dsn)
    assert postgres["receipts"] == in_memory["receipts"]
    assert postgres["readbacks"] == in_memory["readbacks"]
