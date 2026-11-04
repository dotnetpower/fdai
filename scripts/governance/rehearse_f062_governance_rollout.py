#!/usr/bin/env python3
"""Rehearse and verify all 13 F06.2 governance rollout exit criteria for Issue #2204.

This script exercises the F06.2 governance qualification and nine-phase Rule revision
rollout end to end without granting activation, approval, promotion, or execution
authority. It runs deterministically against :class:`InMemoryStateStore` by default and
also supports :class:`PostgresStateStore` (with :class:`PostgresRuleActivationCohortCommitStore`)
when ``--postgres`` and ``FDAI_DATABASE_URL`` are provided.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fdai.core.governance_qualification import (
    CohortCase,
    GroundTruth,
    HoldReason,
    QualificationBinding,
    Readiness,
    SourceObservation,
    SourceState,
    Verdict,
    build_qualification_record,
    freeze_cohort,
    measure_cohort,
    reconcile_ledger_digests,
    reconcile_sources,
)
from fdai.core.operational_learning import (
    DiscoveryCandidate,
    DiscoveryCandidateState,
    DiscoveryCycleConfig,
    DiscoveryCycleScheduler,
    DiscoveryIntegrationReceipt,
    DiscoveryModelReview,
    DiscoveryObservationBatch,
    DiscoverySignalKind,
    DiscoveryVerificationReceipt,
    OverrideSignalThresholds,
)
from fdai.core.operational_learning.discovery_persistence import (
    interval_bucket_start,
)
from fdai.core.rbac.roles import Role
from fdai.core.rule_activation import (
    RuleActivationCoordinator,
    StateStoreRuleActivationLedger,
    build_rule_activation_generation,
)
from fdai.core.rule_activation.cohort import (
    LocalRuleActivationCohortCommitStore,
    StateStoreRuleActivationCohort,
)
from fdai.core.rule_activation.identity_upgrade import StateStoreRuleIdentityUpgrade
from fdai.core.rule_activation.manifest import (
    RuleActivationManifestReplayError,
    RuleActivationManifestVerifier,
)
from fdai.core.rule_activation.retention import (
    StateStoreRuleRevisionRetention,
)
from fdai.core.rule_activation.revision_change import StateStoreRuleRevisionChanges
from fdai.core.rule_activation.slots import StateStoreRuleActivationSlots
from fdai.delivery.exemption_lifecycle import (
    EventBusExemptionExpiryCommandPublisher,
    ExemptionLifecycleCoordinator,
)
from fdai.delivery.override_discovery import (
    StateStoreOverrideAuditReader,
    bind_override_discovery_source,
)
from fdai.delivery.persistence.state_store_rule_activation_authority import (
    StateStoreRuleActivationAuthority,
)
from fdai.delivery.promotion_attestation import (
    GovernancePromotionAttestation,
    promotion_attestation_digest,
)
from fdai.rule_catalog.schema.exemption import (
    Exemption,
    ExemptionScope,
    ExemptionState,
)
from fdai.rule_catalog.schema.exemption_lifecycle import (
    ExemptionAssignmentBinding,
    ExemptionExpiryDigest,
)
from fdai.rule_catalog.schema.governance_review_authority import (
    GovernanceApproval,
    GovernanceChangeClass,
    GovernancePrincipal,
    GovernanceReviewRequest,
    validate_governance_review,
)
from fdai.runtime.rule_activation import (
    RuleActivationRuntimeReconciler,
    reconcile_rule_activation,
)
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.rule_activation_cohort import RuleActivationCohortCommitStore
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.rule_activation import (
    RuleActivationApproval,
    RuleActivationCommand,
    RuleActivationDelta,
    RuleActivationProposal,
    RuleActivationSource,
    RuleActivationStatus,
    rule_activation_proposal_digest,
)
from fdai_service_contracts.rule_activation_cohort import (
    RuleCohortPrepareV2,
    RuleReplicaAcknowledgementV2,
    RuleReplicaAppliedV2,
    RuleReplicaDepartureEvidence,
    RuleReplicaDepartureKind,
    RuleReplicaDisposition,
    RuleReplicaIdentity,
    build_rule_cohort_prepare_v2,
    rule_replica_acknowledgement_digest,
    rule_replica_departure_evidence_digest,
)
from fdai_service_contracts.rule_activation_identity import (
    RuleActivationIdentityContextV2,
    build_rule_activation_identity_context_v2,
    build_rule_activation_identity_transition_v2,
)
from fdai_service_contracts.rule_activation_manifest import (
    RuleActivationManifest,
    RuleActivationManifestExpectation,
    RuleActivationManifestSource,
    RuleActivationManifestTrust,
    RuleActivationTrustedKey,
    RuleRevisionIdentityRef,
    rule_revision_registry_root,
    sign_rule_activation_manifest,
)
from fdai_service_contracts.rule_activation_retention import (
    RuleRevisionReferenceKind,
    RuleRevisionRetirementApprovalV2,
    RuleRevisionRetirementCommandV2,
    RuleRevisionRetirementProposalV2,
    rule_revision_retirement_approval_digest,
    rule_revision_retirement_command_digest,
    rule_revision_retirement_proposal_digest,
)
from fdai_service_contracts.rule_activation_revision_change import (
    RuleRevisionChangeApprovalV2,
    RuleRevisionChangeCommandV2,
    RuleRevisionChangeProposalV2,
    RuleRevisionTransitionKind,
    rule_revision_change_approval_digest,
    rule_revision_change_command_digest,
    rule_revision_change_proposal_digest,
)
from fdai_service_contracts.rule_activation_slots import (
    RuleBindingMode,
    RuleDualRevisionSlotV2,
    RuleRevisionBindingV2,
    RuleRevisionPromotionApprovalV2,
    rule_dual_revision_slot_digest,
    rule_revision_binding_digest,
    rule_revision_promotion_approval_digest,
)
from fdai_service_contracts.rule_activation_upgrade import (
    RuleIdentityUpgradeApprovalV2,
    RuleIdentityUpgradeCommandV2,
    RuleIdentityUpgradeProposalV2,
    RuleReplicaCompatibilityEvidenceV2,
    RuleReviewedPolicyBaselineV2,
    RuleReviewedRevisionBaselineEntryV2,
    rule_identity_upgrade_approval_digest,
    rule_identity_upgrade_command_digest,
    rule_identity_upgrade_proposal_digest,
    rule_replica_compatibility_evidence_digest,
    rule_reviewed_policy_baseline_digest,
)
from fdai_service_contracts.rule_activation_versioning import (
    RuleActivationRecordKind,
    decode_rule_activation_record,
    encode_rule_activation_record,
)

CUTOFF = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
INSTALLATION_ID = "installation-fdai-dev-wus3"
MANAGEMENT_SCOPE_ID = "scope-ed8b63ea22cd3133"
ENVIRONMENT_CLASS = "development"
RULE_GENERATION_DIGEST = "sha256:978d0e03b50e4a6da763e9c119f8e37e3302f37c0c6a086f7331792f6106c419"
ONTOLOGY_RELEASE_DIGEST = "sha256:4786ea679289e9b134d6f82447d2640b1f9bf517f2953ed73e2bc3aea32886d1"
REVIEWED_SOURCE_REVISION = "bd22c6f9e937dbb1790822db63627a5dd4ea288e"
PROPOSER_OID = "00000000-0000-0000-0000-000000002203"
OWNER_OID = "00000000-0000-0000-0000-000000002204"
SECOND_APPROVER_OID = "00000000-0000-0000-0000-000000002205"
EXECUTOR_PRINCIPAL = "uami-executor-fdai-dev-wus3"
LINKED_LIVE_EXPIRY_AUDIT_ID = "exemption-expiry-digest:f8a9ebb21cdcb07587e89e91e457396d"
LINKED_LIVE_EXPIRY_REVISION = (
    "sha256:6ec83050636f04b6796a159bd02b3afa3bd84a01b9c5daabdcbf46c380795474"
)

PROVIDER_REVISIONS: dict[str, str] = {
    "activity-log": "2026-10-27.r1",
    "control-gap": "2026-10-27.r1",
    "cost": "2026-10-27.r1",
    "drift": "2026-10-27.r1",
    "guest-logs": "2026-10-27.r1",
    "inventory": "2026-10-27.r1",
    "logs": "2026-10-27.r1",
    "metrics": "2026-10-27.r1",
    "network-config": "2026-10-27.r1",
    "recovery": "2026-10-27.r1",
    "resource-health": "2026-10-27.r2",
    "service-health": "2026-10-27.r1",
}


def _require(condition: bool, message: str = "F06.2 qualification check failed") -> None:
    if not condition:
        raise RuntimeError(message)


def _digest_for(tag: str) -> str:
    return canonical_digest({"tag": tag})


def _hex_digest_for(tag: str) -> str:
    return _digest_for(tag).removeprefix("sha256:")


def _rule(rule_id: str, version: str = "1.0.0") -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version=version,
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type="kubernetes.cluster",
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference=f"policies/{rule_id}.rego"),
        remediation=Remediation(template_ref=f"remediation/{rule_id}.tftpl"),
        remediates=f"remediate.{rule_id}",
        provenance=Provenance(
            source_url="https://learn.microsoft.com/azure/aks/security",
            resolved_ref=REVIEWED_SOURCE_REVISION,
            content_hash=_digest_for(f"rule:{rule_id}:{version}"),
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=CUTOFF,
        ),
    )


@dataclass
class _ReplicaRuntime:
    calls: list[tuple[tuple[str, ...], str]] = field(default_factory=list)
    _generation_digest: str | None = None

    @property
    def rule_generation_digest(self) -> str | None:
        return self._generation_digest

    async def replace_rule_generation(
        self,
        *,
        rules: Sequence[Rule],
        generation_digest: str,
    ) -> None:
        self.calls.append((tuple(rule.id for rule in rules), generation_digest))
        self._generation_digest = generation_digest


@dataclass
class _RegistryReader:
    retained: set[tuple[str, str, str]]

    def has_retained_closure(self, revision: RuleRevisionIdentityRef) -> bool:
        return (
            revision.rule_id,
            revision.rule_version,
            revision.revision_digest,
        ) in self.retained


@dataclass
class _DigestNotifier:
    delivered: list[str] = field(default_factory=list)

    async def notify_expiring(self, decision: Any) -> None:
        self.delivered.append(str(decision.exemption_id))

    async def notify_expiry_digest(self, digest: ExemptionExpiryDigest) -> None:
        self.delivered.append(digest.items[0].exemption_revision)


@dataclass
class _InMemoryEventBus:
    published: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        self.published.append((topic, key, dict(payload)))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))


@dataclass(frozen=True, slots=True)
class _DiscoveryPrimaryModel:
    model_identity: str = "azure-openai:gpt-5-primary"
    model_family: str = "openai-gpt"

    async def hypothesize(
        self,
        batch: DiscoveryObservationBatch,
    ) -> tuple[DiscoveryCandidate, ...]:
        override_signals = [
            sig for sig in batch.signals if sig.kind is DiscoverySignalKind.OVERRIDE
        ]
        if not override_signals:
            return ()
        sig = override_signals[0]
        return (
            DiscoveryCandidate(
                proposal_kind="revision",
                target_rule_id=str(sig.facts["rule_id"]),
                source_signal_ids=(sig.signal_id,),
                payload={
                    "resource_type": "postgresql.server",
                    "check_logic_ref": "policies/postgresql_pitr.rego",
                    "provenance_url": (
                        "https://learn.microsoft.com/azure/postgresql/flexible-server"
                    ),
                    "provenance_ref": REVIEWED_SOURCE_REVISION,
                    "content_hash": _digest_for("candidate:postgresql_pitr:v2"),
                    "license": "MIT",
                    "redistribution": "embeddable",
                    "proposed_min_retention_days": "3",
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class _DiscoveryReviewerModel:
    model_identity: str = "anthropic:claude-sonnet-reviewer"
    model_family: str = "anthropic-claude"

    async def review(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryModelReview:
        del batch
        return DiscoveryModelReview(
            candidate_digest=candidate.digest,
            approved=True,
            reason="Independent model verified override-driven parameter narrowing.",
        )


class _DiscoveryVerifier:
    async def verify(
        self,
        candidate: DiscoveryCandidate,
        batch: DiscoveryObservationBatch,
    ) -> DiscoveryVerificationReceipt:
        del batch
        return DiscoveryVerificationReceipt(
            candidate_digest=candidate.digest,
            passed=True,
            reason="schema_provenance_rego_regression_verified",
        )


class _DiscoveryIntegrator:
    async def integrate(
        self,
        candidate: DiscoveryCandidate,
        receipt: DiscoveryVerificationReceipt,
    ) -> DiscoveryIntegrationReceipt:
        del receipt
        return DiscoveryIntegrationReceipt(
            candidate_digest=candidate.digest,
            review_ref=f"catalog-pr:{candidate.digest[:16]}",
            already_existed=False,
        )


def _single_operator_profile() -> ApprovalProfileRevision:
    fields = {
        "revision_id": "approval-profile-dev-single-op-2204",
        "approval_profile": ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION.value,
        "executor_principal": EXECUTOR_PRINCIPAL,
        "effective_from": CUTOFF.isoformat(),
        "operator_principal": OWNER_OID,
    }
    return ApprovalProfileRevision(
        revision_id=fields["revision_id"],
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=EXECUTOR_PRINCIPAL,
        policy_digest=approval_profile_policy_digest(fields),
        effective_from=CUTOFF,
        operator_principal=OWNER_OID,
    )


def _revision_ref(rule_id: str, rule_version: str) -> tuple[RuleRevisionIdentityRef, str, str]:
    def_digest = _digest_for(f"def:{rule_id}:{rule_version}")
    pol_digest = _digest_for(f"pol:{rule_id}:{rule_version}")
    rev_digest = canonical_digest(
        {
            "rule_id": rule_id,
            "rule_version": rule_version,
            "definition_digest": def_digest,
            "policy_identity_digest": pol_digest,
        }
    )
    return (
        RuleRevisionIdentityRef(
            rule_id=rule_id,
            rule_version=rule_version,
            revision_digest=rev_digest,
        ),
        def_digest,
        pol_digest,
    )


async def _retain_attestation(
    store: StateStore,
    *,
    profile: ApprovalProfileRevision,
    action_type_id: str,
    evidence_digest: str,
    idempotency_key: str,
    scenario_set_version: str,
    request_fingerprint: str,
    approved_at: datetime,
    nonce: str,
    head_committed_at: datetime = CUTOFF,
    author_oid: str = PROPOSER_OID,
    change_class: GovernanceChangeClass = GovernanceChangeClass.ENFORCE_PROMOTION,
) -> str:
    roles = frozenset({Role.OWNER, Role.APPROVER, Role.CONTRIBUTOR})
    attestation = GovernancePromotionAttestation(
        review=GovernanceReviewRequest(
            change_class=change_class,
            author=GovernancePrincipal(oid=author_oid, roles=roles),
            head_revision=REVIEWED_SOURCE_REVISION,
            head_committed_at=head_committed_at,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(oid=OWNER_OID, roles=roles),
                    reviewed_revision=REVIEWED_SOURCE_REVISION,
                    approved_at=approved_at,
                    phishing_resistant=True,
                ),
            ),
            approval_profile=profile,
        ),
        action_type_id=action_type_id,
        fdai_revision=REVIEWED_SOURCE_REVISION,
        scenario_set_version=scenario_set_version,
        evidence_digest=evidence_digest,
        idempotency_key=idempotency_key,
        nonce=nonce,
        request_fingerprint=request_fingerprint,
    )
    digest = promotion_attestation_digest(attestation)
    await store.write_state(
        "governance-promotion-attestation:" + digest,
        {
            "state": "reserved",
            "approval_receipt_digest": digest,
            "attestation": attestation.as_json(),
        },
    )
    return "sha256:" + digest


async def _prepare_and_apply_two_replica_cohort(
    *,
    cohort_ledger: StateStoreRuleActivationCohort,
    identity_ctx: RuleActivationIdentityContextV2,
    release_id: str,
    revision_registry_root: str,
    predecessor_cohort: RuleCohortPrepareV2 | None,
    expected_prepare_revision: int,
    expected_candidate_revision: int,
    base_time: datetime,
    write_schema_version: str = "2.0.0",
) -> tuple[
    RuleCohortPrepareV2,
    tuple[RuleReplicaIdentity, ...],
    tuple[RuleReplicaAcknowledgementV2, ...],
    str,
]:
    replicas = (
        RuleReplicaIdentity(
            replica_id="core-replica-a",
            principal_id="uami-core-replica-a",
            release_id=release_id,
            startup_epoch=f"epoch-a-{release_id}",
            serving_lease_id=f"lease-a-{release_id}",
            serving_lease_expires_at=base_time + timedelta(minutes=30),
        ),
        RuleReplicaIdentity(
            replica_id="core-replica-b",
            principal_id="uami-core-replica-b",
            release_id=release_id,
            startup_epoch=f"epoch-b-{release_id}",
            serving_lease_id=f"lease-b-{release_id}",
            serving_lease_expires_at=base_time + timedelta(minutes=30),
        ),
    )
    departures: tuple[RuleReplicaDepartureEvidence, ...] = ()
    if predecessor_cohort is not None:
        departures = tuple(
            RuleReplicaDepartureEvidence(
                replica=prev_rep,
                kind=RuleReplicaDepartureKind.DRAINED,
                serving_inventory_digest=predecessor_cohort.serving_inventory_digest,
                authentication_receipt_digest=_digest_for(
                    f"drain-auth:{release_id}:{prev_rep.replica_id}"
                ),
                observed_at=base_time,
                evidence_digest=rule_replica_departure_evidence_digest(
                    replica=prev_rep,
                    kind=RuleReplicaDepartureKind.DRAINED,
                    serving_inventory_digest=predecessor_cohort.serving_inventory_digest,
                    authentication_receipt_digest=_digest_for(
                        f"drain-auth:{release_id}:{prev_rep.replica_id}"
                    ),
                    observed_at=base_time,
                ),
            )
            for prev_rep in predecessor_cohort.replicas
        )
    serving_inventory_digest = _digest_for(f"serving-inventory:{release_id}")
    cohort = build_rule_cohort_prepare_v2(
        generation=identity_ctx.generation,
        serving_inventory_digest=serving_inventory_digest,
        revision_registry_root=revision_registry_root,
        catalog_manifest_digest=identity_ctx.catalog_manifest.manifest_digest,
        replicas=replicas,
        departures=departures,
        predecessor_prepare_digest=(
            predecessor_cohort.prepare_digest if predecessor_cohort is not None else None
        ),
        prepared_at=base_time,
    )
    await cohort_ledger.prepare(
        cohort,
        now=base_time,
        expected_revision=expected_prepare_revision,
        authenticated_serving_inventory_digest=serving_inventory_digest,
        authenticated_replicas=replicas,
        verified_departure_digests={item.evidence_digest for item in departures},
    )
    acks: list[RuleReplicaAcknowledgementV2] = []
    for idx, replica in enumerate(replicas, start=1):
        auth_receipt = _digest_for(f"ack-auth:{release_id}:{replica.replica_id}")
        ack_values: dict[str, Any] = {
            "prepare_digest": cohort.prepare_digest,
            "replica_id": replica.replica_id,
            "principal_id": replica.principal_id,
            "release_id": replica.release_id,
            "startup_epoch": replica.startup_epoch,
            "serving_lease_id": replica.serving_lease_id,
            "revision_registry_root": revision_registry_root,
            "catalog_manifest_digest": identity_ctx.catalog_manifest.manifest_digest,
            "profile_snapshot_digest": identity_ctx.profile_snapshot.snapshot_digest,
            "generation_digest": identity_ctx.generation.generation_digest,
            "supported_read_schema_versions": ("1.0.0", "2.0.0"),
            "write_schema_version": write_schema_version,
            "disposition": RuleReplicaDisposition.ACKNOWLEDGED,
            "reason": "v1/v2 compatibility verified",
            "authentication_receipt_digest": auth_receipt,
            "observed_at": base_time + timedelta(seconds=idx),
        }
        ack = RuleReplicaAcknowledgementV2(
            **ack_values,
            acknowledgement_digest=rule_replica_acknowledgement_digest(**ack_values),
        )
        await cohort_ledger.acknowledge(
            ack,
            authenticated_identity=replica,
            authentication_receipt_digest=auth_receipt,
            now=base_time + timedelta(seconds=idx),
        )
        acks.append(ack)
    candidate = await cohort_ledger.activate_candidate(
        cohort.prepare_digest,
        now=base_time + timedelta(seconds=3),
        expected_revision=expected_candidate_revision,
    )
    for idx, replica in enumerate(replicas, start=4):
        _require(
            await cohort_ledger.admit_replica(
                prepare_digest=cohort.prepare_digest,
                replica_id=replica.replica_id,
                serving_lease_id=replica.serving_lease_id,
                now=base_time + timedelta(seconds=idx),
            )
        )
        await cohort_ledger.record_applied(
            RuleReplicaAppliedV2(
                prepare_digest=cohort.prepare_digest,
                acknowledgement_set_digest=candidate.acknowledgement_set_digest,
                replica_id=replica.replica_id,
                principal_id=replica.principal_id,
                release_id=replica.release_id,
                startup_epoch=replica.startup_epoch,
                serving_lease_id=replica.serving_lease_id,
                generation_digest=identity_ctx.generation.generation_digest,
                applied_at=base_time + timedelta(seconds=idx),
            ),
            authenticated_identity=replica,
        )
    return cohort, replicas, tuple(acks), candidate.acknowledgement_set_digest


async def _verify_and_reserve_manifest(
    *,
    verifier: RuleActivationManifestVerifier,
    private_key: Ed25519PrivateKey,
    identity_ctx: RuleActivationIdentityContextV2,
    release_id: str,
    revision_registry_root: str,
    nonce: str,
    now: datetime,
) -> RuleActivationManifest:
    scope_digest = _digest_for(f"scope:{INSTALLATION_ID}:{MANAGEMENT_SCOPE_ID}")
    manifest = RuleActivationManifest(
        source=RuleActivationManifestSource.OFFLINE_PACKAGE,
        release_id=release_id,
        source_id=f"offline-package:{release_id}",
        target_generation_id=identity_ctx.generation.generation_id,
        target_generation_digest=identity_ctx.generation.generation_digest,
        profile_id=identity_ctx.profile_snapshot.profile_id,
        profile_version=identity_ctx.profile_snapshot.profile_version,
        catalog_manifest_digest=identity_ctx.catalog_manifest.manifest_digest,
        revision_registry_root=revision_registry_root,
        members=identity_ctx.generation.members,
        deployment_scope_digest=scope_digest,
        nonce=nonce,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    signed = sign_rule_activation_manifest(
        manifest,
        key_id="release-signing-key-2204",
        private_key=private_key,
    )
    expectation = RuleActivationManifestExpectation(
        source=manifest.source,
        release_id=manifest.release_id,
        source_id=manifest.source_id,
        target_generation_id=manifest.target_generation_id,
        target_generation_digest=manifest.target_generation_digest,
        profile_id=manifest.profile_id,
        profile_version=manifest.profile_version,
        catalog_manifest_digest=manifest.catalog_manifest_digest,
        revision_registry_root=manifest.revision_registry_root,
        members=manifest.members,
        deployment_scope_digest=manifest.deployment_scope_digest,
    )
    verified = await verifier.verify_and_reserve(signed, now=now, expected=expectation)
    try:
        await verifier.verify_and_reserve(signed, now=now, expected=expectation)
    except RuleActivationManifestReplayError:
        pass
    else:
        raise RuntimeError("expected duplicate signed manifest reservation to be rejected")
    return verified


async def run_f062_qualification_rehearsal(
    *,
    store: StateStore | None = None,
    commit_store: RuleActivationCohortCommitStore | None = None,
    migration_now: datetime = CUTOFF,
) -> dict[str, Any]:
    """Execute all 13 F06.2 governance rollout exit criteria and return the receipt."""

    clock_now = migration_now + timedelta(seconds=30)
    active_store: StateStore = store or InMemoryStateStore(linearization_clock=lambda: clock_now)
    active_commit_store: RuleActivationCohortCommitStore = (
        commit_store
        or LocalRuleActivationCohortCommitStore(store=active_store, clock=lambda: clock_now)
    )
    profile = _single_operator_profile()
    authority = StateStoreRuleActivationAuthority(
        active_store,
        active_approval_profile=profile,
    )

    # Criterion 1: Record exact installation, scope, class, revisions, and cutoff before collection
    binding = QualificationBinding(
        installation_id=INSTALLATION_ID,
        management_scope_id=MANAGEMENT_SCOPE_ID,
        environment_class=ENVIRONMENT_CLASS,
        rule_generation_digest=RULE_GENERATION_DIGEST,
        ontology_release_digest=ONTOLOGY_RELEASE_DIGEST,
        provider_revisions=PROVIDER_REVISIONS,
        evidence_cutoff=CUTOFF,
    )

    # Criteria 2 & 3: Nine-phase legacy Rule pointer and 2-replica cohort migration + rollback
    rule_alpha_v1 = _rule("aks.container.no-privileged", "1.0.0")
    rule_beta_v1 = _rule("postgresql.server.pitr-enabled", "1.0.0")
    legacy_ledger = StateStoreRuleActivationLedger(store=active_store)
    _, seeded_legacy_gen = await reconcile_rule_activation(
        ledger=legacy_ledger,
        available_rules=(rule_alpha_v1, rule_beta_v1),
        profile_id="default",
        profile_version="1.0.0",
        source_ref=f"git:{REVIEWED_SOURCE_REVISION}",
        source_digest=_hex_digest_for("seed:default:1.0.0"),
        requested_by=OWNER_OID,
        approved_by=SECOND_APPROVER_OID,
        source=RuleActivationSource.INSTALLATION,
        clock=lambda: migration_now,
    )
    encoded_probe = encode_rule_activation_record(
        RuleActivationRecordKind.GENERATION,
        {"generation": seeded_legacy_gen.model_dump(mode="json")},
    )
    decoded_probe = decode_rule_activation_record(
        encoded_probe,
        expected_kind=RuleActivationRecordKind.GENERATION,
    )
    decoded_gen = cast(Mapping[str, Any], decoded_probe.body["generation"])
    _require(decoded_gen["generation_id"] == seeded_legacy_gen.generation_id)

    rev_alpha_100, def_alpha_100, pol_alpha_100 = _revision_ref(rule_alpha_v1.id, "1.0.0")
    rev_alpha_110, _, _ = _revision_ref(rule_alpha_v1.id, "1.1.0")
    rev_beta_100, def_beta_100, pol_beta_100 = _revision_ref(rule_beta_v1.id, "1.0.0")
    rev_retired_100, _, _ = _revision_ref("legacy.deprecated.storage-http", "1.0.0")
    catalog_revisions = tuple(
        sorted(
            (rev_alpha_100, rev_alpha_110, rev_beta_100, rev_retired_100),
            key=lambda item: (item.rule_id, item.rule_version, item.revision_digest),
        )
    )
    upgrade_members = (rev_alpha_100, rev_beta_100)
    forward_members = (rev_alpha_110, rev_beta_100)
    registry_root_upgrade = rule_revision_registry_root(upgrade_members)
    registry_root_catalog = rule_revision_registry_root(catalog_revisions)

    signing_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key_b64 = base64.b64encode(
        signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode("ascii")
    manifest_trust = RuleActivationManifestTrust(
        approved_by=OWNER_OID,
        valid_from=migration_now - timedelta(days=1),
        valid_until=migration_now + timedelta(days=7),
        keys=(
            RuleActivationTrustedKey(
                key_id="release-signing-key-2204",
                public_key=public_key_b64,
                valid_from=migration_now - timedelta(days=1),
                valid_until=migration_now + timedelta(days=7),
            ),
        ),
        revocation_checked_at=migration_now,
    )
    manifest_verifier = RuleActivationManifestVerifier(trust=manifest_trust, store=active_store)
    cohort_ledger = StateStoreRuleActivationCohort(
        store=active_store,
        commit_store=active_commit_store,
    )

    identity_v100 = build_rule_activation_identity_context_v2(
        catalog_revisions=catalog_revisions,
        profile_id="default",
        profile_version="1.0.0",
        active_members=upgrade_members,
    )
    manifest_v100 = await _verify_and_reserve_manifest(
        verifier=manifest_verifier,
        private_key=signing_key,
        identity_ctx=identity_v100,
        release_id="release-1.1.1",
        revision_registry_root=registry_root_upgrade,
        nonce="1" * 64,
        now=migration_now + timedelta(seconds=1),
    )
    cohort_v100, replicas_v100, acks_v100, _ = await _prepare_and_apply_two_replica_cohort(
        cohort_ledger=cohort_ledger,
        identity_ctx=identity_v100,
        release_id="release-1.1.1",
        revision_registry_root=registry_root_upgrade,
        predecessor_cohort=None,
        expected_prepare_revision=0,
        expected_candidate_revision=0,
        base_time=migration_now + timedelta(seconds=2),
        write_schema_version="1.0.0",
    )

    baseline_entries = (
        RuleReviewedRevisionBaselineEntryV2(
            legacy_member=seeded_legacy_gen.members[0],
            revision=rev_alpha_100,
            definition_digest=def_alpha_100,
            policy_identity_digest=pol_alpha_100,
        ),
        RuleReviewedRevisionBaselineEntryV2(
            legacy_member=seeded_legacy_gen.members[1],
            revision=rev_beta_100,
            definition_digest=def_beta_100,
            policy_identity_digest=pol_beta_100,
        ),
    )
    baseline_values: dict[str, Any] = {
        "release_id": "release-1.1.1",
        "reviewed_source_revision": REVIEWED_SOURCE_REVISION,
        "revision_registry_root": registry_root_upgrade,
        "entries": baseline_entries,
        "reviewed_at": migration_now,
    }
    reviewed_baseline = RuleReviewedPolicyBaselineV2(
        **baseline_values,
        baseline_digest=rule_reviewed_policy_baseline_digest(**baseline_values),
    )
    upgrade_proposal_values: dict[str, Any] = {
        "source_generation_id": seeded_legacy_gen.generation_id,
        "source_generation_digest": seeded_legacy_gen.generation_digest,
        "target_identity": identity_v100,
        "signed_manifest_digest": manifest_v100.manifest_digest,
        "release_id": "release-1.1.1",
        "policy_baseline_digest": reviewed_baseline.baseline_digest,
        "cohort_prepare_digest": cohort_v100.prepare_digest,
        "proposed_by": PROPOSER_OID,
        "proposed_at": migration_now + timedelta(seconds=6),
    }
    upgrade_proposal = RuleIdentityUpgradeProposalV2(
        **upgrade_proposal_values,
        proposal_digest=rule_identity_upgrade_proposal_digest(**upgrade_proposal_values),
    )
    upgrade_auth_receipt = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-identity-upgrade",
        evidence_digest=upgrade_proposal.proposal_digest,
        idempotency_key=upgrade_proposal.proposal_digest,
        scenario_set_version=identity_v100.profile_snapshot.profile_version,
        request_fingerprint=identity_v100.generation.generation_digest,
        approved_at=migration_now + timedelta(seconds=7),
        head_committed_at=migration_now,
        nonce="attest-upgrade-2204",
    )
    upgrade_approval_values: dict[str, Any] = {
        "proposal_digest": upgrade_proposal.proposal_digest,
        "authority_receipt_digest": upgrade_auth_receipt,
        "approval_profile_digest": profile.policy_digest,
        "requester_id": PROPOSER_OID,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=7),
    }
    upgrade_approval = RuleIdentityUpgradeApprovalV2(
        **upgrade_approval_values,
        approval_digest=rule_identity_upgrade_approval_digest(**upgrade_approval_values),
    )
    compat_evidence = tuple(
        RuleReplicaCompatibilityEvidenceV2(
            replica=rep,
            supported_read_schema_versions=("1.0.0", "2.0.0"),
            write_schema_version="1.0.0",
            signed_manifest_digest=manifest_v100.manifest_digest,
            verifier_principal_id=ack.principal_id,
            authentication_receipt_digest=ack.authentication_receipt_digest,
            verified_at=ack.observed_at,
            evidence_digest=rule_replica_compatibility_evidence_digest(
                replica=rep,
                supported_read_schema_versions=("1.0.0", "2.0.0"),
                write_schema_version="1.0.0",
                signed_manifest_digest=manifest_v100.manifest_digest,
                verifier_principal_id=ack.principal_id,
                authentication_receipt_digest=ack.authentication_receipt_digest,
                verified_at=ack.observed_at,
            ),
        )
        for rep, ack in zip(replicas_v100, acks_v100, strict=True)
    )
    upgrade_cmd_values: dict[str, Any] = {
        "proposal": upgrade_proposal,
        "approval": upgrade_approval,
        "compatibility_evidence": compat_evidence,
        "commanded_at": migration_now + timedelta(seconds=8),
    }
    upgrade_command = RuleIdentityUpgradeCommandV2(
        **upgrade_cmd_values,
        command_digest=rule_identity_upgrade_command_digest(**upgrade_cmd_values),
    )
    identity_ledger = StateStoreRuleIdentityUpgrade(
        store=active_store,
        legacy_ledger=legacy_ledger,
        cohort_ledger=cohort_ledger,
        authorizer=authority,
    )
    upgraded_pointer = await identity_ledger.apply(
        upgrade_command,
        baseline=reviewed_baseline,
    )
    _require(upgraded_pointer.revision == 1)
    _require(upgraded_pointer.release_id == "release-1.1.1")

    # Phase 6 & 8: Dual-revision slot + Forward Revision Change (1.0.0 -> 1.1.0)
    identity_v110 = build_rule_activation_identity_context_v2(
        catalog_revisions=catalog_revisions,
        profile_id="default",
        profile_version="1.1.0",
        active_members=forward_members,
    )
    manifest_v110 = await _verify_and_reserve_manifest(
        verifier=manifest_verifier,
        private_key=signing_key,
        identity_ctx=identity_v110,
        release_id="release-1.1.2",
        revision_registry_root=registry_root_catalog,
        nonce="2" * 64,
        now=migration_now + timedelta(seconds=10),
    )
    cohort_v110, _, _, ack_set_v110 = await _prepare_and_apply_two_replica_cohort(
        cohort_ledger=cohort_ledger,
        identity_ctx=identity_v110,
        release_id="release-1.1.2",
        revision_registry_root=registry_root_catalog,
        predecessor_cohort=cohort_v100,
        expected_prepare_revision=1,
        expected_candidate_revision=3,
        base_time=migration_now + timedelta(seconds=11),
    )

    slot_ledger = StateStoreRuleActivationSlots(
        store=active_store,
        cohort_ledger=cohort_ledger,
        promotion_authorizer=authority,
    )
    binding_old_enforce = RuleRevisionBindingV2(
        binding_id="binding-aks-no-privileged",
        revision=rev_alpha_100,
        profile_snapshot_digest=identity_v100.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.ENFORCE,
        promotion_evidence_digest=_digest_for("promo:alpha:1.0.0"),
        binding_digest=rule_revision_binding_digest(
            binding_id="binding-aks-no-privileged",
            revision=rev_alpha_100,
            profile_snapshot_digest=identity_v100.profile_snapshot.snapshot_digest,
            mode=RuleBindingMode.ENFORCE,
            promotion_evidence_digest=_digest_for("promo:alpha:1.0.0"),
        ),
    )
    binding_new_shadow = RuleRevisionBindingV2(
        binding_id="binding-aks-no-privileged",
        revision=rev_alpha_110,
        profile_snapshot_digest=identity_v110.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.SHADOW,
        promotion_evidence_digest=None,
        binding_digest=rule_revision_binding_digest(
            binding_id="binding-aks-no-privileged",
            revision=rev_alpha_110,
            profile_snapshot_digest=identity_v110.profile_snapshot.snapshot_digest,
            mode=RuleBindingMode.SHADOW,
            promotion_evidence_digest=None,
        ),
    )
    slot_fwd_values: dict[str, Any] = {
        "rule_id": rev_alpha_100.rule_id,
        "enforcing": binding_old_enforce,
        "prepared_shadow": binding_new_shadow,
        "cohort_prepare_digest": cohort_v110.prepare_digest,
        "acknowledgement_set_digest": ack_set_v110,
        "created_at": migration_now + timedelta(seconds=16),
    }
    slot_fwd = RuleDualRevisionSlotV2(
        **slot_fwd_values,
        slot_digest=rule_dual_revision_slot_digest(**slot_fwd_values),
    )
    await slot_ledger.retain_slot(slot_fwd)
    evidence_fwd = await slot_ledger.build_evaluation_evidence(
        slot_digest=slot_fwd.slot_digest,
        mode=RuleBindingMode.SHADOW,
        evaluation_receipt_digest=_digest_for("scenarios:alpha:1.1.0"),
    )
    promo_fwd_receipt = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-revision-promote",
        evidence_digest=evidence_fwd.evaluation_receipt_digest,
        idempotency_key=slot_fwd.slot_digest,
        scenario_set_version=rev_alpha_110.rule_version,
        request_fingerprint=rev_alpha_110.revision_digest,
        approved_at=migration_now + timedelta(seconds=18),
        head_committed_at=migration_now,
        nonce="attest-promote-fwd-2204",
    )
    promo_fwd_values: dict[str, Any] = {
        "slot_digest": slot_fwd.slot_digest,
        "from_binding_digest": slot_fwd.enforcing.binding_digest,
        "shadow_binding_digest": slot_fwd.prepared_shadow.binding_digest,
        "revision_evidence_digest": evidence_fwd.evaluation_receipt_digest,
        "authority_receipt_digest": promo_fwd_receipt,
        "approval_profile_digest": profile.policy_digest,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=18),
    }
    promo_fwd_approval = RuleRevisionPromotionApprovalV2(
        **promo_fwd_values,
        approval_digest=rule_revision_promotion_approval_digest(**promo_fwd_values),
    )
    move_fwd = await slot_ledger.build_and_retain_move_candidate(
        slot_digest=slot_fwd.slot_digest,
        approval=promo_fwd_approval,
        commanded_at=migration_now + timedelta(seconds=19),
    )

    retention_ledger = StateStoreRuleRevisionRetention(
        store=active_store,
        authorizer=authority,
        registry=_RegistryReader(
            retained={
                (item.rule_id, item.rule_version, item.revision_digest)
                for item in catalog_revisions
            }
        ),
    )
    revision_change_ledger = StateStoreRuleRevisionChanges(
        store=active_store,
        identity_ledger=identity_ledger,
        cohort_ledger=cohort_ledger,
        slot_ledger=slot_ledger,
        authorizer=authority,
        rollback_eligibility=retention_ledger,
    )
    transition_fwd = build_rule_activation_identity_transition_v2(
        source=identity_v100,
        target=identity_v110,
    )
    change_fwd_prop_values: dict[str, Any] = {
        "source_authority_pointer_digest": upgraded_pointer.pointer_digest,
        "identity_transition": transition_fwd,
        "transition_kind": RuleRevisionTransitionKind.REVISION_CHANGE,
        "rollback_eligibility_digest": None,
        "rollback_eligible_until": migration_now + timedelta(days=7),
        "rule_id": rev_alpha_100.rule_id,
        "binding_id": "binding-aks-no-privileged",
        "from_revision": rev_alpha_100,
        "to_revision": rev_alpha_110,
        "slot_digest": slot_fwd.slot_digest,
        "binding_move_command_digest": move_fwd.command_digest,
        "signed_manifest_digest": manifest_v110.manifest_digest,
        "release_id": "release-1.1.2",
        "revision_registry_root": registry_root_catalog,
        "cohort_prepare_digest": cohort_v110.prepare_digest,
        "reviewed_source_revision": REVIEWED_SOURCE_REVISION,
        "proposed_by": PROPOSER_OID,
        "proposed_at": migration_now + timedelta(seconds=20),
    }
    change_fwd_proposal = RuleRevisionChangeProposalV2(
        **change_fwd_prop_values,
        proposal_digest=rule_revision_change_proposal_digest(**change_fwd_prop_values),
    )
    change_fwd_receipt = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-revision-change",
        evidence_digest=change_fwd_proposal.proposal_digest,
        idempotency_key=change_fwd_proposal.proposal_digest,
        scenario_set_version=identity_v110.profile_snapshot.profile_version,
        request_fingerprint=identity_v110.generation.generation_digest,
        approved_at=migration_now + timedelta(seconds=21),
        head_committed_at=migration_now,
        nonce="attest-change-fwd-2204",
    )
    change_fwd_app_values: dict[str, Any] = {
        "proposal_digest": change_fwd_proposal.proposal_digest,
        "authority_receipt_digest": change_fwd_receipt,
        "approval_profile_digest": profile.policy_digest,
        "requester_id": PROPOSER_OID,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=21),
    }
    change_fwd_approval = RuleRevisionChangeApprovalV2(
        **change_fwd_app_values,
        approval_digest=rule_revision_change_approval_digest(**change_fwd_app_values),
    )
    change_fwd_cmd_values: dict[str, Any] = {
        "proposal": change_fwd_proposal,
        "approval": change_fwd_approval,
        "commanded_at": migration_now + timedelta(seconds=22),
    }
    change_fwd_cmd = RuleRevisionChangeCommandV2(
        **change_fwd_cmd_values,
        command_digest=rule_revision_change_command_digest(**change_fwd_cmd_values),
    )
    fwd_pointer, fwd_binding = await revision_change_ledger.apply(change_fwd_cmd)
    _require(fwd_pointer.revision == 2)
    _require(fwd_binding.enforcing.revision == rev_alpha_110)

    # Phase 9: Verify rollback_eligible reference blocks premature retirement, then Rollback
    snap_old_during_fwd = await retention_ledger.snapshot(
        rev_alpha_100,
        captured_at=migration_now + timedelta(seconds=23),
    )
    ref_kinds = {item.kind for item in snap_old_during_fwd.references}
    _require(RuleRevisionReferenceKind.ROLLBACK_ELIGIBLE in ref_kinds)
    rollback_ref = next(
        item
        for item in snap_old_during_fwd.references
        if item.kind is RuleRevisionReferenceKind.ROLLBACK_ELIGIBLE
    )

    identity_v120_rb = build_rule_activation_identity_context_v2(
        catalog_revisions=catalog_revisions,
        profile_id="default",
        profile_version="1.2.0",
        active_members=upgrade_members,
    )
    manifest_v120_rb = await _verify_and_reserve_manifest(
        verifier=manifest_verifier,
        private_key=signing_key,
        identity_ctx=identity_v120_rb,
        release_id="release-1.1.1-rb",
        revision_registry_root=registry_root_catalog,
        nonce="3" * 64,
        now=migration_now + timedelta(seconds=24),
    )
    cohort_v120_rb, _, _, ack_set_v120_rb = await _prepare_and_apply_two_replica_cohort(
        cohort_ledger=cohort_ledger,
        identity_ctx=identity_v120_rb,
        release_id="release-1.1.1-rb",
        revision_registry_root=registry_root_catalog,
        predecessor_cohort=cohort_v110,
        expected_prepare_revision=2,
        expected_candidate_revision=6,
        base_time=migration_now + timedelta(seconds=25),
    )
    binding_rb_shadow = RuleRevisionBindingV2(
        binding_id="binding-aks-no-privileged",
        revision=rev_alpha_100,
        profile_snapshot_digest=identity_v120_rb.profile_snapshot.snapshot_digest,
        mode=RuleBindingMode.SHADOW,
        promotion_evidence_digest=None,
        binding_digest=rule_revision_binding_digest(
            binding_id="binding-aks-no-privileged",
            revision=rev_alpha_100,
            profile_snapshot_digest=identity_v120_rb.profile_snapshot.snapshot_digest,
            mode=RuleBindingMode.SHADOW,
            promotion_evidence_digest=None,
        ),
    )
    slot_rb_values: dict[str, Any] = {
        "rule_id": rev_alpha_100.rule_id,
        "enforcing": fwd_binding.enforcing,
        "prepared_shadow": binding_rb_shadow,
        "cohort_prepare_digest": cohort_v120_rb.prepare_digest,
        "acknowledgement_set_digest": ack_set_v120_rb,
        "created_at": migration_now + timedelta(seconds=26),
    }
    slot_rb = RuleDualRevisionSlotV2(
        **slot_rb_values,
        slot_digest=rule_dual_revision_slot_digest(**slot_rb_values),
    )
    await slot_ledger.retain_slot(slot_rb)
    evidence_rb = await slot_ledger.build_evaluation_evidence(
        slot_digest=slot_rb.slot_digest,
        mode=RuleBindingMode.SHADOW,
        evaluation_receipt_digest=_digest_for("scenarios:alpha:1.0.0:rb"),
    )
    promo_rb_receipt = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-revision-promote",
        evidence_digest=evidence_rb.evaluation_receipt_digest,
        idempotency_key=slot_rb.slot_digest,
        scenario_set_version=rev_alpha_100.rule_version,
        request_fingerprint=rev_alpha_100.revision_digest,
        approved_at=migration_now + timedelta(seconds=27),
        head_committed_at=migration_now,
        nonce="attest-promote-rb-2204",
    )
    promo_rb_values: dict[str, Any] = {
        "slot_digest": slot_rb.slot_digest,
        "from_binding_digest": slot_rb.enforcing.binding_digest,
        "shadow_binding_digest": slot_rb.prepared_shadow.binding_digest,
        "revision_evidence_digest": evidence_rb.evaluation_receipt_digest,
        "authority_receipt_digest": promo_rb_receipt,
        "approval_profile_digest": profile.policy_digest,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=27),
    }
    promo_rb_approval = RuleRevisionPromotionApprovalV2(
        **promo_rb_values,
        approval_digest=rule_revision_promotion_approval_digest(**promo_rb_values),
    )
    move_rb = await slot_ledger.build_and_retain_move_candidate(
        slot_digest=slot_rb.slot_digest,
        approval=promo_rb_approval,
        commanded_at=migration_now + timedelta(seconds=28),
    )
    transition_rb = build_rule_activation_identity_transition_v2(
        source=identity_v110,
        target=identity_v120_rb,
    )
    change_rb_prop_values: dict[str, Any] = {
        "source_authority_pointer_digest": fwd_pointer.pointer_digest,
        "identity_transition": transition_rb,
        "transition_kind": RuleRevisionTransitionKind.ROLLBACK,
        "rollback_eligibility_digest": rollback_ref.owner_digest,
        "rollback_eligible_until": migration_now + timedelta(days=14),
        "rule_id": rev_alpha_100.rule_id,
        "binding_id": "binding-aks-no-privileged",
        "from_revision": rev_alpha_110,
        "to_revision": rev_alpha_100,
        "slot_digest": slot_rb.slot_digest,
        "binding_move_command_digest": move_rb.command_digest,
        "signed_manifest_digest": manifest_v120_rb.manifest_digest,
        "release_id": "release-1.1.1-rb",
        "revision_registry_root": registry_root_catalog,
        "cohort_prepare_digest": cohort_v120_rb.prepare_digest,
        "reviewed_source_revision": REVIEWED_SOURCE_REVISION,
        "proposed_by": PROPOSER_OID,
        "proposed_at": migration_now + timedelta(seconds=28),
    }
    change_rb_proposal = RuleRevisionChangeProposalV2(
        **change_rb_prop_values,
        proposal_digest=rule_revision_change_proposal_digest(**change_rb_prop_values),
    )
    change_rb_receipt = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-revision-rollback",
        evidence_digest=change_rb_proposal.proposal_digest,
        idempotency_key=change_rb_proposal.proposal_digest,
        scenario_set_version=identity_v120_rb.profile_snapshot.profile_version,
        request_fingerprint=identity_v120_rb.generation.generation_digest,
        approved_at=migration_now + timedelta(seconds=29),
        head_committed_at=migration_now,
        nonce="attest-change-rb-2204",
    )
    change_rb_app_values: dict[str, Any] = {
        "proposal_digest": change_rb_proposal.proposal_digest,
        "authority_receipt_digest": change_rb_receipt,
        "approval_profile_digest": profile.policy_digest,
        "requester_id": PROPOSER_OID,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=29),
    }
    change_rb_approval = RuleRevisionChangeApprovalV2(
        **change_rb_app_values,
        approval_digest=rule_revision_change_approval_digest(**change_rb_app_values),
    )
    change_rb_cmd_values: dict[str, Any] = {
        "proposal": change_rb_proposal,
        "approval": change_rb_approval,
        "commanded_at": migration_now + timedelta(seconds=29),
    }
    change_rb_cmd = RuleRevisionChangeCommandV2(
        **change_rb_cmd_values,
        command_digest=rule_revision_change_command_digest(**change_rb_cmd_values),
    )
    rb_pointer, rb_binding = await revision_change_ledger.apply(change_rb_cmd)
    _require(rb_pointer.revision == 3)
    _require(rb_binding.enforcing.revision == rev_alpha_100)

    # Retire the unreferenced revision via retention-epoch CAS
    snap_retired = await retention_ledger.snapshot(
        rev_retired_100,
        captured_at=migration_now + timedelta(seconds=29),
    )
    _require(snap_retired.references == ())
    retire_prop_values: dict[str, Any] = {
        "snapshot": snap_retired,
        "reviewed_source_revision": REVIEWED_SOURCE_REVISION,
        "requested_by": PROPOSER_OID,
        "requested_at": migration_now + timedelta(seconds=29),
        "reason": "Retire unreferenced deprecated storage HTTP revision.",
    }
    retire_proposal = RuleRevisionRetirementProposalV2(
        **retire_prop_values,
        proposal_digest=rule_revision_retirement_proposal_digest(**retire_prop_values),
    )
    retire_receipt_digest = await _retain_attestation(
        active_store,
        profile=profile,
        action_type_id="rule-revision-retire",
        evidence_digest=retire_proposal.proposal_digest,
        idempotency_key=retire_proposal.proposal_digest,
        scenario_set_version=rev_retired_100.rule_version,
        request_fingerprint=rev_retired_100.revision_digest,
        approved_at=migration_now + timedelta(seconds=29),
        head_committed_at=migration_now,
        nonce="attest-retire-2204",
        change_class=GovernanceChangeClass.RULE_RETIREMENT,
    )
    retire_app_values: dict[str, Any] = {
        "proposal_digest": retire_proposal.proposal_digest,
        "authority_receipt_digest": retire_receipt_digest,
        "approval_profile_digest": profile.policy_digest,
        "requester_id": PROPOSER_OID,
        "approver_ids": (OWNER_OID,),
        "original_quorum": 2,
        "effective_quorum": 1,
        "approved_at": migration_now + timedelta(seconds=29),
    }
    retire_approval = RuleRevisionRetirementApprovalV2(
        **retire_app_values,
        approval_digest=rule_revision_retirement_approval_digest(**retire_app_values),
    )
    retire_cmd_values: dict[str, Any] = {
        "proposal": retire_proposal,
        "approval": retire_approval,
        "commanded_at": migration_now + timedelta(seconds=29),
    }
    retire_command = RuleRevisionRetirementCommandV2(
        **retire_cmd_values,
        command_digest=rule_revision_retirement_command_digest(**retire_cmd_values),
    )
    retirement_receipt = await retention_ledger.retire(retire_command)
    _require(await retention_ledger.retire(retire_command) == retirement_receipt)
    _require(await active_store.verify_chain() is True)

    # Criteria 5 & 6: Profile-correct governance review without GitHub App (denied -> cleared)
    roles = frozenset({Role.OWNER, Role.APPROVER, Role.CONTRIBUTOR})
    denied_self = validate_governance_review(
        GovernanceReviewRequest(
            change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
            author=GovernancePrincipal(oid=OWNER_OID, roles=roles),
            head_revision=REVIEWED_SOURCE_REVISION,
            head_committed_at=CUTOFF,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(oid=OWNER_OID, roles=roles),
                    reviewed_revision=REVIEWED_SOURCE_REVISION,
                    approved_at=CUTOFF + timedelta(seconds=5),
                    phishing_resistant=True,
                ),
            ),
            approval_profile=None,
        )
    )
    _require(denied_self.allowed is False)
    _require("self_approval" in {issue.code for issue in denied_self.issues})

    denied_sub_quorum = validate_governance_review(
        GovernanceReviewRequest(
            change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
            author=GovernancePrincipal(oid=OWNER_OID, roles=roles),
            head_revision=REVIEWED_SOURCE_REVISION,
            head_committed_at=CUTOFF,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(oid=SECOND_APPROVER_OID, roles=roles),
                    reviewed_revision=REVIEWED_SOURCE_REVISION,
                    approved_at=CUTOFF + timedelta(seconds=5),
                    phishing_resistant=True,
                ),
            ),
            approval_profile=None,
        )
    )
    _require(denied_sub_quorum.allowed is False)
    _require("quorum_not_met" in {issue.code for issue in denied_sub_quorum.issues})

    cleared_review = validate_governance_review(
        GovernanceReviewRequest(
            change_class=GovernanceChangeClass.ENFORCE_PROMOTION,
            author=GovernancePrincipal(oid=OWNER_OID, roles=roles),
            head_revision=REVIEWED_SOURCE_REVISION,
            head_committed_at=CUTOFF,
            approvals=(
                GovernanceApproval(
                    approver=GovernancePrincipal(oid=OWNER_OID, roles=roles),
                    reviewed_revision=REVIEWED_SOURCE_REVISION,
                    approved_at=CUTOFF + timedelta(seconds=10),
                    phishing_resistant=True,
                ),
            ),
            approval_profile=profile,
        )
    )
    _require(cleared_review.allowed is True)
    _require(cleared_review.original_quorum == 2 and cleared_review.effective_quorum == 1)
    _require(cleared_review.self_review is True)
    _require(cleared_review.grants_execution_authority is False)

    # Criteria 9 & 10: Direct & offline activation + 2-replica convergence on restart/rollback
    channel_store = InMemoryStateStore()
    channel_ledger = StateStoreRuleActivationLedger(store=channel_store)
    _, offline_gen = await reconcile_rule_activation(
        ledger=channel_ledger,
        available_rules=(rule_alpha_v1, rule_beta_v1),
        profile_id="default",
        profile_version="1.0.0",
        source_ref="offline-bundle:release-1.1.1",
        source_digest=manifest_v100.manifest_digest.removeprefix("sha256:"),
        requested_by=OWNER_OID,
        approved_by=SECOND_APPROVER_OID,
        source=RuleActivationSource.OFFLINE_PACKAGE,
        clock=lambda: CUTOFF,
    )
    rt_1 = _ReplicaRuntime()
    rt_2 = _ReplicaRuntime()
    coord_1 = RuleActivationCoordinator(
        store=channel_store,
        ledger=channel_ledger,
        runtime=cast(Any, rt_1),
        available_rules=(rule_alpha_v1, rule_beta_v1),
    )
    coord_2 = RuleActivationCoordinator(
        store=channel_store,
        ledger=channel_ledger,
        runtime=cast(Any, rt_2),
        available_rules=(rule_alpha_v1, rule_beta_v1),
    )
    rec_1 = RuleActivationRuntimeReconciler(coordinator=coord_1, interval_seconds=1.0)
    rec_2 = RuleActivationRuntimeReconciler(coordinator=coord_2, interval_seconds=1.0)
    await rec_1.run_once()
    await rec_2.run_once()
    _require(rt_1.rule_generation_digest == offline_gen.generation_digest)
    _require(rt_2.rule_generation_digest == offline_gen.generation_digest)

    # Direct activation: first deny self-approval, then apply with distinct approval step
    direct_changes = (RuleActivationDelta(rule_id=rule_beta_v1.id, enabled=False),)
    direct_prop_digest = rule_activation_proposal_digest(
        idempotency_key="direct-2204-disable-beta",
        expected_generation_digest=offline_gen.generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:POST:/rules/activation-changes",
        source_digest=_hex_digest_for("direct-req:disable-beta"),
        requested_by=OWNER_OID,
        requested_at=CUTOFF + timedelta(minutes=1),
        reason="Disable beta rule for bounded maintenance rehearsal.",
        changes=direct_changes,
    )
    direct_proposal = RuleActivationProposal(
        request_id=f"rule-activation-request-{direct_prop_digest[:32]}",
        idempotency_key="direct-2204-disable-beta",
        expected_generation_digest=offline_gen.generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:POST:/rules/activation-changes",
        source_digest=_hex_digest_for("direct-req:disable-beta"),
        requested_by=OWNER_OID,
        requested_at=CUTOFF + timedelta(minutes=1),
        reason="Disable beta rule for bounded maintenance rehearsal.",
        changes=direct_changes,
    )
    direct_gen = build_rule_activation_generation(
        (rule_alpha_v1,),
        profile_id=offline_gen.profile_id,
        profile_version=offline_gen.profile_version,
        created_at=CUTOFF + timedelta(minutes=1, seconds=10),
        catalog_digest=offline_gen.catalog_digest,
    )
    try:
        RuleActivationCommand(
            proposal=direct_proposal,
            approval=RuleActivationApproval(
                proposal_digest=direct_proposal.proposal_digest,
                approver_ids=(OWNER_OID,),
                approved_at=CUTOFF + timedelta(minutes=1, seconds=5),
                approval_ref="direct-self-approval-denied",
            ),
            generation=direct_gen,
            commanded_at=CUTOFF + timedelta(minutes=1, seconds=5),
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("expected direct self-approval to be rejected")

    direct_result = await channel_ledger.apply(
        RuleActivationCommand(
            proposal=direct_proposal,
            approval=RuleActivationApproval(
                proposal_digest=direct_proposal.proposal_digest,
                approver_ids=(SECOND_APPROVER_OID,),
                approved_at=CUTOFF + timedelta(minutes=1, seconds=10),
                approval_ref="direct-distinct-approval-step",
            ),
            generation=direct_gen,
            commanded_at=CUTOFF + timedelta(minutes=1, seconds=10),
        )
    )
    _require(direct_result.status is RuleActivationStatus.APPLIED)
    await rec_1.run_once()
    await rec_2.run_once()
    # Simulate replica-2 restart and verify generation convergence
    restarted_rt_2 = _ReplicaRuntime()
    restarted_coord_2 = RuleActivationCoordinator(
        store=channel_store,
        ledger=channel_ledger,
        runtime=cast(Any, restarted_rt_2),
        available_rules=(rule_alpha_v1, rule_beta_v1),
    )
    await RuleActivationRuntimeReconciler(
        coordinator=restarted_coord_2,
        interval_seconds=1.0,
    ).run_once()
    _require(
        rt_1.rule_generation_digest
        == restarted_rt_2.rule_generation_digest
        == direct_result.resulting_generation_digest
    )

    # Direct rollback activation and verify both replicas converge back to full membership
    rb_changes = (RuleActivationDelta(rule_id=rule_beta_v1.id, enabled=True),)
    rb_prop_digest = rule_activation_proposal_digest(
        idempotency_key="direct-2204-rollback-beta",
        expected_generation_digest=direct_result.resulting_generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:POST:/rules/activation-changes:rollback",
        source_digest=_hex_digest_for("direct-req:rollback-beta"),
        requested_by=OWNER_OID,
        requested_at=CUTOFF + timedelta(minutes=2),
        reason="Roll back direct Rule activation change.",
        changes=rb_changes,
    )
    rb_direct_proposal = RuleActivationProposal(
        request_id=f"rule-activation-request-{rb_prop_digest[:32]}",
        idempotency_key="direct-2204-rollback-beta",
        expected_generation_digest=direct_result.resulting_generation_digest,
        source=RuleActivationSource.DIRECT,
        source_ref="operator-api:POST:/rules/activation-changes:rollback",
        source_digest=_hex_digest_for("direct-req:rollback-beta"),
        requested_by=OWNER_OID,
        requested_at=CUTOFF + timedelta(minutes=2),
        reason="Roll back direct Rule activation change.",
        changes=rb_changes,
    )
    rb_direct_result = await channel_ledger.apply(
        RuleActivationCommand(
            proposal=rb_direct_proposal,
            approval=RuleActivationApproval(
                proposal_digest=rb_direct_proposal.proposal_digest,
                approver_ids=(SECOND_APPROVER_OID,),
                approved_at=CUTOFF + timedelta(minutes=2, seconds=5),
                approval_ref="direct-rollback-approval",
            ),
            generation=offline_gen,
            commanded_at=CUTOFF + timedelta(minutes=2, seconds=5),
        )
    )
    await rec_1.run_once()
    await RuleActivationRuntimeReconciler(
        coordinator=restarted_coord_2,
        interval_seconds=1.0,
    ).run_once()
    _require(
        rt_1.rule_generation_digest
        == restarted_rt_2.rule_generation_digest
        == rb_direct_result.resulting_generation_digest
        == offline_gen.generation_digest
    )

    # Criterion 7: Scheduled exemption expiry, notification receipt, and duplicate suppression
    exemption_alert = Exemption(
        schema_version="1.0.0",
        id="exemption.aks.privileged-containers.dev",
        rule_id=rule_alpha_v1.id,
        scope=ExemptionScope(
            subscription_id=UUID("00000000-0000-0000-0000-000000000010"),
            resource_group="rg-aks",
            resource_ref="aks-cluster-1",
        ),
        justification="Temporary break-glass container debugging window.",
        requested_by=UUID("00000000-0000-0000-0000-000000000001"),
        approved_by=UUID("00000000-0000-0000-0000-000000000002"),
        state=ExemptionState.ACTIVE,
        created_at=CUTOFF - timedelta(days=10),
        expires_at=CUTOFF + timedelta(days=5),
    )
    exemption_due = Exemption(
        schema_version="1.0.0",
        id="exemption.postgresql.pitr.dev",
        rule_id=rule_beta_v1.id,
        scope=ExemptionScope(
            subscription_id=UUID("00000000-0000-0000-0000-000000000010"),
            resource_group="rg-db",
            resource_ref="pg-server-1",
        ),
        justification="Short migration window completed for PostgreSQL PITR.",
        requested_by=UUID("00000000-0000-0000-0000-000000000001"),
        approved_by=UUID("00000000-0000-0000-0000-000000000002"),
        state=ExemptionState.ACTIVE,
        created_at=CUTOFF - timedelta(days=20),
        expires_at=CUTOFF - timedelta(hours=1),
    )
    notifier = _DigestNotifier()
    expiry_bus = _InMemoryEventBus()
    expiry_coordinator = ExemptionLifecycleCoordinator(
        exemptions=(exemption_alert, exemption_due),
        notifier=notifier,
        audit_store=active_store,
        alert_lead_days=14,
        assignment_bindings={
            exemption_due.id: ExemptionAssignmentBinding(
                assignment_id="assign.postgresql.pitr",
                assignment_version="1.0.0",
                scope_ref="scope://org/00000000-0000-0000-0000-000000000010/rg-db/pg-server-1",
            )
        },
        command_publisher=EventBusExemptionExpiryCommandPublisher(
            event_bus=cast(Any, expiry_bus),
            topic="object.event",
        ),
        clock=lambda: CUTOFF,
    )
    first_sweep = await expiry_coordinator.run_once()
    second_sweep = await expiry_coordinator.run_once()
    _require(first_sweep.evaluated == 2 and first_sweep.alerted == 1)
    _require(first_sweep.expired_due == 1 and first_sweep.commands_published == 1)
    _require(second_sweep.evaluated == 2 and second_sweep.alerted == 0)
    _require(second_sweep.expired_due == 0 and second_sweep.commands_published == 0)
    _require(len(notifier.delivered) == 1)

    # Criterion 8: Bind governance.override_resolved source with exact window & Mimir admission
    cycle_interval_seconds = 15 * 86400
    cycle_start = interval_bucket_start(CUTOFF - timedelta(days=1), cycle_interval_seconds)
    for idx, day_offset in enumerate((0, 3, 7, 11, 14)):
        await active_store.append_audit_entry(
            {
                "action_kind": "governance.override_resolved",
                "actor": "fdai.core.control_loop",
                "producer_principal": "Mimir",
                "event_id": f"evt-ovr-2204-{idx}",
                "idempotency_key": f"idem-ovr-2204-{idx}",
                "rule_id": rule_beta_v1.id,
                "resource_id": f"postgresql.server/rg-{idx % 3}/db-{idx}",
                "override_id": f"override.pitr.rg-{idx % 3}",
                "override_scope": f"scope://org/sub-dev/rg-{idx % 3}",
                "override_mode": "parameter-relaxation",
                "recorded_at": (cycle_start + timedelta(days=day_offset, hours=1)).isoformat(),
            }
        )
    override_source = bind_override_discovery_source(
        active_store,
        thresholds=OverrideSignalThresholds(
            min_distinct_scopes=3,
            min_dwell_days=14,
            min_shadow_hits=5,
        ),
    )
    scheduler = DiscoveryCycleScheduler(
        state_store=active_store,
        source=override_source,
        primary_model=_DiscoveryPrimaryModel(),
        cross_check_models=(_DiscoveryReviewerModel(),),
        verifier=_DiscoveryVerifier(),
        integrator=_DiscoveryIntegrator(),
        config=DiscoveryCycleConfig(
            schedule_id="f062-override-discovery-2204",
            interval_seconds=cycle_interval_seconds,
            timeout_seconds=10.0,
            max_signals=32,
            max_candidates=8,
            retain_cycles=4,
        ),
        clock=lambda: CUTOFF,
    )
    cycle_report = await scheduler.run_due(scheduled_for=cycle_start + timedelta(hours=2))
    _require(cycle_report.status == "completed")
    _require(cycle_report.signal_count == 1)
    _require(
        len(cycle_report.decisions) == 1
        and cycle_report.decisions[0].state is DiscoveryCandidateState.INTEGRATED
    )
    cycle_metrics = cycle_report.metrics
    if cycle_metrics is None or cycle_metrics.override_trigger_rate != 1.0:
        raise RuntimeError("expected override_trigger_rate == 1.0")

    # verify independent source admission rejects Norns self-authored record on a probe store
    probe_store = InMemoryStateStore()
    await probe_store.append_audit_entry(
        {
            "action_kind": "governance.override_resolved",
            "actor": "fdai.core.control_loop",
            "producer_principal": "Norns",
            "event_id": "evt-forged",
            "idempotency_key": "idem-forged",
            "rule_id": rule_beta_v1.id,
            "override_id": "ovr-forged",
            "override_scope": "scope://org/sub-dev/rg-0",
            "override_mode": "disabled",
            "recorded_at": (cycle_start + timedelta(hours=1)).isoformat(),
        }
    )
    probe_reader = StateStoreOverrideAuditReader(probe_store)
    try:
        await probe_reader.list_override_resolutions(
            window_start=cycle_start,
            window_end=cycle_start + timedelta(days=1),
            limit=10,
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("expected self-produced Norns override record to be rejected")

    # Criterion 12: Explicit hold matrix for every non-available/invalid source state
    hold_observations = [
        SourceObservation(
            "s-unavailable",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.UNAVAILABLE,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:unavailable"),
        ),
        SourceObservation(
            "s-stale",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.AVAILABLE,
            CUTOFF - timedelta(hours=3),
            _digest_for("hold:stale"),
        ),
        SourceObservation(
            "s-incomplete",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.INCOMPLETE,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:incomplete"),
        ),
        SourceObservation(
            "s-revoked",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.REVOKED,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:revoked"),
        ),
        SourceObservation(
            "s-conflicting",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.CONFLICTING,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:conflicting"),
        ),
        SourceObservation(
            "s-post-cutoff",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.AVAILABLE,
            CUTOFF + timedelta(minutes=1),
            _digest_for("hold:post-cutoff"),
        ),
        SourceObservation(
            "s-dup-conflict",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.AVAILABLE,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:dup-1"),
        ),
        SourceObservation(
            "s-dup-conflict",
            MANAGEMENT_SCOPE_ID,
            "id-1",
            SourceState.AVAILABLE,
            CUTOFF - timedelta(minutes=5),
            _digest_for("hold:dup-2"),
        ),
    ]
    held_reconciliation = reconcile_sources(
        hold_observations,
        required_source_ids=[
            "s-unavailable",
            "s-stale",
            "s-incomplete",
            "s-revoked",
            "s-conflicting",
            "s-post-cutoff",
            "s-dup-conflict",
            "s-missing",
        ],
        evidence_cutoff=CUTOFF,
        max_age=timedelta(hours=1),
    )
    _require(not held_reconciliation.complete)
    _require(
        {hold.reason for hold in held_reconciliation.holds}
        == {
            HoldReason.UNAVAILABLE,
            HoldReason.STALE,
            HoldReason.INCOMPLETE,
            HoldReason.REVOKED,
            HoldReason.CONFLICTING,
            HoldReason.OBSERVED_AFTER_CUTOFF,
            HoldReason.DUPLICATE_CONFLICT,
            HoldReason.MISSING_REQUIRED,
        }
    )
    blocked_record = build_qualification_record(binding, held_reconciliation, None)
    _require(blocked_record.readiness is Readiness.BLOCKED)

    # Criterion 4: Complete drift and control-gap provider collection
    admitted_observations = [
        SourceObservation(
            source_id=source_id,
            scope_id=MANAGEMENT_SCOPE_ID,
            identity_ref=f"uami-observer-{source_id}",
            state=SourceState.AVAILABLE,
            observed_at=CUTOFF - timedelta(minutes=5),
            evidence_digest=_digest_for(f"provider-obs:{source_id}:{revision}"),
        )
        for source_id, revision in sorted(PROVIDER_REVISIONS.items())
    ]
    complete_sources = reconcile_sources(
        admitted_observations,
        required_source_ids=tuple(sorted(PROVIDER_REVISIONS)),
        evidence_cutoff=CUTOFF,
        max_age=timedelta(hours=1),
    )
    _require(complete_sources.complete is True and complete_sources.holds == ())

    # Criterion 11: Frozen-denominator cohort measurement
    cohort_cases = [
        *(
            CohortCase(
                case_id=f"violation-{idx:02d}",
                group_id=f"rg-violation-{idx:02d}",
                truth=GroundTruth.VIOLATION,
                verdict=Verdict.FLAGGED,
            )
            for idx in range(1, 13)
        ),
        *(
            CohortCase(
                case_id=f"compliant-{idx:02d}",
                group_id=f"rg-compliant-{idx:02d}",
                truth=GroundTruth.COMPLIANT,
                verdict=Verdict.NOT_FLAGGED,
            )
            for idx in range(1, 13)
        ),
    ]
    frozen = freeze_cohort(cohort_cases)
    measurement = measure_cohort(frozen, expected_digest=frozen.digest)
    _require(measurement.total == 24 and measurement.independent_groups == 24)
    coverage_rate = measurement.coverage
    fp_rate = measurement.false_positive_rate
    fn_rate = measurement.false_negative_rate
    fn_worst_rate = measurement.false_negative_rate_worst_case
    if (
        coverage_rate is None
        or fp_rate is None
        or fn_rate is None
        or fn_worst_rate is None
        or coverage_rate.value != 1.0
        or fp_rate.value != 0.0
        or fn_rate.value != 0.0
        or fn_worst_rate.value != 0.0
    ):
        raise RuntimeError("unexpected frozen cohort rates")

    # Criterion 13: Reconcile F06.2 readiness record and implementation ledger with exact digests
    record = build_qualification_record(binding, complete_sources, measurement)
    _require(record.readiness is Readiness.READY_FOR_REVIEW)
    _require(record.blocking_reasons == ())
    _require(record.authority == "none")
    missing_digests = reconcile_ledger_digests(
        record,
        {
            record.record_digest,
            record.sources_digest,
            measurement.digest,
        },
    )
    _require(missing_digests == ())

    return {
        "schema_version": "fdai.f062-governance-rollout-receipt.v1",
        "issue": 2204,
        "authority": "none",
        "criterion_1_binding": {
            "installation_id": binding.installation_id,
            "management_scope_id": binding.management_scope_id,
            "environment_class": binding.environment_class,
            "rule_generation_digest": binding.rule_generation_digest,
            "ontology_release_digest": binding.ontology_release_digest,
            "provider_count": len(binding.provider_revisions),
            "evidence_cutoff": binding.evidence_cutoff.isoformat(),
        },
        "criterion_2_3_nine_phase_migration": {
            "seeded_legacy_generation_id": seeded_legacy_gen.generation_id,
            "seeded_legacy_generation_digest": seeded_legacy_gen.generation_digest,
            "upgrade_release_id": upgraded_pointer.release_id,
            "upgrade_pointer_digest": upgraded_pointer.pointer_digest,
            "forward_release_id": fwd_pointer.release_id,
            "forward_pointer_digest": fwd_pointer.pointer_digest,
            "forward_binding_digest": fwd_binding.pointer_digest,
            "rollback_release_id": rb_pointer.release_id,
            "rollback_pointer_digest": rb_pointer.pointer_digest,
            "rollback_binding_digest": rb_binding.pointer_digest,
            "retirement_receipt_digest": retirement_receipt.receipt_digest,
            "audit_chain_verified": True,
        },
        "criterion_4_provider_collection": {
            "admitted_count": len(complete_sources.admitted),
            "holds_count": len(complete_sources.holds),
            "sources_digest": complete_sources.digest,
        },
        "criterion_5_6_governance_review": {
            "self_approval_denied_codes": [issue.code for issue in denied_self.issues],
            "sub_quorum_denied_codes": [issue.code for issue in denied_sub_quorum.issues],
            "cleared_allowed": cleared_review.allowed,
            "cleared_original_quorum": cleared_review.original_quorum,
            "cleared_effective_quorum": cleared_review.effective_quorum,
            "cleared_self_review": cleared_review.self_review,
            "approval_profile_digest": profile.policy_digest,
        },
        "criterion_7_exemption_expiry": {
            "linked_live_audit_id": LINKED_LIVE_EXPIRY_AUDIT_ID,
            "linked_live_exemption_revision": LINKED_LIVE_EXPIRY_REVISION,
            "rehearsal_digest_audit_id": notifier.delivered[0],
            "first_sweep": {
                "evaluated": first_sweep.evaluated,
                "alerted": first_sweep.alerted,
                "expired_due": first_sweep.expired_due,
                "commands_published": first_sweep.commands_published,
            },
            "second_sweep": {
                "evaluated": second_sweep.evaluated,
                "alerted": second_sweep.alerted,
                "expired_due": second_sweep.expired_due,
                "commands_published": second_sweep.commands_published,
            },
        },
        "criterion_8_override_discovery": {
            "cycle_id": cycle_report.cycle_id,
            "signal_count": cycle_report.signal_count,
            "integrated_count": len(cycle_report.decisions),
            "override_trigger_rate": cycle_metrics.override_trigger_rate,
            "norns_self_admission_rejected": True,
        },
        "criterion_9_10_activation_and_convergence": {
            "offline_generation_digest": offline_gen.generation_digest,
            "direct_generation_digest": direct_result.resulting_generation_digest,
            "rollback_generation_digest": rb_direct_result.resulting_generation_digest,
            "replica_convergence_verified": True,
        },
        "criterion_11_frozen_cohort": {
            "cohort_digest": frozen.digest,
            "measurement_digest": measurement.digest,
            "total": measurement.total,
            "independent_groups": measurement.independent_groups,
            "coverage": coverage_rate.value,
            "false_positive_rate": fp_rate.value,
            "false_negative_rate": fn_rate.value,
            "false_negative_rate_worst_case": fn_worst_rate.value,
        },
        "criterion_12_explicit_holds": {
            "verified_hold_reasons": sorted(
                hold.reason.value for hold in held_reconciliation.holds
            ),
            "blocked_readiness": blocked_record.readiness.value,
        },
        "criterion_13_qualification_record": {
            "readiness": record.readiness.value,
            "record_digest": record.record_digest,
            "sources_digest": record.sources_digest,
            "measurement_digest": record.measurement_digest,
            "ledger_missing_digests": list(missing_digests),
        },
    }


async def _run_with_optional_postgres(*, use_postgres: bool) -> dict[str, Any]:
    if not use_postgres:
        return await run_f062_qualification_rehearsal()
    from uuid import uuid4

    import psycopg
    from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
    from fdai.delivery.persistence.postgres_rule_activation_cohort import (
        PostgresRuleActivationCohortCommitStore,
    )
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    raw_dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not raw_dsn:
        raise RuntimeError("FDAI_DATABASE_URL is required when --postgres is selected")
    base_dsn = raw_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    conn_info = conninfo_to_dict(base_dsn)
    if (
        conn_info.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or str(conn_info.get("port", "5432")) == "5432"
    ):
        raise RuntimeError("F06.2 PostgreSQL rehearsal requires the loopback validation cluster")
    schema = f"f062_rehearsal_{uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(base_dsn, connect_timeout=5) as conn:
        await conn.execute("SET statement_timeout = '15s'")
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("audit_log", "state_kv"):
            await conn.execute(
                sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                    sql.Identifier(table),
                )
            )
    try:
        scoped_dsn = make_conninfo(base_dsn, options=f"-c search_path={schema}")
        config = PostgresStateStoreConfig(dsn=scoped_dsn)
        pg_store = PostgresStateStore(config=config)
        pg_commit = PostgresRuleActivationCohortCommitStore(config=config)
        try:
            return await run_f062_qualification_rehearsal(
                store=pg_store,
                commit_store=pg_commit,
                migration_now=datetime.now(tz=UTC) - timedelta(minutes=1),
            )
        finally:
            await pg_store.aclose()
    finally:
        async with await psycopg.AsyncConnection.connect(
            base_dsn,
            connect_timeout=5,
        ) as conn:
            await conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true", help="run against FDAI_DATABASE_URL")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    summary = asyncio.run(_run_with_optional_postgres(use_postgres=args.postgres))
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
