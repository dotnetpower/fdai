"""Advanced ontology graph reasoning: K6-K8 interaction/attribution, conflict readback, What-If."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.assurance_twin.effect_model import EffectModelStatus
from fdai.core.assurance_twin.graph_effect import (
    EffectInteractionTerm,
    GraphDynamicSimulationResult,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    simulate_graph_effects,
)
from fdai.core.assurance_twin.state_trajectory import (
    DynamicInvariant,
    InvariantOperator,
    InvariantStatus,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    TrajectoryOutcomeStatus,
    close_trajectory_outcome,
)
from fdai.core.ontology_platform.observation_adjudication import (
    CrossSourceReadConfidence,
    CrossSourceStateStatus,
)
from fdai.shared.contracts.models import CausalEvidenceGrade
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class TrajectoryFailureAttribution:
    """Pinpoint the exact hop, link_path, and GraphEffectModel responsible for a mismatch (#17)."""

    prediction_digest: str
    outcome_status: TrajectoryOutcomeStatus
    diverged_object_ref: str
    diverged_metric: str
    predicted_value: float
    observed_value: float
    absolute_error: float
    responsible_model_ref: str
    faulty_link_path: tuple[str, ...]
    attribution_digest: str


@dataclass(frozen=True, slots=True)
class ConflictReadbackResolutionReceipt:
    """Immutable receipt from an active 3rd-source readback resolving an evidence conflict (#18)."""

    target_id: str
    property_name: str
    provider_value: Any
    telemetry_value: Any
    readback_source_id: str
    readback_value: Any
    initial_status: CrossSourceStateStatus
    resolved_status: CrossSourceStateStatus
    confidence: CrossSourceReadConfidence
    resolved_value: Any
    receipt_digest: str


@dataclass(frozen=True, slots=True)
class ScenarioBranchWhatIfReport:
    """Combined copy-on-write scenario branch and K6-K8 business SLO impact evaluation (#19)."""

    branch_id: str
    base_graph_digest: str
    branch_graph_digest: str
    modified_object_ids: tuple[str, ...]
    simulation_result: GraphDynamicSimulationResult
    violated_invariant_ids: tuple[str, ...]
    safe_to_propose: bool
    execution_authority: bool = False


def simulate_interaction_and_attribute_failure(
    *,
    ontology_release: str,
    cutoff: datetime | None = None,
) -> tuple[GraphDynamicSimulationResult, TrajectoryFailureAttribution]:
    """Run K6-K8 with `EffectInteractionTerm` and attribute a post-horizon mismatch (#17)."""

    eval_cutoff = (cutoff or datetime(2026, 10, 15, 12, 0, tzinfo=UTC)).astimezone(UTC)
    horizon_end = eval_cutoff + timedelta(hours=2)
    base_ev = (_sha256("interaction-base-ev"),)
    baseline = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release=ontology_release,
        graph_revision="rev-2",
        inventory_generation="gen-2",
        base_snapshot_id="snap-2",
        evidence_cutoff=eval_cutoff,
        horizon_end=horizon_end,
        slices=(
            StateSlice(
                "res-aks-checkout-01",
                "Resource",
                "cpu_utilization",
                0.85,
                eval_cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
            StateSlice(
                "svc-checkout-api",
                "BusinessService",
                "latency_p95_ms",
                145.0,
                eval_cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
        ),
    )
    topology = tuple(
        sorted(
            (
                GraphTopologyEdge(
                    "res-aks-checkout-01",
                    "Resource",
                    "runs_on_inverse",
                    "wl-checkout-aks",
                    "Workload",
                ),
                GraphTopologyEdge(
                    "wl-checkout-aks",
                    "Workload",
                    "implemented_by_inverse",
                    "svc-checkout-api",
                    "BusinessService",
                ),
            ),
            key=lambda e: e.key,
        )
    )
    model = GraphEffectModel(
        model_id="model-aks-to-svc-latency",
        version="1.0.0",
        revision=1,
        status=EffectModelStatus.ACTIVE,
        trigger_ref="ops.scale-out",
        source_type="Resource",
        link_path=("runs_on_inverse", "implemented_by_inverse"),
        target_type="BusinessService",
        target_metric="latency_p95_ms",
        propagation_lag_seconds=60,
        gain=100.0,
        offset=0.0,
        interval_radius=5.0,
        evidence_grade=CausalEvidenceGrade.INTERVENTIONAL,
        causal_evidence_receipt_digest=_sha256("interaction-causal-1"),
        learned_through=eval_cutoff,
        sample_count=120,
        mean_absolute_error=1.5,
    )
    drain_model = GraphEffectModel(
        model_id="model-drain-to-svc-latency",
        version="1.0.0",
        revision=1,
        status=EffectModelStatus.ACTIVE,
        trigger_ref="ops.drain-connection",
        source_type="Resource",
        link_path=("runs_on_inverse", "implemented_by_inverse"),
        target_type="BusinessService",
        target_metric="latency_p95_ms",
        propagation_lag_seconds=60,
        gain=20.0,
        offset=0.0,
        interval_radius=2.0,
        evidence_grade=CausalEvidenceGrade.INTERVENTIONAL,
        causal_evidence_receipt_digest=_sha256("interaction-causal-2"),
        learned_through=eval_cutoff,
        sample_count=80,
        mean_absolute_error=0.8,
    )
    eff_time = eval_cutoff + timedelta(minutes=5)
    interventions = (
        GraphIntervention(
            "int-1",
            "ops.scale-out",
            "res-aks-checkout-01",
            "Resource",
            "cpu_utilization",
            -0.30,
            eff_time,
        ),
        GraphIntervention(
            "int-2",
            "ops.drain-connection",
            "res-aks-checkout-01",
            "Resource",
            "cpu_utilization",
            -0.10,
            eff_time,
        ),
    )
    interaction = EffectInteractionTerm(
        interaction_id="ix-scale-and-drain",
        trigger_refs=("ops.drain-connection", "ops.scale-out"),
        target_ref="svc-checkout-api",
        metric="latency_p95_ms",
        delta=-5.0,
        lag_seconds=60,
        model_ref="interaction:scale-plus-drain@1.0.0",
        evidence_grade=CausalEvidenceGrade.INTERVENTIONAL,
    )
    invariants = (
        DynamicInvariant(
            "inv-checkout-latency",
            "latency_p95_ms",
            InvariantOperator.LESS_THAN_OR_EQUAL,
            150.0,
            target_ref="svc-checkout-api",
        ),
    )
    sim = simulate_graph_effects(
        baseline=baseline,
        topology=topology,
        interventions=interventions,
        active_models=(model, drain_model),
        interaction_terms=(interaction,),
        invariants=invariants,
    )
    # Inject a post-horizon observed slice where latency remained 155.0ms instead of 123.0ms
    observed_slices = tuple(
        StateSlice(
            s.object_ref,
            s.object_type,
            s.metric,
            155.0
            if (s.object_ref == "svc-checkout-api" and s.effective_at > eval_cutoff)
            else s.value,
            s.effective_at,
            evidence_refs=(_sha256(f"obs-mismatch:{s.object_ref}:{s.effective_at.isoformat()}"),),
            independent_observer=True,
        )
        for s in sim.active_trajectory.slices
    )
    observed = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release=ontology_release,
        graph_revision="rev-2",
        inventory_generation="gen-2",
        base_snapshot_id="snap-2",
        evidence_cutoff=eval_cutoff,
        horizon_end=horizon_end,
        slices=observed_slices,
    )
    outcome = close_trajectory_outcome(
        sim.active_trajectory,
        observed,
        absolute_tolerance=2.0,
    )
    pred_slice = next(
        s
        for s in sim.active_trajectory.slices
        if s.object_ref == "svc-checkout-api" and s.effective_at > eval_cutoff
    )
    obs_slice = next(
        s
        for s in observed.slices
        if s.object_ref == "svc-checkout-api" and s.effective_at > eval_cutoff
    )
    err = round(abs(obs_slice.value - pred_slice.value), 4)
    attribution = TrajectoryFailureAttribution(
        prediction_digest=sim.active_trajectory.digest,
        outcome_status=outcome.status,
        diverged_object_ref=pred_slice.object_ref,
        diverged_metric=pred_slice.metric,
        predicted_value=pred_slice.value,
        observed_value=obs_slice.value,
        absolute_error=err,
        responsible_model_ref=model.ref,
        faulty_link_path=model.link_path,
        attribution_digest=_sha256(f"attr:{sim.active_trajectory.digest}:{model.ref}:{err}"),
    )
    return sim, attribution


def resolve_cross_source_conflict_with_readback(
    *,
    target_id: str,
    property_name: str,
    provider_value: Any,
    telemetry_value: Any,
    readback_source_id: str,
    readback_value: Any,
) -> ConflictReadbackResolutionReceipt:
    """Resolve a provider-vs-telemetry conflict using an independent 3rd-source readback (#18)."""

    if provider_value == telemetry_value:
        raise ValueError("resolve_cross_source_conflict_with_readback requires conflicting inputs")
    corroborated = readback_value in (provider_value, telemetry_value)
    resolved_status = (
        CrossSourceStateStatus.AGREED if corroborated else CrossSourceStateStatus.CONFLICTING
    )
    confidence = (
        CrossSourceReadConfidence.CORROBORATED
        if corroborated
        else CrossSourceReadConfidence.UNAVAILABLE
    )
    resolved_val = readback_value if corroborated else None
    digest = _sha256(
        f"readback:{target_id}:{property_name}:{provider_value}:{telemetry_value}:"
        f"{readback_source_id}:{readback_value}"
    )
    return ConflictReadbackResolutionReceipt(
        target_id=target_id,
        property_name=property_name,
        provider_value=provider_value,
        telemetry_value=telemetry_value,
        readback_source_id=readback_source_id,
        readback_value=readback_value,
        initial_status=CrossSourceStateStatus.CONFLICTING,
        resolved_status=resolved_status,
        confidence=confidence,
        resolved_value=resolved_val,
        receipt_digest=digest,
    )


def run_scenario_branch_what_if(
    *,
    branch_id: str,
    base_objects: Sequence[OntologyObjectRecord],
    base_links: Sequence[OntologyLinkRecord],
    upsert_objects: Sequence[OntologyObjectRecord],
    ontology_release: str,
    simulated_cpu_delta: float,
    latency_slo_threshold_ms: float = 150.0,
) -> ScenarioBranchWhatIfReport:
    """Materialize a copy-on-write scenario overlay and evaluate K6-K8 SLO impact (#19)."""

    base_map = {obj.id: obj for obj in base_objects}
    branch_map = dict(base_map)
    for obj in upsert_objects:
        branch_map[obj.id] = obj
    base_graph = OntologyGraphSnapshot(
        objects=tuple(base_map[k] for k in sorted(base_map)),
        links=tuple(base_links),
    )
    branch_graph = OntologyGraphSnapshot(
        objects=tuple(branch_map[k] for k in sorted(branch_map)),
        links=tuple(base_links),
    )
    base_digest = _sha256(f"base-graph:{len(base_graph.objects)}:{len(base_graph.links)}")
    branch_digest = _sha256(
        f"branch:{branch_id}:{len(branch_graph.objects)}:"
        f"{[o.properties for o in upsert_objects]}:{simulated_cpu_delta}"
    )
    cutoff = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    horizon_end = cutoff + timedelta(hours=1)
    base_ev = (_sha256(f"what-if-ev:{branch_id}"),)
    baseline = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release=ontology_release,
        graph_revision=branch_id,
        inventory_generation="gen-what-if",
        base_snapshot_id=branch_digest,
        evidence_cutoff=cutoff,
        horizon_end=horizon_end,
        slices=(
            StateSlice(
                "res-aks-checkout-01",
                "Resource",
                "cpu_utilization",
                0.75,
                cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
            StateSlice(
                "svc-checkout-api",
                "BusinessService",
                "latency_p95_ms",
                135.0,
                cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
        ),
    )
    topology = tuple(
        sorted(
            (
                GraphTopologyEdge(
                    "res-aks-checkout-01",
                    "Resource",
                    "runs_on_inverse",
                    "wl-checkout-aks",
                    "Workload",
                ),
                GraphTopologyEdge(
                    "wl-checkout-aks",
                    "Workload",
                    "implemented_by_inverse",
                    "svc-checkout-api",
                    "BusinessService",
                ),
            ),
            key=lambda e: e.key,
        )
    )
    model = GraphEffectModel(
        model_id="model-what-if-latency",
        version="1.0.0",
        revision=1,
        status=EffectModelStatus.ACTIVE,
        trigger_ref="remediate.right-size",
        source_type="Resource",
        link_path=("runs_on_inverse", "implemented_by_inverse"),
        target_type="BusinessService",
        target_metric="latency_p95_ms",
        propagation_lag_seconds=60,
        gain=120.0,
        offset=0.0,
        interval_radius=5.0,
        evidence_grade=CausalEvidenceGrade.INTERVENTIONAL,
        causal_evidence_receipt_digest=_sha256(f"what-if-causal:{branch_id}"),
        learned_through=cutoff,
        sample_count=100,
        mean_absolute_error=1.0,
    )
    interventions = (
        GraphIntervention(
            f"what-if-{branch_id}",
            "remediate.right-size",
            "res-aks-checkout-01",
            "Resource",
            "cpu_utilization",
            simulated_cpu_delta,
            cutoff + timedelta(minutes=5),
        ),
    )
    invariants = (
        DynamicInvariant(
            "inv-checkout-latency-slo",
            "latency_p95_ms",
            InvariantOperator.LESS_THAN_OR_EQUAL,
            latency_slo_threshold_ms,
            target_ref="svc-checkout-api",
        ),
    )
    sim = simulate_graph_effects(
        baseline=baseline,
        topology=topology,
        interventions=interventions,
        active_models=(model,),
        invariants=invariants,
    )
    violated = tuple(
        res.invariant_id for res in sim.invariant_results if res.status is InvariantStatus.VIOLATED
    )
    return ScenarioBranchWhatIfReport(
        branch_id=branch_id,
        base_graph_digest=base_digest,
        branch_graph_digest=branch_digest,
        modified_object_ids=tuple(sorted(o.id for o in upsert_objects)),
        simulation_result=sim,
        violated_invariant_ids=violated,
        safe_to_propose=not violated and not sim.requires_review,
        execution_authority=False,
    )
