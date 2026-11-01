"""Focused tests for Hub opaque entitlement carrier Plan handoff and governed rotation."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from fdai_lifecycle_hub.entitlement_handoff import (
    EntitlementHandoffGovernanceError,
    GovernedEntitlementRotationReceipt,
    HubEntitlementHandoffStore,
    OpaqueEntitlementCarrierHandoff,
)

_NOW = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64
_DIGEST_C = "sha256:" + "c" * 64
_APPROVAL_DIGEST = "sha256:" + "d" * 64
_CIPHERTEXT_A = base64.b64encode(b"opaque-sealed-carrier-payload-a").decode("ascii")
_CIPHERTEXT_B = base64.b64encode(b"opaque-sealed-carrier-payload-b").decode("ascii")
_EPHEMERAL_KEY = base64.b64encode(b"e" * 32).decode("ascii")
_NONCE = base64.b64encode(b"n" * 12).decode("ascii")


def _make_handoff(
    *,
    handoff_id: str = "handoff-1",
    installation_id: str = "inst-alpha",
    deployment_id: str = "deploy-alpha",
    plan_id: str = "plan-1",
    carrier_digest: str = _DIGEST_A,
    ciphertext_b64: str = _CIPHERTEXT_A,
    sequence: int = 1,
    recorded_at: datetime = _NOW,
) -> OpaqueEntitlementCarrierHandoff:
    return OpaqueEntitlementCarrierHandoff(
        handoff_id=handoff_id,
        installation_id=installation_id,
        deployment_id=deployment_id,
        plan_id=plan_id,
        carrier_digest=carrier_digest,
        ciphertext_b64=ciphertext_b64,
        ephemeral_public_key_b64=_EPHEMERAL_KEY,
        nonce_b64=_NONCE,
        sequence=sequence,
        recorded_at=recorded_at,
    )


def test_opaque_plan_handoff_attachment_and_idempotent_replay() -> None:
    store = HubEntitlementHandoffStore()
    first = _make_handoff()
    staged = store.stage_plan_handoff(first)

    assert staged == first
    assert staged.hub_is_issuer is False
    assert staged.execution_authority == "none"
    assert store.get_handoff("inst-alpha") == first
    assert store.get_plan_handoff("plan-1") == first

    replay = store.stage_plan_handoff(
        _make_handoff(
            handoff_id="handoff-1-replay",
            plan_id="plan-2",
            carrier_digest=_DIGEST_A,
            sequence=2,
            recorded_at=_NOW + timedelta(minutes=5),
        )
    )
    assert replay == first
    assert store.get_plan_handoff("plan-2") == first
    assert len(store.audit_log) == 1
    assert store.audit_log[0]["event"] == "hub.entitlement_handoff.staged"


def test_silent_replacement_without_governed_rotation_receipt_is_rejected() -> None:
    store = HubEntitlementHandoffStore()
    store.stage_plan_handoff(_make_handoff())

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="automatic entitlement replacement is forbidden",
    ):
        store.stage_plan_handoff(
            _make_handoff(
                handoff_id="handoff-2",
                plan_id="plan-2",
                carrier_digest=_DIGEST_B,
                ciphertext_b64=_CIPHERTEXT_B,
                sequence=2,
            )
        )

    assert store.get_handoff("inst-alpha") is not None
    assert store.get_handoff("inst-alpha").carrier_digest == _DIGEST_A  # type: ignore[union-attr]


def test_governed_rotation_requires_distinct_actors_monotonic_sequence_and_prior_digest() -> None:
    store = HubEntitlementHandoffStore()
    store.stage_plan_handoff(_make_handoff(sequence=3))

    with pytest.raises(EntitlementHandoffGovernanceError, match="forbids self-approval"):
        GovernedEntitlementRotationReceipt(
            rotation_id="rot-self",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            prior_carrier_digest=_DIGEST_A,
            next_carrier_digest=_DIGEST_B,
            sequence=4,
            approver_id="operator-1",
            requester_id="operator-1",
            approval_digest=_APPROVAL_DIGEST,
            reason="annual key rotation",
            approved_at=_NOW + timedelta(minutes=1),
        )

    with pytest.raises(EntitlementHandoffGovernanceError, match="distinct prior and next"):
        GovernedEntitlementRotationReceipt(
            rotation_id="rot-same-digest",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            prior_carrier_digest=_DIGEST_A,
            next_carrier_digest=_DIGEST_A,
            sequence=4,
            approver_id="approver-2",
            requester_id="requester-1",
            approval_digest=_APPROVAL_DIGEST,
            reason="no-op digest",
            approved_at=_NOW + timedelta(minutes=1),
        )

    with pytest.raises(EntitlementHandoffGovernanceError, match="strictly exceed"):
        store.record_governed_rotation(
            rotation_id="rot-stale-seq",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            prior_carrier_digest=_DIGEST_A,
            next_carrier_digest=_DIGEST_B,
            sequence=3,
            approver_id="approver-2",
            requester_id="requester-1",
            approval_digest=_APPROVAL_DIGEST,
            reason="stale sequence",
            approved_at=_NOW + timedelta(minutes=1),
        )

    with pytest.raises(EntitlementHandoffGovernanceError, match="prior_carrier_digest"):
        store.record_governed_rotation(
            rotation_id="rot-wrong-prior",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            prior_carrier_digest=_DIGEST_C,
            next_carrier_digest=_DIGEST_B,
            sequence=4,
            approver_id="approver-2",
            requester_id="requester-1",
            approval_digest=_APPROVAL_DIGEST,
            reason="wrong prior digest",
            approved_at=_NOW + timedelta(minutes=1),
        )

    receipt = store.record_governed_rotation(
        rotation_id="rot-valid-4",
        installation_id="inst-alpha",
        deployment_id="deploy-alpha",
        prior_carrier_digest=_DIGEST_A,
        next_carrier_digest=_DIGEST_B,
        sequence=4,
        approver_id="approver-2",
        requester_id="requester-1",
        approval_digest=_APPROVAL_DIGEST,
        reason="governed entitlement renewal handoff",
        approved_at=_NOW + timedelta(minutes=2),
    )
    assert store.rotation_history("inst-alpha") == (receipt,)

    rotated = store.stage_plan_handoff(
        _make_handoff(
            handoff_id="handoff-2",
            plan_id="plan-2",
            carrier_digest=_DIGEST_B,
            ciphertext_b64=_CIPHERTEXT_B,
            sequence=4,
            recorded_at=_NOW + timedelta(minutes=3),
        )
    )
    assert rotated.carrier_digest == _DIGEST_B
    assert store.get_handoff("inst-alpha") == rotated
    assert store.get_plan_handoff("plan-2") == rotated

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="automatic entitlement replacement is forbidden",
    ):
        store.stage_plan_handoff(
            _make_handoff(
                handoff_id="handoff-3",
                plan_id="plan-3",
                carrier_digest=_DIGEST_C,
                ciphertext_b64=_CIPHERTEXT_B,
                sequence=5,
            )
        )


def test_clear_delete_and_issuer_authority_claims_are_rejected() -> None:
    store = HubEntitlementHandoffStore()
    store.stage_plan_handoff(_make_handoff())

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="Hub cannot clear or delete installation entitlement grants",
    ):
        store.delete_entitlement("inst-alpha")

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="Hub cannot clear or delete installation entitlement grants",
    ):
        store.clear_entitlement("inst-alpha")

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="MUST NOT claim entitlement issuer authority",
    ):
        OpaqueEntitlementCarrierHandoff(
            handoff_id="handoff-bad-issuer",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            plan_id="plan-bad",
            carrier_digest=_DIGEST_A,
            ciphertext_b64=_CIPHERTEXT_A,
            ephemeral_public_key_b64=_EPHEMERAL_KEY,
            nonce_b64=_NONCE,
            sequence=1,
            recorded_at=_NOW,
            hub_is_issuer=True,  # type: ignore[arg-type]
        )

    with pytest.raises(
        EntitlementHandoffGovernanceError,
        match="MUST NOT carry execution authority",
    ):
        OpaqueEntitlementCarrierHandoff(
            handoff_id="handoff-bad-exec",
            installation_id="inst-alpha",
            deployment_id="deploy-alpha",
            plan_id="plan-bad",
            carrier_digest=_DIGEST_A,
            ciphertext_b64=_CIPHERTEXT_A,
            ephemeral_public_key_b64=_EPHEMERAL_KEY,
            nonce_b64=_NONCE,
            sequence=1,
            recorded_at=_NOW,
            execution_authority="execute",  # type: ignore[arg-type]
        )
