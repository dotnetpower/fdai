"""Tests for InfrastructureAgent, DualSlotUpgradeController, and Foundation ownership exclusion (#2398)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai_deployment_cli.lifecycle_authorization import (
    exact_plan_digest_for,
    issue_lifecycle_authorization_receipt,
)
from fdai_deployment_cli.lifecycle_infrastructure_agent import (
    DestructiveChangeConfirmation,
    InfrastructureAgent,
    PlannedResourceChange,
)
from fdai_deployment_cli.lifecycle_ownership_exclusion import (
    ProvenFoundationOwnershipRegistry,
    SignedFoundationOwnershipReceipt,
)
from fdai_deployment_cli.lifecycle_plan import (
    LifecycleEffectEnvelope,
    LifecyclePlan,
    canonical_plan_payload,
)
from fdai_deployment_cli.lifecycle_self_upgrade import (
    DualSlotState,
    DualSlotUpgradeController,
    SelfUpgradeComponent,
)

NOW = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)


def _key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())


def _plan() -> LifecyclePlan:
    hub_key = _key("hub")
    unsigned = LifecyclePlan(
        plan_id="plan-infra-0001",
        audience="installation-alpha",
        hub_key_epoch=1,
        hub_key_id="hub-key-1",
        source_state_digest="a" * 64,
        sequence=1,
        fencing_generation=2,
        plan_type="upgrade",
        target_release_id="1.6.0",
        target_release_digest="b" * 64,
        configuration_revision_digest="c" * 64,
        entity_ids=frozenset({"platform"}),
        capability_ids=("action:scale-service",),
        release_regions=frozenset({"korea-central"}),
        rollback_target_plan_id=None,
        declared_duration_minutes=15,
        envelope=LifecycleEffectEnvelope(
            entity_ids=frozenset({"platform"}),
            regions=frozenset({"korea-central"}),
            capability_modes={"action:scale-service": "enforce"},
            destructive_allowed=False,
            max_duration_minutes=30,
        ),
        expires_at=NOW + timedelta(minutes=30),
        signed_payload=b"",
        signature=b"",
    )
    payload = canonical_plan_payload(unsigned)
    return replace(unsigned, signed_payload=payload, signature=hub_key.sign(payload))


@dataclass
class _FakeCoordinator:
    calls: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

    def claim_apply_and_verify(
        self,
        *,
        plan_id: str,
        exact_plan_digest: str,
        authorization_receipt_digest: str,
        changes: tuple[PlannedResourceChange, ...],
    ) -> bool:
        self.calls.append(
            (
                plan_id,
                exact_plan_digest,
                tuple(change.address for change in changes),
            )
        )
        return True


def test_infrastructure_agent_holds_deletion_or_replacement_and_applies_in_envelope_changes() -> (
    None
):
    plan = _plan()
    receipt = issue_lifecycle_authorization_receipt(
        plan,
        phase="infrastructure",
        window_starts_at=NOW - timedelta(minutes=5),
        window_ends_at=NOW + timedelta(minutes=30),
        issued_at=NOW,
    )
    coordinator = _FakeCoordinator()
    agent = InfrastructureAgent(coordinator)

    # 1. In-envelope create/update change applies through the exact-plan coordinator.
    in_envelope = (
        PlannedResourceChange(
            address="azurerm_kubernetes_cluster.fdai",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks",
            entity_id="platform",
            region="korea-central",
            actions=("update",),
        ),
    )
    applied = agent.execute_phase(
        plan,
        authorization_receipt=receipt,
        planned_changes=in_envelope,
        trusted_now=NOW,
    )
    assert applied.outcome == "applied"
    assert applied.completion_receipt is not None
    assert applied.completion_receipt.exact_plan_digest == exact_plan_digest_for(plan)
    assert coordinator.calls == [
        (plan.plan_id, exact_plan_digest_for(plan), ("azurerm_kubernetes_cluster.fdai",))
    ]

    # 2. Deletion or replacement of an existing Azure resource is held for confirmation without
    # invoking the coordinator.
    coordinator.calls.clear()
    destructive = (
        PlannedResourceChange(
            address="azurerm_postgresql_flexible_server.state",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg",
            entity_id="platform",
            region="korea-central",
            actions=("replace",),
        ),
        PlannedResourceChange(
            address="azurerm_storage_account.audit",
            resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/st",
            entity_id="platform",
            region="korea-central",
            actions=("delete",),
        ),
    )
    held = agent.execute_phase(
        plan,
        authorization_receipt=receipt,
        planned_changes=destructive,
        trusted_now=NOW,
    )
    assert held.outcome == "held-for-confirmation"
    assert held.reason_code == "destructive_change_confirmation_required"
    assert held.held_addresses == (
        "azurerm_postgresql_flexible_server.state",
        "azurerm_storage_account.audit",
    )
    assert coordinator.calls == []

    # 3. With an operator confirmation bound to the exact Plan digest and addresses, it proceeds.
    confirmation = DestructiveChangeConfirmation(
        exact_plan_digest=exact_plan_digest_for(plan),
        confirmed_addresses=frozenset(
            {
                "azurerm_postgresql_flexible_server.state",
                "azurerm_storage_account.audit",
            }
        ),
        operator="operator-alice",
        reason="Approved planned replacement and storage retirement",
        confirmed_at=NOW,
    )
    confirmed = agent.execute_phase(
        plan,
        authorization_receipt=receipt,
        planned_changes=destructive,
        trusted_now=NOW,
        confirmation=confirmation,
    )
    assert confirmed.outcome == "applied"
    assert len(coordinator.calls) == 1


@pytest.mark.parametrize(
    "component",
    ["lifecycle-agent", "infrastructure-agent", "target-hub"],
)
def test_dual_slot_self_upgrade_rolls_back_on_failed_health_and_cuts_over_when_healthy(
    component: SelfUpgradeComponent,
) -> None:
    v1_digest = "sha256:" + "1" * 64
    v2_digest = "sha256:" + "2" * 64
    initial = DualSlotState.initial(
        component=component,
        release_id="1.5.0",
        image_digest=v1_digest,
        active_slot="slot-a",
        fencing_generation=4,
    )
    controller = DualSlotUpgradeController()

    # 1. Failed health check on candidate slot-b rolls back to slot-a, keeping slot-a active
    # with sole write authority and stopping candidate slot-b.
    failed = controller.upgrade(
        initial,
        target_release_id="1.6.0",
        target_image_digest=v2_digest,
        check_candidate_health=lambda _comp, _slot, _rel, _img: False,
    )
    assert failed.outcome == "rolled-back"
    assert failed.reason_code == "candidate_health_check_failed"
    assert failed.state.active_slot == "slot-a"
    assert failed.state.fencing_generation == 4
    assert failed.state.slots["slot-a"].write_authority is True
    assert failed.state.slots["slot-a"].release_id == "1.5.0"
    assert failed.state.slots["slot-b"].running is False
    assert failed.state.slots["slot-b"].write_authority is False

    # 2. Healthy candidate slot-b passes health and post-handoff readback, advancing fencing
    # generation and transferring sole write authority to slot-b while keeping slot-a as rollback.
    upgraded = controller.upgrade(
        initial,
        target_release_id="1.6.0",
        target_image_digest=v2_digest,
        check_candidate_health=lambda _comp, _slot, _rel, _img: True,
        verify_post_handoff_readback=lambda _comp, slot, gen: (slot, gen) == ("slot-b", 5),
    )
    assert upgraded.outcome == "upgraded"
    assert upgraded.state.active_slot == "slot-b"
    assert upgraded.state.fencing_generation == 5
    assert upgraded.state.slots["slot-b"].write_authority is True
    assert upgraded.state.slots["slot-b"].release_id == "1.6.0"
    assert upgraded.state.slots["slot-a"].write_authority is False
    assert upgraded.state.slots["slot-a"].release_id == "1.5.0"


def test_proven_foundation_ownership_registry_verifies_signed_receipts_and_excludes_targets() -> (
    None
):
    foundation_key = _key("foundation-receipt-signer")
    fdai_resource = "resource:azure/rg-fdai/postgres-foundation"
    customer_tagged_resource = "resource:azure/rg-customer/manually-tagged-vm"

    unsigned_receipt = SignedFoundationOwnershipReceipt(
        resource_ref=fdai_resource,
        foundation_receipt_digest="sha256:" + "a" * 64,
        terraform_state_digest="sha256:" + "b" * 64,
        signature=b"",
    )
    signed_receipt = replace(
        unsigned_receipt,
        signature=foundation_key.sign(unsigned_receipt.canonical_payload()),
    )

    def verify_foundation(payload: bytes, sig: bytes) -> bool:
        try:
            foundation_key.public_key().verify(sig, payload)
            return True
        except InvalidSignature:
            return False

    ownership_registry = ProvenFoundationOwnershipRegistry().register_verified(
        signed_receipt,
        verify_signature=verify_foundation,
    )
    assert ownership_registry.is_proven_fdai_owned(fdai_resource)
    assert not ownership_registry.is_proven_fdai_owned(customer_tagged_resource)
    assert ownership_registry.upstream_risk_gate_signal(fdai_resource) == "deny"
    assert ownership_registry.upstream_risk_gate_signal(customer_tagged_resource) is None

    forged = replace(signed_receipt, signature=_key("other").sign(b"forged"))
    with pytest.raises(ValueError, match="foundation_ownership_signature_invalid"):
        ownership_registry.register_verified(forged, verify_signature=verify_foundation)
