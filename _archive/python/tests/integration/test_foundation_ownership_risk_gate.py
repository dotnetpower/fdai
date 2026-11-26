"""Integration test: RiskGate denies operations-loop actions on Foundation-owned resources
and manual customer tags never become FDAI-owned Entities (#2398)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fdai.core.risk_gate import (
    ActionPromotionRegistry,
    RiskDecisionOutcome,
    RiskGate,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.rule_catalog.schema.rule import load_rule_catalog
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai_deployment_cli.lifecycle_ownership_exclusion import (
    ProvenFoundationOwnershipRegistry,
    SignedFoundationOwnershipReceipt,
)

from fdai_lifecycle_hub.entity import Entity, EntitySettings, OwnershipEvidence, OwnershipGap

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
CATALOG_ROOT = REPO_ROOT / "rule-catalog" / "catalog"
POLICIES_ROOT = REPO_ROOT / "policies"
REMEDIATION_ROOT = REPO_ROOT / "rule-catalog" / "remediation"
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())


def test_risk_gate_denies_signed_foundation_owned_target_and_rejects_tag_only_entity() -> None:
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

    # 1. A manually tagged customer resource (fdai:managed=true without signed Foundation receipt
    # and Terraform state identity) has OwnershipGap.TAG_ONLY and stays unmanaged.
    tag_only_evidence = OwnershipEvidence(managed_tag=True)
    assert tag_only_evidence.gap is OwnershipGap.TAG_ONLY
    with pytest.raises(ValueError, match="without proven ownership"):
        Entity(
            entity_id="customer-vm",
            kind="service",
            ownership=tag_only_evidence,
            settings=EntitySettings(overrides=({"versions": ">=1.0.0", "values": {}},)),
        )

    # 2. RiskGate denies an operations-loop action targeting a resource with a verified signed
    # Foundation ownership receipt.
    schema_registry = PackageResourceSchemaRegistry()
    action_types = load_action_type_catalog(ACTION_TYPES_ROOT, schema_registry=schema_registry)
    action_types_by_name = {a.name: a for a in action_types}
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        resource_types = load_resource_type_registry_from_mapping(yaml.safe_load(fh))
    rules_by_id = {
        r.id: r
        for r in load_rule_catalog(
            CATALOG_ROOT,
            schema_registry=schema_registry,
            action_types=action_types,
            resource_types=resource_types,
            policies_root=POLICIES_ROOT,
            remediation_root=REMEDIATION_ROOT,
        )
    }

    action_type = action_types_by_name["remediate.tag-add"]
    rule = rules_by_id["object-storage.owner-tag.required"]
    gate = RiskGate(registry=ActionPromotionRegistry(allow_legacy_metrics=True))
    action_on_fdai_owned = Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000042",  # type: ignore[arg-type]
        idempotency_key="k-fdai-owned",
        event_id="00000000-0000-0000-0000-000000000041",  # type: ignore[arg-type]
        action_type=action_type.name,
        target_resource_ref=fdai_resource,
        operation=Operation.TAG,
        params={},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference=None),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=[rule.id],
        created_at="2026-10-22T00:00:00Z",  # type: ignore[arg-type]
    )
    decision = gate.evaluate(
        action=action_on_fdai_owned,
        rule=rule,
        action_type=action_type,
        upstream_signal=ownership_registry.upstream_risk_gate_signal(
            action_on_fdai_owned.target_resource_ref
        ),
    )
    assert decision.outcome is RiskDecisionOutcome.DENY
