"""Simulated business ontology projection, 52-rule objective bindings, and K6-K8 closure."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai.core.assurance_twin.effect_model import EffectModelStatus
from fdai.core.assurance_twin.graph_effect import (
    GraphDynamicSimulationResult,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    simulate_graph_effects,
)
from fdai.core.assurance_twin.state_trajectory import (
    DynamicInvariant,
    InvariantOperator,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
)
from fdai.core.assurance_twin.trajectory_ledger import (
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryClosure,
)
from fdai.core.ontology_platform.catalog_projection import CatalogOntologyProjection
from fdai.core.ontology_platform.simulated_business_model_seed import (
    build_simulated_business_operating_model,
    project_all_authored_rule_objectives,
)
from fdai.core.operational_context.materializer import OperationalContextMaterializer
from fdai.core.operational_context.models import OperationalContextSnapshot, SourceFreshness
from fdai.core.operational_context.operating_scope import (
    OperatingScopeCoverage,
    project_operating_scope,
)
from fdai.core.operational_context.projector import OperatingModelProjector
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.rule_objective_binding import RuleObjectiveBindingMigrationReport
from fdai.shared.contracts.models import CausalEvidenceGrade, Rule
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyObjectRecord
from fdai.shared.providers.operating_model import OperatingModelSnapshot
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _sha256(seed: str) -> str:
    return f"sha256:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class SimulatedBusinessOntologyResult:
    """Verified business ontology graph, context snapshots, rule bindings, and K6-K8 closure."""

    snapshot: OperatingModelSnapshot
    scope_coverage: OperatingScopeCoverage
    context_snapshots: tuple[OperationalContextSnapshot, ...]
    rule_binding_projection: CatalogOntologyProjection
    rule_migration_report: RuleObjectiveBindingMigrationReport
    dynamic_simulation: GraphDynamicSimulationResult
    trajectory_closure: TrajectoryClosure
    store: OntologyInstanceStore


@dataclass(frozen=True, slots=True)
class BusinessConceptAnswer:
    """Structured answer resolved across BusinessCapability, BusinessService, and Objectives."""

    service_id: str
    service_name: str
    criticality: str
    capability_ids: tuple[str, ...]
    workload_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]
    service_objective_ids: tuple[str, ...]
    recovery_objective_ids: tuple[str, ...]
    cost_objective_ids: tuple[str, ...]
    budget_ids: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    ownership_ids: tuple[str, ...]


async def run_simulated_business_ontology_suite(
    *,
    catalog: OntologyCatalog,
    rules: Sequence[Rule],
    repo_root: Path,
    cutoff: datetime | None = None,
) -> SimulatedBusinessOntologyResult:
    """Project the business ontology, materialize all contexts, and close K6-K8 trajectories."""

    eval_cutoff = (cutoff or datetime(2026, 10, 15, 12, 0, tzinfo=UTC)).astimezone(UTC)
    release = catalog.build_release()
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    projector = OperatingModelProjector(
        store=store,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    snapshot = build_simulated_business_operating_model()
    await projector.project(snapshot)
    scope_coverage = project_operating_scope(snapshot)
    freshness = (
        SourceFreshness("source:approved-enterprise-service-catalog", eval_cutoff, 86400),
        SourceFreshness("source:azure-monitor-sli", eval_cutoff, 3600),
        SourceFreshness("source:dr-drill-verifier", eval_cutoff, 86400),
        SourceFreshness("source:finops-cost-export", eval_cutoff, 86400),
        SourceFreshness("policy:zone-redundancy", eval_cutoff, 86400),
    )
    materializer = OperationalContextMaterializer(
        store=store,
        clock=lambda: eval_cutoff,
        catalog_versions={"ontology": release.digest},
    )
    resource_ids = tuple(
        sorted(obj.id for obj in snapshot.objects if obj.object_type == "Resource")
    )
    contexts = tuple(
        [
            await materializer.materialize(
                target_resource_id=res_id,
                cutoff=eval_cutoff,
                catalog_versions={"ontology": release.digest},
                source_freshness=freshness,
            )
            for res_id in resource_ids
        ]
    )
    rule_projection, migration_report = project_all_authored_rule_objectives(
        rules=rules,
        repo_root=repo_root,
    )
    horizon_end = eval_cutoff + timedelta(days=7)
    base_ev = (_sha256("base-slice-evidence"),)
    base_traj = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release=release.digest,
        graph_revision="rev-1",
        inventory_generation="gen-1",
        base_snapshot_id="snap-1",
        evidence_cutoff=eval_cutoff,
        horizon_end=horizon_end,
        slices=(
            StateSlice(
                "obj-slo-checkout",
                "ServiceObjective",
                "availability",
                0.999,
                eval_cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
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
                140.0,
                eval_cutoff,
                evidence_refs=base_ev,
                independent_observer=True,
            ),
            StateSlice(
                "wl-checkout-aks",
                "Workload",
                "pod_ready_ratio",
                0.98,
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
                    "svc-checkout-api",
                    "BusinessService",
                    "service_has_service_objective",
                    "obj-slo-checkout",
                    "ServiceObjective",
                ),
                GraphTopologyEdge(
                    "wl-checkout-aks",
                    "Workload",
                    "implemented_by_inverse",
                    "svc-checkout-api",
                    "BusinessService",
                ),
            ),
            key=lambda edge: edge.key,
        )
    )
    models = (
        GraphEffectModel(
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
            causal_evidence_receipt_digest=_sha256("k6-k8-causal-receipt"),
            learned_through=eval_cutoff,
            sample_count=120,
            mean_absolute_error=1.2,
        ),
    )
    interventions = (
        GraphIntervention(
            intervention_id="int-scale-out-1",
            trigger_ref="ops.scale-out",
            source_ref="res-aks-checkout-01",
            source_type="Resource",
            metric="cpu_utilization",
            delta=-0.25,
            effective_at=eval_cutoff + timedelta(minutes=5),
        ),
    )
    invariants = (
        DynamicInvariant(
            invariant_id="inv-checkout-latency-slo",
            metric="latency_p95_ms",
            operator=InvariantOperator.LESS_THAN_OR_EQUAL,
            threshold=150.0,
            target_ref="svc-checkout-api",
        ),
    )
    sim_result = simulate_graph_effects(
        baseline=base_traj,
        topology=topology,
        interventions=interventions,
        active_models=models,
        invariants=invariants,
    )
    ledger = StateStoreTrajectoryEpisodeLedger(InMemoryStateStore())
    await ledger.record_prediction(
        sim_result.active_trajectory,
        challenger_model_refs=("model-aks-to-svc-latency@1.0.0:r1",),
        recorded_by="Heimdall",
        recorded_at=eval_cutoff,
    )
    observed_traj = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release=release.digest,
        graph_revision="rev-1",
        inventory_generation="gen-1",
        base_snapshot_id="snap-1",
        evidence_cutoff=eval_cutoff,
        horizon_end=horizon_end,
        slices=tuple(
            StateSlice(
                s.object_ref,
                s.object_type,
                s.metric,
                s.value,
                s.effective_at,
                evidence_refs=(_sha256(f"obs-slice:{s.object_ref}:{s.metric}"),),
                independent_observer=True,
            )
            for s in sim_result.active_trajectory.slices
        ),
    )
    closure = await ledger.close(
        prediction_digest=sim_result.active_trajectory.digest,
        observed=observed_traj,
        recorded_at=horizon_end + timedelta(minutes=10),
        absolute_tolerance=1.0,
    )
    return SimulatedBusinessOntologyResult(
        snapshot=snapshot,
        scope_coverage=scope_coverage,
        context_snapshots=contexts,
        rule_binding_projection=rule_projection,
        rule_migration_report=migration_report,
        dynamic_simulation=sim_result,
        trajectory_closure=closure,
        store=store,
    )


async def answer_business_concept_query(
    store: OntologyInstanceStore,
    *,
    query_term: str,
) -> BusinessConceptAnswer | None:
    """Resolve a BusinessService by ID, name, or bilingual alias and join all business facets."""

    normalized = query_term.strip().casefold()
    if not normalized:
        return None
    graph = await store.query_objects(
        object_types=("BusinessService",),
        limit=100,
        include_relationships=False,
    )
    matched: OntologyObjectRecord | None = None
    for obj in graph.objects:
        aliases = [str(a).casefold() for a in obj.properties.get("aliases", ())]
        if (
            obj.id.casefold() == normalized
            or str(obj.properties.get("name", "")).casefold() == normalized
            or normalized in aliases
        ):
            matched = obj
            break
    if matched is None:
        return None
    neighborhood = await store.traverse(
        root_ids=(matched.id,),
        root_object_types=("BusinessService",),
        link_types=(
            "delivered_by",
            "implemented_by",
            "workload_runs_on",
            "service_has_service_objective",
            "service_has_recovery_objective",
            "service_has_cost_objective",
            "service_has_budget",
            "service_has_architecture_constraint",
            "service_owned_by",
        ),
        direction="both",
        max_depth=3,
    )
    by_type: dict[str, list[str]] = {}
    for item in neighborhood.objects:
        by_type.setdefault(item.object_type, []).append(item.id)

    def _ids(t: str) -> tuple[str, ...]:
        return tuple(sorted(set(by_type.get(t, ()))))

    return BusinessConceptAnswer(
        service_id=matched.id,
        service_name=str(matched.properties.get("name", matched.id)),
        criticality=str(matched.properties.get("criticality", "unknown")),
        capability_ids=_ids("BusinessCapability"),
        workload_ids=_ids("Workload"),
        resource_ids=_ids("Resource"),
        service_objective_ids=_ids("ServiceObjective"),
        recovery_objective_ids=_ids("RecoveryObjective"),
        cost_objective_ids=_ids("CostObjective"),
        budget_ids=_ids("Budget"),
        constraint_ids=_ids("ArchitectureConstraint"),
        ownership_ids=_ids("Ownership"),
    )
