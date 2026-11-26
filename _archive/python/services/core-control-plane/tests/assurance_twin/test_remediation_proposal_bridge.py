"""Tests for reviewed ActionType effect catalog, what-if producer, and remediation bridge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import (
    AbstainCode,
    AbstainResult,
    AssuranceTwinQueryGap,
    DiscoveryHandoffStatus,
    build_baseline_projection,
    derive_predicted_change_set,
)
from fdai.delivery.assurance_twin_proposal_intake import StateStoreTypedProposalReviewIntake
from fdai.delivery.assurance_twin_remediation_bridge import (
    GOVERNED_REVIEWED_ACTION_EFFECTS,
    AssuranceTwinRemediationProposalBridge,
    InMemoryRiskGatedRemediationSink,
    RemediationBridgeAuthorityError,
    RemediationBridgeError,
    TypedPipelineWhatIfProducer,
    build_reviewed_action_effect_catalog,
)
from fdai.shared.providers.projection import ResourceRef
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
INVENTORY_REVISION = "sha256:" + "c" * 64


class _RecordingDiscoverySink:
    def __init__(self) -> None:
        self.gaps: list[AssuranceTwinQueryGap] = []

    async def publish(self, gap: AssuranceTwinQueryGap) -> None:
        self.gaps.append(gap)


def test_reviewed_action_effect_catalog_declares_governance_provenance_and_derives_changes() -> (
    None
):
    catalog = build_reviewed_action_effect_catalog()
    assert len(catalog) == len(GOVERNED_REVIEWED_ACTION_EFFECTS) >= 3

    effect = catalog.effect_for("ops.enforce-minimum-tls", "1.0.0")
    assert effect is not None
    assert effect.review_ref.startswith("governance-review:action-effect:")
    assert effect.effect_digest.startswith("sha256:")

    target = ResourceRef("object-storage", "storage-prod-1")
    projection = build_baseline_projection(
        ((target, {"min_tls_version": "1.0", "https_only": False}),)
    )
    from fdai.core.assurance_twin import (
        ProposalWhatIfResult,
        TypedActionProposal,
        WhatIfStatus,
    )
    from fdai.core.assurance_twin.typed_proposal import WHAT_IF_SOURCE_AUTHORITY

    proposal = TypedActionProposal.create(
        action_type="ops.enforce-minimum-tls",
        action_type_version="1.0.0",
        targets=(target,),
        parameters={"min_tls_version": "1.2", "change_ticket": "CHG-101"},
    )
    what_if = ProposalWhatIfResult(
        proposal_digest=proposal.proposal_digest,
        status=WhatIfStatus.PASSED,
        complete=True,
        synthetic=False,
        source_authority=WHAT_IF_SOURCE_AUTHORITY,
        producer_id="sim-engine-1",
        observed_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=14),
        affected_targets=(target,),
        evidence_refs=("what-if:receipt:101",),
    )
    change_set = derive_predicted_change_set(
        proposal=proposal,
        what_if=what_if,
        effect=effect,
        projection=projection,
        inventory_revision=INVENTORY_REVISION,
        now=NOW,
    )
    assert change_set.scratch.properties(target) == {
        "min_tls_version": "1.2",
        "https_only": True,
    }


async def test_typed_pipeline_what_if_producer_submits_exact_pair_to_durable_intake() -> None:
    state_store = InMemoryStateStore()
    intake = StateStoreTypedProposalReviewIntake(store=state_store)
    catalog = build_reviewed_action_effect_catalog()
    producer = TypedPipelineWhatIfProducer(
        intake=intake,
        effects=catalog,
        clock=lambda: NOW,
    )

    target = ResourceRef("object-storage", "storage-prod-2")
    receipt = await producer.produce_and_submit(
        action_type="ops.set-public-access",
        action_type_version="1.0.0",
        targets=(target,),
        parameters={"public_access": "disabled", "justification": "remediate public exposure"},
        evidence_refs=("what-if:receipt:202",),
        correlation_id="corr-twin-202",
    )

    assert receipt.twin_execution_authority == "none"
    assert receipt.execution_authority is False
    assert receipt.review_ref == "governance-review:action-effect:ops.set-public-access@1.0.0"

    active = await intake.active()
    assert len(active) == 1
    assert active[0].key == receipt.intake_key
    assert active[0].proposal == receipt.proposal
    assert active[0].what_if == receipt.what_if

    # Rejects unreviewed ActionType version.
    with pytest.raises(RemediationBridgeError, match="unreviewed ActionType"):
        await producer.produce_and_submit(
            action_type="ops.set-public-access",
            action_type_version="9.9.9",
            targets=(target,),
            parameters={"public_access": "disabled"},
            evidence_refs=("what-if:receipt:203",),
            correlation_id="corr-twin-203",
        )


async def test_abstained_query_forwards_only_content_free_gap_to_discovery() -> None:
    discovery = _RecordingDiscoverySink()
    action_sink = InMemoryRiskGatedRemediationSink()
    bridge = AssuranceTwinRemediationProposalBridge(
        effects=build_reviewed_action_effect_catalog(),
        action_sink=action_sink,
        discovery_sink=discovery,
        compiler_revision="twin-compiler-2026.11",
    )

    sensitive_question = "Why is storage-account-secret-prod failing rule X?"
    abstain = AbstainResult(
        code=AbstainCode.UNRECOGNIZED_INTENT,
        reason="no covering query template",
    )
    receipt = await bridge.forward_abstained_query(
        abstain=abstain,
        raw_query=sensitive_question,
    )

    assert receipt.handoff_status is DiscoveryHandoffStatus.EMITTED
    assert receipt.grants_authority is False
    assert receipt.twin_execution_authority == "none"
    assert len(discovery.gaps) == 1
    gap = discovery.gaps[0]
    assert gap.grants_authority is False
    assert gap.code is AbstainCode.UNRECOGNIZED_INTENT
    assert gap.question_digest == receipt.question_digest
    assert sensitive_question not in repr(gap)


async def test_remediation_bridge_enforces_shadow_mode_and_risk_gate_without_elevation() -> None:
    state_store = InMemoryStateStore()
    intake = StateStoreTypedProposalReviewIntake(store=state_store)
    catalog = build_reviewed_action_effect_catalog()
    producer = TypedPipelineWhatIfProducer(intake=intake, effects=catalog, clock=lambda: NOW)
    action_sink = InMemoryRiskGatedRemediationSink()
    bridge = AssuranceTwinRemediationProposalBridge(
        effects=catalog,
        action_sink=action_sink,
        what_if_producer=producer,
        blast_radius_limit=2,
    )

    target = ResourceRef("key-vault", "kv-prod-1")

    # Cannot request enforce mode or execution authority from Twin read surface.
    with pytest.raises(RemediationBridgeAuthorityError, match="shadow mode"):
        await bridge.submit_remediation_proposal(
            finding_id="finding-1",
            rule_id="rule:key-vault.network-default-deny",
            action_type="ops.restrict-network-default-action",
            action_type_version="1.0.0",
            targets=(target,),
            parameters={"network_default_action": "Deny"},
            rollback_contract="scripted",
            stop_condition="abort on management probe failure",
            idempotency_key="idem-rem-1",
            correlation_id="corr-rem-1",
            requested_mode="enforce",
        )

    with pytest.raises(RemediationBridgeAuthorityError, match="execution authority"):
        await bridge.submit_remediation_proposal(
            finding_id="finding-1",
            rule_id="rule:key-vault.network-default-deny",
            action_type="ops.restrict-network-default-action",
            action_type_version="1.0.0",
            targets=(target,),
            parameters={"network_default_action": "Deny"},
            rollback_contract="scripted",
            stop_condition="abort on management probe failure",
            idempotency_key="idem-rem-1",
            correlation_id="corr-rem-1",
            bypass_risk_gate=True,
        )

    with pytest.raises(RemediationBridgeError, match="RollbackKind"):
        await bridge.submit_remediation_proposal(
            finding_id="finding-1",
            rule_id="rule:key-vault.network-default-deny",
            action_type="ops.restrict-network-default-action",
            action_type_version="1.0.0",
            targets=(target,),
            parameters={"network_default_action": "Deny"},
            rollback_contract="none",
            stop_condition="abort on management probe failure",
            idempotency_key="idem-rem-rb",
            correlation_id="corr-rem-rb",
        )

    # Cannot exceed blast radius cap.
    with pytest.raises(RemediationBridgeError, match="blast_radius_limit"):
        await bridge.submit_remediation_proposal(
            finding_id="finding-1",
            rule_id="rule:key-vault.network-default-deny",
            action_type="ops.restrict-network-default-action",
            action_type_version="1.0.0",
            targets=(
                ResourceRef("key-vault", "kv-1"),
                ResourceRef("key-vault", "kv-2"),
                ResourceRef("key-vault", "kv-3"),
            ),
            parameters={"network_default_action": "Deny"},
            rollback_contract="scripted",
            stop_condition="abort on management probe failure",
            idempotency_key="idem-rem-blast",
            correlation_id="corr-rem-blast",
        )

    envelope = await bridge.submit_remediation_proposal(
        finding_id="finding-1",
        rule_id="rule:key-vault.network-default-deny",
        action_type="ops.restrict-network-default-action",
        action_type_version="1.0.0",
        targets=(target,),
        parameters={"network_default_action": "Deny", "change_ticket": "CHG-500"},
        rollback_contract="scripted",
        stop_condition="abort on management probe failure",
        idempotency_key="idem-rem-valid",
        correlation_id="corr-rem-valid",
        risk_tier="high",
    )

    assert envelope.mode == "shadow"
    assert envelope.twin_execution_authority == "none"
    assert envelope.execution_authority is False
    assert envelope.requires_risk_gate is True
    assert envelope.requires_hil_approval is True
    assert envelope.intake_key is not None
    assert len(action_sink.proposals) == 1
    assert len(await intake.active()) == 1
