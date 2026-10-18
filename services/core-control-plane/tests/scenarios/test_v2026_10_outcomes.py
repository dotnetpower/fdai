"""Capability-specific FDAI-CONST-005 outcome evidence for v2026.10."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from fdai.core.architecture_review import (
    ArchitectureDecisionAuthorityBasis,
    ArchitectureDecisionOutcome,
    build_architecture_review_decision_receipt,
)
from fdai.core.chaos import ChaosRunState
from fdai.core.measurement.cost_effect_settlement import CostEffectSettlementService
from fdai.core.mscp_profile import (
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
    verify_effect,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_replacement_evidence import (
    KubernetesPodReplacementStatus,
)
from fdai.core.readiness.detection_lifecycle import (
    DetectionPublicationState,
    PodLifecycleCurrentState,
    PodLifecycleDetectionRecord,
    PodLifecycleRecoveryState,
    reduce_pod_lifecycle_detection,
)
from fdai.core.recovery import (
    ProbeVerdict,
    RecoveryProbeKind,
    RecoveryProbeResult,
    RecoveryVerificationOutcome,
    verify_recovery_postconditions,
)
from fdai.core.verticals.resilience.recovery_plan import (
    RecoveryMode,
    RecoveryObjectives,
    RecoveryObservationLane,
    RecoveryOutcomeMeasurement,
    RecoveryPlan,
    RecoveryPlanStateMachine,
    RecoveryProfile,
    RecoveryState,
)
from fdai.shared.providers.cost_governance_decision import (
    CostCompletenessReceipt,
    CostEffectKind,
    CostEffectObservation,
    CostExpectedEffect,
    CostObservationLane,
    CostSavingsEvidenceClass,
    CostSettlementStatus,
)

from tests.core.chaos import test_governed_runner as chaos_support

_ROOT = Path(__file__).resolve().parent
_SCENARIO_DIR = _ROOT / "v2026.10"
_ENRICHMENT_DIR = _ROOT / "enrichment" / "v2026.10"
_MANIFEST_PATH = _ROOT / "manifests" / "v2026.10.json"
_AT = datetime(2026, 7, 5, 8, tzinfo=UTC)
_DIGESTS = tuple(f"sha256:{character * 64}" for character in "abcdef")


class _StatefulFaultInjector:
    """Mutate only local test state so enforce replay proves inject and rollback."""

    def __init__(self, fault_type: str) -> None:
        self._fault_type = fault_type
        self.active: set[str] = set()
        self.injected: list[str] = []
        self.stopped: list[str] = []

    @property
    def fault_type(self) -> str:
        return self._fault_type

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        del params
        self.active.add(target)
        self.injected.append(target)

    async def stop(self, *, target: str) -> None:
        self.active.discard(target)
        self.stopped.append(target)


def _filename(scenario_id: str) -> str:
    return scenario_id.replace(".", "-") + ".json"


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _bound_scenario(
    capability: str,
    scenario_id: str,
    outcome_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = cast(
        dict[str, Any],
        json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")),
    )
    pack = manifest["capability_packs"][capability]
    assert scenario_id in pack["scenario_ids"]
    assert pack["required_outcome"]["id"] == outcome_id
    assert pack["required_outcome"]["status"] == "complete"
    assert any(item["scenario_id"] == scenario_id for item in pack["required_outcome"]["evidence"])

    scenario = cast(
        dict[str, Any],
        json.loads((_SCENARIO_DIR / _filename(scenario_id)).read_text(encoding="utf-8")),
    )
    overlay = cast(
        dict[str, Any],
        json.loads((_ENRICHMENT_DIR / _filename(scenario_id)).read_text(encoding="utf-8")),
    )
    assert scenario["id"] == overlay["scenario_id"] == scenario_id
    assert scenario["version"] == "v2026.10"
    return scenario, overlay


def _verified_effect(overlay: dict[str, Any]) -> EffectVerificationStatus:
    evidence = overlay["effect_evidence"]
    target_ref = overlay["event_payload_resource"]["resource_id"]
    observation = evidence["authoritative_observation"]
    expected = ExpectedEffect(
        prediction_id=evidence["prediction_id"],
        target_ref=target_ref,
        metric=evidence["metric"],
        acceptable_min=float(evidence["acceptable_min"]),
        acceptable_max=float(evidence["acceptable_max"]),
        predicted_at=datetime.fromisoformat(evidence["predicted_at"]),
        observation_deadline=datetime.fromisoformat(evidence["observation_deadline"]),
    )
    observed = ObservedEffect(
        prediction_id=evidence["prediction_id"],
        target_ref=target_ref,
        metric=evidence["metric"],
        value=float(observation["value"]),
        observed_at=datetime.fromisoformat(observation["observed_at"]),
    )
    return verify_effect(expected, observed).status


def test_sre_outcome_closes_recovery_and_recurrence() -> None:
    scenario_id = "sre.cluster-diagnostics-missing.001"
    _, overlay = _bound_scenario(
        "sre",
        scenario_id,
        "recovery_and_recurrence_closure",
    )
    resource_ref = str(overlay["event_payload_resource"]["resource_id"])
    recovery = PodLifecycleDetectionRecord(
        resource_ref=resource_ref,
        idempotency_key=f"{scenario_id}:recovery",
        signal=KubernetesPodReplacementStatus.POD_REPLACEMENT,
        occurred_at=_AT,
        recorded_at=_AT + timedelta(minutes=1),
        detection_latency_seconds=60.0,
        evidence_complete=True,
        recovery_closed=True,
        recovery_status=KubernetesPodRecoveryStatus.RECOVERED,
        publication=DetectionPublicationState.PUBLISHED,
        assessed_by="heimdall-independent-observer",
        evidence_refs=("evidence:recovery-observation",),
    )

    snapshot = reduce_pod_lifecycle_detection(
        (recovery,),
        resource_ref=resource_ref,
        generated_at=_AT + timedelta(minutes=2),
    )
    probes = tuple(
        RecoveryProbeResult(
            kind=kind,
            verdict=ProbeVerdict.PASSED,
            observed_at=_AT + timedelta(minutes=2),
            evidence_ref=f"evidence:independent:{kind.value}",
        )
        for kind in RecoveryProbeKind
    )
    closure = verify_recovery_postconditions(probes, telemetry_complete=True)

    assert _verified_effect(overlay) is EffectVerificationStatus.VERIFIED
    assert snapshot.current_state is PodLifecycleCurrentState.RECOVERED
    assert snapshot.recovery_state is PodLifecycleRecoveryState.VERIFIED
    assert snapshot.execution_authority is False
    assert closure.outcome is RecoveryVerificationOutcome.RECOVERED
    assert any(item.kind is RecoveryProbeKind.RECURRENCE_CLEAR for item in probes)


def test_arb_outcome_binds_approval_conditions_and_post_change_verification() -> None:
    scenario_id = "change.vm-managed-identity-missing.004"
    _, overlay = _bound_scenario(
        "arb_change_safety",
        scenario_id,
        "approval_conditions_and_post_change_verification",
    )
    effect_evidence_digest = _digest(overlay["effect_evidence"])
    receipt = build_architecture_review_decision_receipt(
        review_case_id=scenario_id,
        change_id=scenario_id,
        decision_case_id="decision-case:managed-identity",
        impact_envelope_id="impact:managed-identity",
        target_revision="revision:v2026.10",
        context_snapshot_id="context:v2026.10",
        evidence_bundle_id="evidence:v2026.10",
        graph_revision=_DIGESTS[0],
        catalog_release="catalog:v2026.10",
        evidence_refs=(_DIGESTS[1], effect_evidence_digest),
        conditions=("post_change_identity_readback_required",),
        outcome=ArchitectureDecisionOutcome.CONDITIONAL,
        rationale="Two distinct approvers require an independent identity readback.",
        authority_basis=ArchitectureDecisionAuthorityBasis.HUMAN_APPROVAL,
        authority_ref="authority:architecture-review",
        requester_id="principal:requester",
        judge_id="agent:Forseti",
        arbitrator_id="agent:Odin",
        approver_ids=("principal:approver-a", "principal:approver-b"),
        approval_receipt_refs=("approval:a", "approval:b"),
        quorum=2,
        audit_intent_ref="audit:intent",
        terminal_audit_ref="audit:terminal",
        recorded_at=_AT,
        effective_from=_AT,
        effective_until=_AT + timedelta(hours=1),
        reevaluation_trigger="evidence_or_scope_changes",
    )

    assert receipt.conditions == ("post_change_identity_readback_required",)
    assert receipt.authority_basis is ArchitectureDecisionAuthorityBasis.HUMAN_APPROVAL
    assert receipt.execution_authority is False
    assert effect_evidence_digest in receipt.evidence_refs
    assert _verified_effect(overlay) is EffectVerificationStatus.VERIFIED


def test_finops_outcome_requires_realized_savings_and_reliability() -> None:
    scenario_id = "finops.stop-idle-dev-vm-off-hours.003"
    _, overlay = _bound_scenario(
        "finops",
        scenario_id,
        "realized_savings_with_reliability_valid",
    )
    target_ref = str(overlay["event_payload_resource"]["resource_id"])
    effects = (
        CostExpectedEffect(
            effect_id=f"{scenario_id}:cost",
            kind=CostEffectKind.COST,
            target_ref=target_ref,
            metric="hourly_cost",
            baseline_value=Decimal("100"),
            acceptable_min=Decimal("70"),
            acceptable_max=Decimal("90"),
            predicted_at=_AT,
            horizon=timedelta(hours=1),
            telemetry_grace=timedelta(minutes=15),
            source_digest=_DIGESTS[0],
            savings_evidence_class=CostSavingsEvidenceClass.VERIFIED_RUN_RATE,
            currency="USD",
            baseline_window_digest=_DIGESTS[2],
            treatment_window_digest=_DIGESTS[3],
            demand_normalization_digest=_DIGESTS[4],
        ),
        CostExpectedEffect(
            effect_id=f"{scenario_id}:service",
            kind=CostEffectKind.SERVICE,
            target_ref=target_ref,
            metric="availability_percent",
            baseline_value=Decimal("100"),
            acceptable_min=Decimal("99"),
            acceptable_max=Decimal("100"),
            predicted_at=_AT,
            horizon=timedelta(hours=1),
            telemetry_grace=timedelta(minutes=15),
            source_digest=_DIGESTS[1],
        ),
    )
    observations = tuple(
        CostEffectObservation(
            observation_id=f"observation:{index}",
            effect_id=effect.effect_id,
            effect_source_digest=effect.source_digest,
            target_ref=target_ref,
            metric=effect.metric,
            value=Decimal("80") if effect.kind is CostEffectKind.COST else Decimal("100"),
            observed_at=effect.horizon_ends_at,
            lane=CostObservationLane.INDEPENDENT,
            source_authority="heimdall-independent-observer",
            evidence_digest=_DIGESTS[index + 2],
        )
        for index, effect in enumerate(effects)
    )
    completeness = tuple(
        CostCompletenessReceipt(
            effect_id=effect.effect_id,
            effect_source_digest=effect.source_digest,
            receipt_digest=_DIGESTS[index + 4],
            complete=True,
            coverage_through_at=effect.horizon_ends_at,
            lane=CostObservationLane.INDEPENDENT,
            source_authority="heimdall-completeness",
        )
        for index, effect in enumerate(effects)
    )

    settlement = CostEffectSettlementService().settle(
        episode_id=scenario_id,
        decision_frame_digest=_DIGESTS[0],
        action_ref=f"action-run:{scenario_id}",
        action_revision=1,
        expected_effects=effects,
        observations=observations,
        completeness_receipts=completeness,
        interventions=(),
        evaluated_at=_AT + timedelta(hours=1, minutes=15),
        evidence_refs=(_DIGESTS[1],),
    )

    assert settlement.terminal is True
    assert settlement.realized_savings == Decimal("20")
    assert {item.status for item in settlement.effects} == {CostSettlementStatus.VERIFIED}
    assert settlement.rollback_request is None


def test_dr_outcome_binds_integrity_and_measured_rto_rpo() -> None:
    scenario_id = "dr.backup-vault-restore-rehearsal.002"
    _bound_scenario("dr", scenario_id, "data_integrity_and_measured_rto_rpo")
    objectives = RecoveryObjectives(
        rpo_seconds=60.0,
        rto_seconds=120.0,
        max_degraded_seconds=180.0,
    )
    plan = RecoveryPlan(
        plan_id=scenario_id,
        revision=1,
        mode=RecoveryMode.DRILL,
        profile=RecoveryProfile.RESTORE,
        primary_region="primary-region",
        recovery_region="recovery-region",
        requester_ref="principal:requester",
        scope=("example-postgresql-server",),
        objectives=objectives,
        stop_conditions=("primary_fence_unverified", "state_integrity_failed"),
        rollback_ref="runbook:restore",
        max_affected_resources=1,
    )
    machine = RecoveryPlanStateMachine()
    transitions = []
    sequence = (
        RecoveryState.READY,
        RecoveryState.APPROVED,
        RecoveryState.ACTIVATING,
        RecoveryState.PRIMARY_FENCED,
        RecoveryState.STATE_RESTORED,
        RecoveryState.RUNTIME_STARTED,
        RecoveryState.AUDIT_VERIFIED,
        RecoveryState.EVENT_RECOVERY_READY,
        RecoveryState.TRAFFIC_SHIFTED,
        RecoveryState.SERVICE_VERIFIED,
    )
    for offset, target in enumerate(sequence):
        evidence_refs = (
            ("evidence:independent:data-integrity:passed",)
            if target is RecoveryState.STATE_RESTORED
            else (f"evidence:{target.value}",)
        )
        plan, transition = machine.transition(
            plan,
            target=target,
            actor_ref="principal:reliability-approver",
            at=_AT + timedelta(seconds=offset * 10),
            evidence_refs=evidence_refs,
            approval_ref="approval:drill" if target is RecoveryState.APPROVED else None,
            recovery_epoch=(
                1 if target is RecoveryState.ACTIVATING else plan.recovery_epoch or None
            ),
        )
        transitions.append(transition)

    activation_at = next(
        item.at for item in transitions if item.to_state is RecoveryState.ACTIVATING
    )
    service_verified_at = next(
        item.at for item in transitions if item.to_state is RecoveryState.SERVICE_VERIFIED
    )
    integrity = next(item for item in transitions if item.to_state is RecoveryState.STATE_RESTORED)
    snapshot_at = _AT - timedelta(seconds=30)
    failure_at = _AT
    measurement = RecoveryOutcomeMeasurement(
        plan_id=scenario_id,
        plan_revision=plan.revision,
        recovery_epoch=plan.recovery_epoch,
        snapshot_at=snapshot_at,
        failure_at=failure_at,
        activated_at=activation_at,
        verified_at=service_verified_at,
        data_integrity_verified=True,
        observation_lane=RecoveryObservationLane.INDEPENDENT,
        observer_ref="heimdall-independent-recovery-observer",
        evidence_refs=integrity.evidence_refs,
    )

    assert plan.state is RecoveryState.SERVICE_VERIFIED
    assert measurement.observed_rto_seconds == 70.0
    assert measurement.observed_rpo_seconds == 30.0
    assert measurement.meets(plan)
    assert integrity.evidence_refs == ("evidence:independent:data-integrity:passed",)


async def test_chaos_outcome_requires_human_approval_continuous_guards_and_recovery() -> None:
    scenario_id = "dr.chaos-experiment-novel.003"
    _bound_scenario(
        "chaos",
        scenario_id,
        "human_approved_injection_and_verified_recovery",
    )
    eligibility = chaos_support._eligibility()
    scenario = replace(chaos_support._scenario(), scenario_id=scenario_id)
    injector = _StatefulFaultInjector(fault_type=scenario.fault_type)
    dispatcher = chaos_support._Dispatcher()
    guard_samples: list[float] = []

    async def guard(elapsed: float) -> None:
        guard_samples.append(elapsed)

    result = await chaos_support._runner(injector, dispatcher).run_enforce(
        run_id=f"{scenario_id}:run",
        scenario=scenario,
        eligibility_context=eligibility,
        recovery_plan=chaos_support._plan(),
        impact_guard=guard,
    )

    assert eligibility.approval_principal == "Var"
    assert set(eligibility.approver_ids).isdisjoint({eligibility.initiator_id})
    assert guard_samples
    assert len(guard_samples) >= 2
    assert all(sample >= 0 for sample in guard_samples)
    assert injector.injected == ["resource-a"]
    assert injector.stopped == ["resource-a"]
    assert injector.active == set()
    assert result.state.state is ChaosRunState.RECOVERED
    assert result.experiment is not None and result.experiment.reverted
    assert result.recovery is not None and result.recovery.succeeded
    assert result.verification is not None
    assert result.verification.outcome is RecoveryVerificationOutcome.RECOVERED
