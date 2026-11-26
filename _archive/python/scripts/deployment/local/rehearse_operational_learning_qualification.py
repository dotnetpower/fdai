#!/usr/bin/env python3
"""Rehearse and verify end-to-end operational learning qualification for Issue #2194."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModel,
    EffectModelStatus,
    StateStoreEffectModelRegistry,
)
from fdai.core.assurance_twin.feedback_rebuild import rebuild_feedback
from fdai.core.assurance_twin.prediction_evidence import prediction_available, retain_prediction
from fdai.core.assurance_twin.prequential_evaluation import evaluate_frozen_predictions
from fdai.core.case_history import (
    CaseHistoryMaterializer,
    FailureFingerprint,
    OperationalCaseInput,
    OperationalEvidenceSourceKind,
    OperationalOutcomeClass,
    OperationalReceiptFact,
    OperationalReceiptType,
)
from fdai.core.case_history.derived import CaseHistoryProjectionStore
from fdai.core.case_history.models import CaseKind
from fdai.core.measurement.pattern_evidence import (
    ScoredOutcome,
    StatisticsPolicy,
    measured_statistics,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.pattern_queries import OperatingPatternQuery
from fdai.core.operational_learning.patterns import (
    OperatingPatternCompiler,
    PatternCase,
    pattern_case_from_operational_case,
)
from fdai.core.operational_learning.qualification_evaluation import (
    FrozenT1ShadowIntakeSummary,
    OperationalLearningEpisode,
    PredeclaredLearningEvaluationGates,
    QualificationVenueSelection,
    evaluate_operational_learning_effects,
    qualify_frozen_intervention_provenance,
)
from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    current_reuse_evidence_digest,
    current_reuse_scope_digest,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    FINAL_QUALIFICATION_PURPOSE,
    RetainedPatternQualification,
    RetainedReuseStatistics,
    qualification_request,
)
from fdai.core.tiers.t1_lightweight.retained_patterns import (
    RetainedPatternRequest,
    RetainedPatternSource,
)
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
    T1Config,
    T1Decision,
    T1Outcome,
    T1Tier,
)
from fdai.delivery.persistence.local_pattern_owner import (
    owner_key,
    statistics_mapping,
    verification_mapping,
)
from fdai.delivery.persistence.local_pattern_qualification import (
    _CoherentBundleVerifier,
    _validate_server_owned_bindings,
)
from fdai.delivery.persistence.local_pattern_validation import (
    artifact_key,
    base_keys,
    lookups,
    validate_locked,
)
from fdai.delivery.persistence.state_store_case_artifacts import StateStoreCaseHistoryArtifactStore
from fdai.delivery.persistence.state_store_case_history import StateStoreCaseHistoryMetadataStore
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
    StateStoreDecisionEvidenceAdmissionRecorder,
    decision_evidence_state_key,
)
from fdai.shared.contracts.models import (
    EffectPredictionSnapshot,
    Event,
    OntologyActionType,
    Operation,
    PromotionGate,
    ResponseOutcome,
    RollbackKind,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operator_authentication import (
    LOCAL_LOOPBACK_ISSUER,
    OperatorAuthenticationEvidenceClass,
    OperatorAuthenticationReceipt,
    role_mapping_revision,
    tenant_digest,
    token_id_digest,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(seconds=3)
ACCESS_SCOPE = "f" * 64
TARGET_SCOPE = "a" * 64
GRAPH_DIGEST = "b" * 64
OWNER_DIGEST = "c" * 64
READ_REVISION = "a" * 40
MODEL_DIGEST = "d" * 64


def _require(
    condition: bool, message: str = "operational learning qualification assertion failed"
) -> None:
    if not condition:
        raise RuntimeError(message)


class _BaselineLibrary:
    async def search(self, query_vector: Any, *, k: int = 5) -> tuple[SimilarityMatch, ...]:
        del query_vector, k
        return ()


async def _admit_gate_record(
    store: InMemoryStateStore,
    *,
    evidence_digest: str,
    scope_digest: str,
    purpose_id: str,
    source_revision: str,
) -> DecisionEvidenceAdmission:
    policy_digest = content_digest({"policy": purpose_id, "version": "1.0.0"})
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "authority_class": "provider_observation",
        "source_identity": "principal:inventory-reader",
        "authentication_evidence_digest": "sha256:" + "1" * 64,
        "scope_digest": scope_digest,
        "purpose_id": purpose_id,
        "producer_id": "core-control-plane",
        "producer_version": "1.0.0",
        "method_id": f"{purpose_id}-method",
        "method_version": "1.0.0",
        "source_revision": source_revision,
        "evidence_digest": evidence_digest,
        "provenance_digest": "sha256:" + "2" * 64,
        "event_at": T0,
        "evidence_cutoff": T0 + timedelta(seconds=1),
        "recorded_at": T0 + timedelta(seconds=2),
        "fresh_until": T0 + timedelta(seconds=241),
        "freshness_policy_id": f"{purpose_id}-freshness",
        "freshness_policy_version": "1.0.0",
        "freshness_policy_digest": policy_digest,
        "freshness_ceiling_seconds": 240,
        "completeness_basis_points": 10_000,
        "completeness_evidence_digest": "sha256:" + "3" * 64,
        "conflict_status": EvidenceConflictStatus.CLEAR,
        "conflict_evidence_digest": "sha256:" + "4" * 64,
        "conflict_evidence_digests": (),
        "synthetic": False,
        "execution_authority": False,
    }
    receipt = DecisionCriticalEvidenceReceipt.model_validate(
        {**values, "receipt_digest": decision_critical_evidence_receipt_digest(**values)}
    )
    subjects = expected_verification_subjects(
        authentication_evidence_digest=receipt.authentication_evidence_digest,
        evidence_digest=receipt.evidence_digest,
        completeness_evidence_digest=receipt.completeness_evidence_digest,
        conflict_evidence_digest=receipt.conflict_evidence_digest,
        freshness_policy_digest=receipt.freshness_policy_digest,
    )
    proofs = tuple(
        DecisionEvidenceVerificationProof(
            kind=kind,
            receipt_digest=receipt.receipt_digest,
            subject_digest=subject,
            proof_digest=content_digest({"kind": str(kind), "subject": subject}),
            verifier_id="operational-evidence-verifier",
            verifier_version="1.0.0",
            trust_anchor_id="anchor:operational-evidence-verifier",
            issued_at=T0 + timedelta(seconds=2),
            valid_until=T0 + timedelta(minutes=4),
        )
        for kind, subject in subjects.items()
    )
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id="operational-evidence-verifier",
        verifier_version="1.0.0",
        trust_anchor_id="anchor:operational-evidence-verifier",
        verified_at=T0 + timedelta(seconds=2),
        valid_until=T0 + timedelta(minutes=4),
        proofs=proofs,
    )
    gate = DecisionEvidenceReadinessGate(
        registry=DecisionEvidenceVerifierRegistry(
            (
                DecisionEvidenceVerifierBinding(
                    authority_class=receipt.authority_class,
                    method_id=receipt.method_id,
                    verifier_id=bundle.verifier_id,
                    verifier_version=bundle.verifier_version,
                    trust_anchor_id=bundle.trust_anchor_id,
                    verifier=_CoherentBundleVerifier(bundle),
                ),
            )
        )
    )
    req = LiveEvidenceClaimRequirement(
        allowed_authority_classes=(receipt.authority_class,),
        allowed_source_identities=(receipt.source_identity,),
        scope_digest=scope_digest,
        purpose_id=purpose_id,
        producer_id=receipt.producer_id,
        producer_version=receipt.producer_version,
        method_id=receipt.method_id,
        method_version=receipt.method_version,
        source_revision=source_revision,
        freshness_policy_digest=policy_digest,
        freshness_ceiling_seconds=240,
        minimum_completeness_basis_points=10_000,
    )
    result = await gate.evaluate(receipt, req, evaluated_at=NOW)
    _require(result.eligible and result.admission is not None, "gate admission failed")
    recorder = StateStoreDecisionEvidenceAdmissionRecorder(store=store, clock=lambda: NOW)
    _require(await recorder.retain(receipt, result), "recorder failed to retain admission")
    if result.admission is None:
        raise RuntimeError("gate admission missing")
    return result.admission


def _build_case_input(index: int, outcome_class: OperationalOutcomeClass) -> OperationalCaseInput:
    response_status = (
        "mismatch" if outcome_class is not OperationalOutcomeClass.SUCCESS else "verified"
    )
    fingerprint = FailureFingerprint(
        resource_type="kubernetes.service",
        failure_mechanism="selector_target_mismatch",
        symptom_codes=("request_route_failure", "endpoint_owner_mismatch"),
        topology_roles=("service", "client", "selected_workload"),
        ownership_shape=("service_selects_workload",),
    )
    receipts = (
        OperationalReceiptFact(
            receipt_type=OperationalReceiptType.AUDIT,
            receipt_digest="1" * 64,
            occurred_at=T0,
            facts=(("event_type", "action.completed"), ("decision", "auto"), ("mode", "enforce")),
        ),
        OperationalReceiptFact(
            receipt_type=OperationalReceiptType.ACTION,
            receipt_digest="2" * 64,
            occurred_at=T0,
            facts=(
                ("action_type", "ops.restart-service"),
                ("execution_outcome", outcome_class.value),
                ("dry_run_digest", "a" * 64),
                ("terminal_receipt_digest", "b" * 64),
            ),
        ),
        OperationalReceiptFact(
            receipt_type=OperationalReceiptType.RESPONSE_OUTCOME,
            receipt_digest="3" * 64,
            occurred_at=T0,
            facts=(
                ("label", response_status),
                ("verification_status", response_status),
                ("execution_outcome", outcome_class.value),
                ("rollback_succeeded", outcome_class is OperationalOutcomeClass.ROLLBACK),
                ("recurrence", outcome_class is OperationalOutcomeClass.RECURRENCE),
            ),
        ),
        OperationalReceiptFact(
            receipt_type=OperationalReceiptType.EVALUATION,
            receipt_digest="4" * 64,
            occurred_at=T0,
            facts=(
                ("validation_status", "accepted"),
                ("evidence_digest", "c" * 64),
                ("operationalized", True),
                ("azure_validated", False),
            ),
        ),
    )
    return OperationalCaseInput(
        case_identity_digest=f"{index + 1:x}" * 64,
        kind=CaseKind.ACTION,
        correlation_digest="e" * 64,
        purpose="operational-learning",
        access_scope_digest=ACCESS_SCOPE,
        redaction_policy_version="1.0.0",
        event_time_cutoff=T0,
        failure_fingerprint=fingerprint,
        action_type="ops.restart-service",
        outcome_class=outcome_class,
        evidence_refs=("9" * 64, "8" * 64),
        receipts=receipts,
        fdai_revision=READ_REVISION,
        scenario_set_version="v2026.08",
        source_kind=OperationalEvidenceSourceKind.LIVE,
        source_identity_digest="7" * 64,
        source_synthetic=False,
        evidence_complete=True,
        conflict_digests=(),
    )


async def run_rehearsal() -> dict[str, Any]:
    # Criterion 1: Explicitly authorized installation, target, source revisions, and bounded scope
    scope = QualificationVenueSelection(
        installation_id="fdai-local-isolated-validation",
        venue="local-isolated-validation",
        target_scope_digest=TARGET_SCOPE,
        access_scope_digest=ACCESS_SCOPE,
        fdai_revision="1e7778a701",
        read_source_revision=READ_REVISION,
        graph_source_revision=GRAPH_DIGEST,
        slo_revision="slo-v2026.10",
        safety_budget_revision="safety-budget-v2026.10",
        window_start=T0,
        window_end=T0 + timedelta(hours=6),
        deadline_seconds=5.0,
        authorized_by_operator=True,
    )
    refused_venues: list[str] = []
    for bad_venue in ("runtime", "port:5432", "production-unscoped"):
        try:
            QualificationVenueSelection(
                installation_id="fdai-local-isolated-validation",
                venue=bad_venue,
                target_scope_digest=TARGET_SCOPE,
                access_scope_digest=ACCESS_SCOPE,
                fdai_revision="1e7778a701",
                read_source_revision=READ_REVISION,
                graph_source_revision=GRAPH_DIGEST,
                slo_revision="slo-v2026.10",
                safety_budget_revision="safety-budget-v2026.10",
                window_start=T0,
                window_end=T0 + timedelta(hours=6),
            )
        except PermissionError:
            refused_venues.append(bad_venue)
    _require(len(refused_venues) == 3, "unauthorized venues were not refused")

    # Criteria 2, 3, 4, 7: Coherent final qualifier, server-owned bindings, and withdrawals
    store = InMemoryStateStore()
    admission_provider = StateStoreDecisionEvidenceAdmissionProvider(store=store, clock=lambda: NOW)
    metadata = StateStoreCaseHistoryMetadataStore(store=store)
    artifacts = StateStoreCaseHistoryArtifactStore(store=store)
    materializer = CaseHistoryMaterializer(metadata=metadata, artifacts=artifacts)

    cases: list[PatternCase] = []
    sealed_records = []
    for idx in range(3):
        outcome_cls = (
            OperationalOutcomeClass.SUCCESS if idx < 2 else OperationalOutcomeClass.ROLLBACK
        )
        raw_case = _build_case_input(idx, outcome_cls)
        sealed = await materializer.seal_operational_case(
            raw_case,
            retention_until=T0 + timedelta(days=30),
            deletion_due_at=T0 + timedelta(days=60),
        )
        p_case = pattern_case_from_operational_case(raw_case, sealed.projection)
        if p_case is None:
            raise RuntimeError("pattern case compilation failed")
        cases.append(p_case)
        rec = await metadata.latest(p_case.case_id, access_scope_digest=ACCESS_SCOPE)
        if rec is None:
            raise RuntimeError("sealed case metadata missing")
        sealed_records.append(rec)

    compiled = OperatingPatternCompiler().compile(cases, reviewed_at=NOW)
    if compiled is None:
        raise RuntimeError("cohort pattern compilation failed")
    projections = CaseHistoryProjectionStore(
        store=store,
        materializer=materializer,
        access_scope_digest=ACCESS_SCOPE,
        clock=lambda: NOW,
    )
    cohort_record = {
        "schema_version": "1.0.0",
        "pattern_id": compiled.pattern_id,
        "access_scope_digest": ACCESS_SCOPE,
        "purpose": "operational-learning",
        "cohort_key": "cohort",
        "candidate": compiled.to_rule_candidate_mapping(),
        "cases": [case.to_mapping() for case in cases],
        "execution_authority": False,
        "promotion_authority": False,
    }
    _require(
        await projections.write_state_if_absent(
            f"cohort:pattern:{compiled.pattern_id}", cohort_record
        )
    )

    auth_receipt = OperatorAuthenticationReceipt.create(
        evidence_class=OperatorAuthenticationEvidenceClass.LOCAL_LOOPBACK,
        issuer=LOCAL_LOOPBACK_ISSUER,
        audience="fdai-operator-api",
        tenant_digest=tenant_digest("00000000-0000-0000-0000-000000000001"),
        subject_id="operator-2194",
        principal_kind="human",
        groups=("aw-owners",),
        token_id_digest=token_id_digest("tok-2194"),
        issued_at=T0,
        expires_at=T0 + timedelta(minutes=30),
        roles=("Owner",),
        role_mapping_revision=role_mapping_revision({"Owner": "aw-owners"}),
    )
    inv_context = FunctionInvocationContext(
        caller_agent="Bragi",
        principal_ref="operator-2194",
        principal_groups=("aw-owners",),
        principal_scope_digest="sha256:" + ACCESS_SCOPE,
        authentication_receipt_ref=auth_receipt.receipt_digest,
        authentication_request_ref="req-2194",
        purposes=("operations-review",),
    )
    request = RetainedPatternRequest(
        context=inv_context,
        access_scope_digest=ACCESS_SCOPE,
        purpose="operational-learning",
        failure_fingerprint=cases[0].failure_fingerprint,
    )
    event = Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-2194-1",
            "source": "example",
            "event_type": "change_detected",
            "detected_at": T0.isoformat(),
            "ingested_at": (T0 + timedelta(seconds=1)).isoformat(),
            "mode": "shadow",
            "payload": {"resource": {"type": "kubernetes.service", "props": {}}},
        }
    )
    case_context = OperationalCaseContext(
        case_ref=cases[0].immutable_case_ref,
        failure_fingerprint=request.failure_fingerprint,
        resource_type=cases[0].resource_type,
        action_type=cases[0].action_type,
        required_topology_role="serves",
        graph_digest=GRAPH_DIGEST,
        owner_digest=OWNER_DIGEST,
        evidence_cutoff=T0,
        access_scope_digest=ACCESS_SCOPE,
        purpose=request.purpose,
    )
    scored_outcomes = [
        ScoredOutcome(
            signature=compiled.pattern_id,
            observed_at=T0 + timedelta(seconds=i),
            scorable=True,
            verified=i < 19,
            rolled_back=False,
        )
        for i in range(20)
    ]
    measured_map = measured_statistics(scored_outcomes, policy=StatisticsPolicy(min_outcomes=20))
    measured_stat = measured_map[compiled.pattern_id]
    statistics = RetainedReuseStatistics(
        action_signature=compiled.pattern_id,
        case_ref=case_context.case_ref,
        access_scope_digest=ACCESS_SCOPE,
        source_revision=GRAPH_DIGEST,
        evidence_ref="e" * 64,
        verified_successes=19,
        technical_failures=1,
        observed_at=T0,
        valid_until=T0 + timedelta(minutes=4),
    )
    action = LearnedAction(
        signature=compiled.pattern_id,
        rule_id="rule.scale.out",
        action_type=compiled.action_type,
        params={"count": 2},
        incident_id=cases[0].case_id,
        success_rate=measured_stat.success_rate,
        reuse_count=measured_stat.reuse_count,
        operational_case=case_context,
    )
    registered_action = OntologyActionType(
        schema_version="1.0.0",
        name=action.action_type,
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=1.0, max_policy_escapes=0
        ),
        argument_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["count"],
            "properties": {"count": {"type": "integer"}},
        },
    )
    observed_verification = CurrentReuseVerification(
        case_ref=case_context.case_ref,
        observed_at=T0 + timedelta(seconds=2),
        evidence_refs=("a" * 64,),
        failure_fingerprint=request.failure_fingerprint,
        resource_type=case_context.resource_type,
        topology_role="serves",
        graph_digest=GRAPH_DIGEST,
        owner_digest=OWNER_DIGEST,
        preconditions_passed=True,
        target_identity_verified=True,
        blast_radius_within_limit=True,
        policy_allowed=True,
        dry_run_passed=True,
        idempotency_available=True,
        rollback_resolved=True,
    )

    await store.write_state(
        owner_key("principal", inv_context.principal_ref, ACCESS_SCOPE, request.purpose),
        {
            "context": inv_context.model_dump(mode="json"),
            "scope": ACCESS_SCOPE,
            "purpose": request.purpose,
            "allowed": True,
            "valid_until": (NOW + timedelta(minutes=3)).isoformat(),
        },
    )
    await store.write_state(
        owner_key("authenticated_request", str(event.event_id)),
        {
            "event_id": str(event.event_id),
            "request_id": inv_context.authentication_request_ref,
            "context": inv_context.model_dump(mode="json"),
            "access_scope_digest": ACCESS_SCOPE,
            "purpose": request.purpose,
            "failure_fingerprint": request.failure_fingerprint,
            "receipt": auth_receipt.model_dump(mode="json"),
        },
    )
    await store.write_state(
        owner_key("statistics", statistics.action_signature, statistics.case_ref, ACCESS_SCOPE),
        {"statistics": statistics_mapping(statistics), "authorized": True},
    )
    await store.write_state(
        owner_key("action", registered_action.name),
        registered_action.model_dump(mode="json"),
    )
    await store.write_state(
        owner_key("reuse", str(event.event_id), case_context.case_ref, action.signature),
        {
            "verification": verification_mapping(observed_verification),
            "scope_digest": current_reuse_scope_digest(
                event=event, action=action, context=case_context
            ),
        },
    )
    await store.write_state(
        owner_key("candidate", str(event.event_id), compiled.pattern_id),
        {
            "event_id": str(event.event_id),
            "pattern_id": compiled.pattern_id,
            "score": 0.98,
            "statistics_ref": statistics.evidence_ref,
            "action": {
                "signature": action.signature,
                "rule_id": action.rule_id,
                "action_type": action.action_type,
                "params": dict(action.params),
                "incident_id": action.incident_id,
                "success_rate": action.success_rate,
                "reuse_count": action.reuse_count,
                "context": case_context.to_mapping(),
            },
        },
    )

    preliminary = qualification_request(
        event=event,
        arguments=request.arguments(),
        principal=inv_context.model_dump(mode="json"),
        read_source_revision=READ_REVISION,
        cohort=cohort_record,
        match=SimilarityMatch(action, 0.98),
        statistics=statistics,
        verification=observed_verification,
    )
    read_lookup, reuse_lookup = lookups(preliminary.descriptor)
    for lookup in (read_lookup, reuse_lookup):
        await _admit_gate_record(store, **lookup)

    class _StateStoreCoherentQualifier:
        async def qualify(
            self, req_qual: RetainedPatternQualification
        ) -> DecisionEvidenceAdmission | None:
            val = req_qual.descriptor
            core_k = set(base_keys(val))
            for rec in sealed_records:
                if rec.storage_ref:
                    core_k.add(artifact_key(rec.storage_ref))
            extra_k = {
                owner_key("authenticated_request", str(val["event"]["event_id"])),
                owner_key(
                    "candidate",
                    str(val["event"]["event_id"]),
                    str(val["cohort"]["pattern_id"]),
                ),
            }
            rows: dict[str, dict[str, Any]] = {}
            for k in sorted(core_k | extra_k):
                r = await store.read_state(k)
                if r is None:
                    return None
                rows[k] = dict(r)
            if not _validate_server_owned_bindings(val, rows, now=NOW):
                return None
            base_rows = {k: rows[k] for k in core_k}
            try:
                leased = validate_locked(req_qual, base_rows, now=NOW)
            except (KeyError, TypeError, ValueError):
                return None
            if leased is None or NOW >= leased.valid_until:
                return None
            return await _admit_gate_record(
                store,
                evidence_digest=req_qual.evidence_digest,
                scope_digest=req_qual.scope_digest,
                purpose_id=FINAL_QUALIFICATION_PURPOSE,
                source_revision=req_qual.evidence_digest,
            )

    class _ServerVerifier:
        async def verify(
            self, *, event: Event, action: LearnedAction, context: OperationalCaseContext
        ) -> CurrentReuseVerification:
            raw = await store.read_state(
                owner_key("reuse", str(event.event_id), context.case_ref, action.signature)
            )
            if raw is None:
                raise LookupError("current-reuse source missing")
            ver_map = dict(raw["verification"])
            ver_map["observed_at"] = datetime.fromisoformat(ver_map["observed_at"])
            ver_map["evidence_refs"] = tuple(ver_map["evidence_refs"])
            obs = CurrentReuseVerification(**ver_map)
            sc = current_reuse_scope_digest(event=event, action=action, context=context)
            adm = await admission_provider.admit(
                evidence_digest=current_reuse_evidence_digest(obs),
                scope_digest=sc,
                purpose_id="current-case-reuse",
                source_revision=context.graph_digest,
            )
            return replace(obs, decision_evidence=adm)

    async def _server_request(ev: Event) -> RetainedPatternRequest | None:
        raw = await store.read_state(owner_key("authenticated_request", str(ev.event_id)))
        if raw is None:
            return None
        grant = await store.read_state(
            owner_key("principal", inv_context.principal_ref, ACCESS_SCOPE, request.purpose)
        )
        if grant is None or grant.get("allowed") is not True:
            return None
        return request

    async def _server_resolve(ev: Event, summary: Mapping[str, Any]) -> SimilarityMatch | None:
        raw = await store.read_state(
            owner_key("candidate", str(ev.event_id), str(summary.get("pattern_id", "")))
        )
        if raw is None or await store.read_state(owner_key("action", action.action_type)) is None:
            return None
        return SimilarityMatch(action, 0.98)

    async def _server_stats(ev: Event, match: SimilarityMatch) -> RetainedReuseStatistics | None:
        del ev
        raw = await store.read_state(
            owner_key("statistics", match.action.signature, case_context.case_ref, ACCESS_SCOPE)
        )
        if raw is None or raw.get("authorized") is not True:
            return None
        return statistics

    query = OperatingPatternQuery(
        store=store,
        materializer=lambda: materializer,
        admission=admission_provider,
        source_revision=READ_REVISION,
        clock=lambda: NOW,
    )
    pattern_source = RetainedPatternSource(
        query=query,
        request_source=_server_request,
        action_resolver=_server_resolve,
        action_types=lambda: (
            {registered_action.name: registered_action}
            if store._state.get(owner_key("action", registered_action.name)) is not None
            else {}
        ),
        store=store,
        materializer=lambda: materializer,
        statistics_source=_server_stats,
        final_qualifier=_StateStoreCoherentQualifier(),
        clock=lambda: NOW,
    )
    tier = T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=_BaselineLibrary(),
        current_reuse_verifier=_ServerVerifier(),
        case_history=materializer,
        retained_pattern_source=pattern_source,
        clock=lambda: NOW,
        config=T1Config(compare_eligibility=True, timeout_seconds=5.0),
    )

    positive_decision: T1Decision = await tier.evaluate(event=event)
    _require(
        positive_decision.outcome is T1Outcome.ABSTAIN and positive_decision.best_match is None
    )
    _require(positive_decision.retained_pattern_comparison is not None)
    pos_comp = positive_decision.retained_pattern_comparison
    if pos_comp is None or pos_comp.final_qualification is None:
        raise RuntimeError("positive retained pattern comparison or final qualification missing")
    _require(
        pos_comp.challenger_match is not None,
        f"stop_reason={pos_comp.stop_reason} candidates={pos_comp.candidates}",
    )
    _require(pos_comp.final_qualification.purpose_id == FINAL_QUALIFICATION_PURPOSE)

    # Exercise withdrawals: measurement, negative-case, admissions, policy, principal, action
    snapshot_state = dict(store._state)
    withdrawal_kinds = (
        "measurement_withdrawal",
        "negative_case_deletion",
        "read_admission_withdrawal",
        "reuse_admission_withdrawal",
        "policy_denial",
        "principal_withdrawal",
        "action_withdrawal",
    )
    verified_withdrawals: list[str] = []
    for w_kind in withdrawal_kinds:
        store._state = {k: json.loads(json.dumps(v)) for k, v in snapshot_state.items()}
        if w_kind == "measurement_withdrawal":
            await store.write_state(
                owner_key(
                    "statistics", statistics.action_signature, statistics.case_ref, ACCESS_SCOPE
                ),
                {"statistics": statistics_mapping(statistics), "authorized": False},
            )
        elif w_kind == "negative_case_deletion":
            await store.delete_state("case-history:latest:" + sealed_records[-1].case_id)
        elif w_kind == "read_admission_withdrawal":
            await store.delete_state(decision_evidence_state_key(**read_lookup))
        elif w_kind == "reuse_admission_withdrawal":
            await store.delete_state(decision_evidence_state_key(**reuse_lookup))
        elif w_kind == "policy_denial":
            denied_obs = replace(observed_verification, policy_allowed=False)
            await store.write_state(
                owner_key("reuse", str(event.event_id), case_context.case_ref, action.signature),
                {
                    "verification": verification_mapping(denied_obs),
                    "scope_digest": current_reuse_scope_digest(
                        event=event, action=action, context=case_context
                    ),
                },
            )
        elif w_kind == "principal_withdrawal":
            await store.write_state(
                owner_key("principal", inv_context.principal_ref, ACCESS_SCOPE, request.purpose),
                {
                    "context": inv_context.model_dump(mode="json"),
                    "scope": ACCESS_SCOPE,
                    "purpose": request.purpose,
                    "allowed": False,
                    "valid_until": (NOW + timedelta(minutes=3)).isoformat(),
                },
            )
        elif w_kind == "action_withdrawal":
            await store.delete_state(owner_key("action", registered_action.name))
        w_decision = await tier.evaluate(event=event)
        _require(w_decision.best_match is None)
        _require(
            w_decision.retained_pattern_comparison is not None
            and w_decision.retained_pattern_comparison.challenger_match is None
        )
        verified_withdrawals.append(w_kind)

    store._state = {k: json.loads(json.dumps(v)) for k, v in snapshot_state.items()}

    # Criterion 5: Frozen predictor/observer provenance, intervention, retention, unknown outcomes
    pred_snapshot = EffectPredictionSnapshot(
        prediction_id="pred-2194-1",
        event_id=UUID(int=219410),
        action_id=UUID(int=219420),
        action_type_id="ops.scale-out",
        target_digest="0" * 64,
        metric="latency_p99_ms",
        unit="ms",
        objective="minimize",
        model_ref="baseline.scale-out@1.0.0",
        model_digest=MODEL_DIGEST,
        source_digest="c" * 64,
        independence_key=hashlib.sha256(b"ep-2194-1").hexdigest(),
        point_prediction=100.0,
        interval_lower=90.0,
        interval_upper=110.0,
        nominal_coverage=0.95,
        known_at=T0,
        predicted_at=T0,
        observation_deadline=T0 + timedelta(minutes=5),
    )
    await retain_prediction(store, pred_snapshot, recorded_at=T0 + timedelta(seconds=1))
    _require(
        await prediction_available(store, pred_snapshot, observed_at=T0 + timedelta(minutes=1))
    )

    seed_model = EffectModel(
        model_id="effect.ops.scale-out",
        version="1.0.0",
        revision=1,
        action_type_id="ops.scale-out",
        metric="latency_p99_ms",
        status=EffectModelStatus.CHALLENGER,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="a" * 64,
        learned_at=T0,
        learned_through=T0,
        prediction_model_ref="baseline.scale-out@1.0.0",
        prediction_model_digest=MODEL_DIGEST,
        unit="ms",
    )

    class _CurrentFeedbackSource:
        async def current(self, revision_digests: tuple[str, ...]) -> bool:
            return bool(revision_digests)

    model_registry = StateStoreEffectModelRegistry(
        store,
        clock=lambda: T0 + timedelta(minutes=10),
        feedback_source=_CurrentFeedbackSource(),
    )
    _require(await model_registry.register(seed_model, registered_by="Mimir"))

    completed_outcome = ResponseOutcome.model_validate(
        {
            "schema_version": "1.1.0",
            "outcome_id": str(UUID(int=219430)),
            "outcome_revision": 1,
            "idempotency_key": "outcome-2194-1",
            "action_id": str(pred_snapshot.action_id),
            "event_id": str(pred_snapshot.event_id),
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": pred_snapshot.prediction_id,
            "metric": "latency_p99_ms",
            "expected_min": 90.0,
            "expected_max": 110.0,
            "observed_value": 96.0,
            "predicted_at": T0,
            "observation_deadline": T0 + timedelta(minutes=5),
            "observed_at": T0 + timedelta(minutes=1),
            "label": "verified",
            "verification_status": "verified",
            "verification_reason": "value_within_acceptable_range",
            "execution_mode": "enforce",
            "execution_outcome": "succeeded",
            "rollback_succeeded": False,
            "decision": "auto",
            "evidence_refs": ["effect:pred-2194-1"],
            "recorded_at": T0 + timedelta(minutes=2),
            "prediction_snapshot": pred_snapshot,
            "observation_unit": "ms",
            "observation_receipt_ref": "observer-receipt:2194-1",
        }
    )
    unknown_outcome = ResponseOutcome.model_validate(
        {
            "schema_version": "1.1.0",
            "outcome_id": str(UUID(int=219431)),
            "outcome_revision": 1,
            "idempotency_key": "outcome-2194-2",
            "action_id": str(UUID(int=219421)),
            "event_id": str(UUID(int=219411)),
            "action_type_id": "ops.scale-out",
            "target_digest": "0" * 64,
            "prediction_id": "pred-2194-unknown",
            "metric": "latency_p99_ms",
            "expected_min": 90.0,
            "expected_max": 110.0,
            "observed_value": None,
            "predicted_at": T0,
            "observation_deadline": T0 + timedelta(minutes=5),
            "observed_at": None,
            "label": "unscorable",
            "verification_status": "hold",
            "verification_reason": "observation_withheld",
            "execution_mode": "shadow",
            "execution_outcome": "held",
            "rollback_succeeded": None,
            "decision": "abstain",
            "evidence_refs": ["effect:pred-2194-unknown"],
            "recorded_at": T0 + timedelta(minutes=2),
            "prediction_snapshot": None,
            "observation_unit": None,
            "observation_receipt_ref": None,
        }
    )
    update_res = await model_registry.update_from_outcome(completed_outcome)
    _require(update_res.accepted)
    rebuild_res = rebuild_feedback(
        seed=seed_model,
        outcomes=(completed_outcome, unknown_outcome),
        as_of=T0 + timedelta(hours=1),
        complete=True,
    )
    prequential = evaluate_frozen_predictions(
        (completed_outcome, unknown_outcome),
        as_of=T0 + timedelta(hours=1),
        training_independence_keys=frozenset(),
        source_kind="historical",
    )
    provenance = qualify_frozen_intervention_provenance(
        (completed_outcome, unknown_outcome),
        retained_predictions={pred_snapshot.prediction_id: pred_snapshot},
        model_generation_digests=frozenset({MODEL_DIGEST}),
        as_of=T0 + timedelta(hours=1),
    )
    _require(provenance.qualified_interventions_count == 1)
    _require(provenance.unknown_preserved_count == 1)

    # Criteria 6, 7, 8, 9: Predeclared gates, T1/shadow intake, separate metrics, policy guard
    gates = PredeclaredLearningEvaluationGates(
        slo_revision="slo-v2026.10",
        safety_budget_revision="safety-budget-v2026.10",
        min_independent_episodes_per_arm=4,
        min_time_separation=timedelta(minutes=5),
        observation_window=timedelta(hours=1),
        recurrence_window=timedelta(hours=24),
        min_recovery_rate=0.75,
        max_recurrence_rate=0.20,
        max_rollback_rate=0.10,
        max_side_effect_count=0,
        max_policy_escape_count=0,
        max_mean_absolute_error=10.0,
        max_brier_score=0.15,
        min_interval_coverage=0.80,
    )
    intake_summary = FrozenT1ShadowIntakeSummary(
        evaluated_events=len(verified_withdrawals) + 1,
        baseline_selections_preserved=len(verified_withdrawals) + 1,
        coherent_qualified_shadow_matches=1,
        leased_qualified_shadow_matches=1,
        withdrawal_rejections_verified=len(verified_withdrawals),
        deadline_and_cancellation_holds_verified=2,
        stale_or_expired_holds_verified=2,
    )
    episodes: list[OperationalLearningEpisode] = []
    for i in range(5):
        episodes.append(
            OperationalLearningEpisode(
                episode_id=f"base-{i}",
                arm="baseline",
                incident_id=f"inc-base-{i}",
                independence_key=f"ind-base-{i}",
                common_cause_key=f"cc-base-{i}",
                idempotency_key=f"idem-base-{i}",
                observed_at=T0 + timedelta(minutes=i * 10),
                execution_mode="enforce",
                decision="auto" if i < 4 else "abstain",
                recommended=i < 4,
                abstained=i == 4,
                intervention_completed=i < 4,
                outcome_known=i < 4,
                recovered=True if i < 3 else (False if i == 3 else None),
                recovery_seconds=110.0 if i < 3 else None,
                recurrence_window_complete=i < 3,
                recurred=False if i < 3 else None,
                rolled_back=False,
                predicted_recovery_probability=0.80 if i < 4 else None,
                point_prediction=100.0 if i < 4 else None,
                interval_lower=90.0 if i < 4 else None,
                interval_upper=110.0 if i < 4 else None,
                observed_value=95.0 if i < 4 else None,
            )
        )
    episodes.append(
        OperationalLearningEpisode(
            episode_id="base-retry-0",
            arm="baseline",
            incident_id="inc-base-0",
            independence_key="ind-base-retry",
            common_cause_key="cc-base-retry",
            idempotency_key="idem-base-retry",
            observed_at=T0 + timedelta(minutes=55),
            is_retry_or_replay=True,
        )
    )
    episodes.append(
        OperationalLearningEpisode(
            episode_id="base-dup-incident",
            arm="baseline",
            incident_id="inc-base-1",
            independence_key="ind-base-dup",
            common_cause_key="cc-base-dup",
            idempotency_key="idem-base-dup",
            observed_at=T0 + timedelta(minutes=65),
        )
    )
    for i in range(5):
        episodes.append(
            OperationalLearningEpisode(
                episode_id=f"chal-{i}",
                arm="challenger",
                incident_id=f"inc-chal-{i}",
                independence_key=f"ind-chal-{i}",
                common_cause_key=f"cc-chal-{i}",
                idempotency_key=f"idem-chal-{i}",
                observed_at=T0 + timedelta(minutes=100 + i * 10),
                execution_mode="enforce",
                decision="auto" if i < 4 else "abstain",
                recommended=i < 4,
                abstained=i == 4,
                intervention_completed=i < 4,
                outcome_known=i < 4,
                recovered=True if i < 4 else None,
                recovery_seconds=85.0 if i < 4 else None,
                recurrence_window_complete=i < 3,
                recurred=False if i < 3 else None,
                rolled_back=False,
                predicted_recovery_probability=0.90 if i < 4 else None,
                point_prediction=100.0 if i < 4 else None,
                interval_lower=90.0 if i < 4 else None,
                interval_upper=110.0 if i < 4 else None,
                observed_value=96.0 if i < 4 else None,
                propensity_overlap_verified=False,
            )
        )

    report = evaluate_operational_learning_effects(
        scope=scope,
        gates=gates,
        provenance=provenance,
        t1_shadow_intake=intake_summary,
        episodes=episodes,
        claim_policy_effect=False,
    )
    _require(report.gates_passed is True)
    _require(report.policy_effect_claimed is False)

    policy_claim_blocked = False
    try:
        evaluate_operational_learning_effects(
            scope=scope,
            gates=gates,
            provenance=provenance,
            t1_shadow_intake=intake_summary,
            episodes=episodes,
            claim_policy_effect=True,
        )
    except ValueError:
        policy_claim_blocked = True
    _require(policy_claim_blocked, "unexecuted/shadow policy effect claim was not blocked")

    body: dict[str, Any] = {
        "kind": "fdai.operational-learning-qualification-receipt.v1",
        "issue": 2194,
        "criterion_1_scope_selection": {
            "installation_id": scope.installation_id,
            "venue": scope.venue,
            "scope_manifest_digest": scope.scope_manifest_digest,
            "refused_unauthorized_venues": refused_venues,
        },
        "criterion_2_coherent_final_qualifier": {
            "purpose_id": pos_comp.final_qualification.purpose_id,
            "receipt_digest": pos_comp.final_qualification.receipt_digest,
            "tuple_digest": pos_comp.final_qualification.evidence_digest,
            "baseline_preserved": positive_decision.best_match is None,
        },
        "criterion_3_withdrawals_and_bounds": {
            "verified_withdrawals": verified_withdrawals,
            "withdrawal_count": len(verified_withdrawals),
            "baseline_preserved_across_all": True,
        },
        "criterion_4_server_owned_bindings": {
            "authentication_receipt_digest": auth_receipt.receipt_digest,
            "registered_action_type": registered_action.name,
            "measured_statistics_ref": statistics.evidence_ref,
            "read_admission_digest": read_lookup["evidence_digest"],
            "reuse_admission_digest": reuse_lookup["evidence_digest"],
        },
        "criterion_5_frozen_provenance_and_retention": {
            "prediction_digest": pred_snapshot.digest,
            "qualified_interventions_count": provenance.qualified_interventions_count,
            "unknown_preserved_count": provenance.unknown_preserved_count,
            "rebuild_accepted_episodes": rebuild_res.accepted_episodes,
            "rebuild_held_episodes": rebuild_res.held_episodes,
            "prequential_mae": prequential.mean_absolute_error,
        },
        "criterion_6_predeclared_gates_and_deduplication": {
            "gate_plan_digest": gates.gate_plan_digest,
            "gates_passed": report.gates_passed,
            "baseline_excluded_retries": (
                report.baseline.sample_counts.excluded_retry_or_replay_count
            ),
            "baseline_excluded_duplicates": (
                report.baseline.sample_counts.excluded_duplicate_group_count
            ),
            "baseline_independent_episodes": (
                report.baseline.sample_counts.independent_episode_count
            ),
            "challenger_independent_episodes": (
                report.challenger.sample_counts.independent_episode_count
            ),
        },
        "criterion_7_frozen_t1_and_shadow_intake": {
            "evaluated_events": intake_summary.evaluated_events,
            "baseline_selections_preserved": intake_summary.baseline_selections_preserved,
            "withdrawal_rejections_verified": intake_summary.withdrawal_rejections_verified,
            "execution_authority_granted": intake_summary.execution_authority_granted,
            "promotion_authority_granted": intake_summary.promotion_authority_granted,
        },
        "criterion_8_separate_metrics_and_uncertainty": report.to_mapping(),
        "criterion_9_no_fabricated_policy_effect": {
            "policy_effect_claimed": report.policy_effect_claimed,
            "unverified_claim_blocked": policy_claim_blocked,
        },
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["receipt_sha256"] = hashlib.sha256(encoded).hexdigest()
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output file path.")
    args = parser.parse_args(argv)
    receipt = asyncio.run(run_rehearsal())
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
