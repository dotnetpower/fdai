"""End-to-end replay for ontology-gated shadow workflows and 3-loop value settlement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import fdai_service_contracts as sc
import yaml
from fdai.core.measurement.outcome_assurance import (
    FinalizedOutcomeEvent,
    OutcomeMeasurementObservation,
)
from fdai.core.measurement.value_claim import (
    CohortRole,
    ObservationLane,
    ValueClaimDeclaration,
    ValueClaimStatus,
    ValueCohortObservation,
    ValueDirection,
    ValueUnit,
)
from fdai.core.notifications.matrix import load_matrix_from_yaml
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.recent_resource_changes import (
    RecentResourceChange,
    RecentResourceChangeRead,
)
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.workflow import (
    AdmittedWorkflowGuardEvaluator,
    OntologyFunctionGateEvaluator,
    WorkflowApprovalPlanner,
    WorkflowOrchestrator,
)
from fdai.delivery.measurement.outcome_assurance_producer import (
    OutcomeAssuranceProjectionProducer,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.rule_catalog.schema.workflow import load_workflow_catalog
from fdai.runtime.control_loop_support import build_ontology_gate_reader
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import (
    InMemoryOntologyInstanceStore,
    InMemoryProcessRuntimeStore,
    InMemoryStateStore,
)

from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime.now(tz=UTC)
EARLIER = NOW - timedelta(hours=6)


def _metadata(*, cutoff: datetime = NOW, completeness: float = 1.0) -> dict[str, object]:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision="generation-1",
        effective_at=cutoff,
        recorded_at=cutoff,
        evidence_cutoff=cutoff,
        freshness_ceiling_seconds=3600,
        completeness=completeness,
        synthetic=False,
        evidence_refs=("inventory-generation:generation-1",),
    ).to_mapping()


class _RecentChangesStub:
    def __init__(self, *, complete: bool = True, failed: int = 0) -> None:
        self.complete = complete
        self.failed = failed

    async def read_recent_resource_changes(
        self, *, start_at: datetime, end_at: datetime, known_at: datetime, limit: int
    ) -> RecentResourceChangeRead:
        del start_at, end_at, known_at, limit
        changes = tuple(
            RecentResourceChange(
                subject_ref="res-target",
                subject_name="res-target",
                subject_type="compute",
                operation="write",
                operation_status="Failed",
                mutation_kind="update",
                observation_kind="activity",
                occurred_at=EARLIER,
                source_identity="source",
                evidence_ref=f"ev-{idx}",
            )
            for idx in range(self.failed)
        )
        return RecentResourceChangeRead(changes=changes, complete=self.complete)

    async def read_recent_resource_change_page(self, **_: object) -> object:
        raise AssertionError("paging is not used")


async def _build_graph(
    catalog, *, cutoff: datetime = NOW, include_service: bool = True
) -> InMemoryOntologyInstanceStore:
    store = InMemoryOntologyInstanceStore(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
    )
    long_ago = NOW - timedelta(days=30)
    await store.upsert_object(
        OntologyObjectRecord(
            id="res-target",
            object_type="Resource",
            properties={
                "id": "res-target",
                "type": "compute",
                "properties": {STATE_FACT_METADATA_PROPERTY: _metadata(cutoff=cutoff)},
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="wl-target",
            object_type="Workload",
            properties={
                "id": "wl-target",
                "name": "wl-target",
                "workload_kind": "service",
                "effective_from": long_ago,
                "source_ref": "catalog",
            },
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(link_type="workload_runs_on", from_id="wl-target", to_id="res-target")
    )
    if include_service:
        await store.upsert_object(
            OntologyObjectRecord(
                id="svc-target",
                object_type="BusinessService",
                properties={
                    "id": "svc-target",
                    "name": "svc-target",
                    "criticality": "low",
                    "effective_from": long_ago,
                    "source_ref": "catalog",
                },
            )
        )
        await store.upsert_link(
            OntologyLinkRecord(link_type="implemented_by", from_id="svc-target", to_id="wl-target")
        )
    await store.upsert_object(
        OntologyObjectRecord(
            id="window-1",
            object_type="ChangeWindow",
            properties={
                "id": "window-1",
                "window_kind": "maintenance",
                "scope_ref": "res-target",
                "status": "approved",
                "effective_from": NOW - timedelta(hours=1),
                "effective_to": NOW + timedelta(hours=2),
                "policy_ref": "policy-1",
            },
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="plan-1",
            object_type="RecoveryPlan",
            properties={
                "id": "plan-1",
                "strategy": "rollback",
                "status": "ready",
                "workflow_ref": "change-risk-gated-scale-in@1.0.0",
                "action_type_refs": ["ops.scale-in@1.0.0"],
                "compensation_order": ["scale_out"],
                "impact_envelope_id": "env-1",
                "recovery_objective_ref": "obj-1",
                "verification_probes": ["target_healthy"],
                "last_rehearsed_at": EARLIER,
                "expires_at": NOW + timedelta(days=7),
            },
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="recovery_targets_resource", from_id="plan-1", to_id="res-target"
        )
    )
    await store.upsert_object(
        OntologyObjectRecord(
            id="run-1",
            object_type="ActionRun",
            properties={
                "id": "run-1",
                "action_type_ref": "ops.scale-in",
                "action_type_version": "1.0.0",
                "target_ref": "res-target",
                "status": "dispatched",
                "mode": "shadow",
                "idempotency_key": "run-1",
                "started_at": EARLIER,
                "ended_at": EARLIER,
            },
        )
    )
    return store


async def test_shipped_gated_workflows_open_on_complete_evidence_and_shut_on_defects(
    monkeypatch,
) -> None:
    from fdai.runtime import control_loop_support

    registry = PackageResourceSchemaRegistry()
    catalog = load_ontology_catalog(
        REPO_ROOT / "rule-catalog",
        schema_registry=registry,
        probes_root=REPO_ROOT / "rule-catalog" / "probes",
    )
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=operational_function_types(catalog.function_types),
    )
    actions = {item.name: item for item in catalog.action_types}
    workflows = {
        item.name: item
        for item in load_workflow_catalog(
            REPO_ROOT / "rule-catalog" / "workflows",
            schema_registry=registry,
            action_type_names=set(actions),
        )
    }
    with (REPO_ROOT / "config" / "rbac-groups.yaml").open(encoding="utf-8") as handle:
        group_mapping = GroupMapping.from_config(yaml.safe_load(handle))
    planner = WorkflowApprovalPlanner(
        action_types=actions,
        group_mapping=group_mapping,
        matrix=load_matrix_from_yaml(REPO_ROOT / "config" / "notifications-matrix.yaml"),
    )

    monkeypatch.setattr(
        control_loop_support,
        "_recent_change_reader",
        lambda _env: _RecentChangesStub(complete=True, failed=0),
    )
    now = datetime.now(tz=UTC)
    complete_store = await _build_graph(catalog, cutoff=now)
    bound = build_ontology_gate_reader(
        catalog_root=REPO_ROOT / "rule-catalog",
        ontology_store=complete_store,
        ontology_release=release,
        audit_store=InMemoryStateStore(),
        environment={},
        clock=lambda: now,
    )
    assert bound is not None
    reader, max_age = bound

    # 1. Complete, fresh, admitted evidence opens both shipped gates -> waiting for approval
    admitted_guard = AdmittedWorkflowGuardEvaluator(
        inner=OntologyFunctionGateEvaluator(reader=reader, max_reading_age=max_age),
        decision_evidence_provider=StubDecisionEvidenceAdmissionProvider(
            lambda: datetime.now(tz=UTC)
        ),
    )
    orchestrator = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=admitted_guard,
    )
    for wf_name in ("blast-radius-gated-service-restart", "change-risk-gated-scale-in"):
        run = await orchestrator.run(
            workflows[wf_name],
            target_resource_id="res-target",
            trigger_ts=now,
            context={"requester.principal": "operator-1"},
        )
        assert run.status is ProcessStatus.WAITING
        assert run.step_results[0].reason == "gate_passed"
        assert run.step_results[1].reason == "waiting_for_approval"

    # 2. Unauthorized (missing decision-evidence admission) keeps both gates shut
    unadmitted_guard = AdmittedWorkflowGuardEvaluator(
        inner=OntologyFunctionGateEvaluator(reader=reader, max_reading_age=max_age),
        decision_evidence_provider=None,
    )
    unadmitted_orch = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=unadmitted_guard,
    )
    for wf_name in ("blast-radius-gated-service-restart", "change-risk-gated-scale-in"):
        run = await unadmitted_orch.run(
            workflows[wf_name],
            target_resource_id="res-target",
            trigger_ts=now,
            context={"requester.principal": "operator-1"},
        )
        assert run.status is ProcessStatus.FAILED
        assert run.step_results[0].reason == "gate_blocked"

    # 3. Incomplete evidence (unmapped service criticality) keeps both gates shut
    incomplete_store = await _build_graph(catalog, cutoff=now, include_service=False)
    inc_bound = build_ontology_gate_reader(
        catalog_root=REPO_ROOT / "rule-catalog",
        ontology_store=incomplete_store,
        ontology_release=release,
        audit_store=InMemoryStateStore(),
        environment={},
        clock=lambda: now,
    )
    assert inc_bound is not None
    inc_orch = WorkflowOrchestrator(
        planner=planner,
        action_types=actions,
        audit_store=InMemoryStateStore(),
        process_store=InMemoryProcessRuntimeStore(),
        guard_evaluator=AdmittedWorkflowGuardEvaluator(
            inner=OntologyFunctionGateEvaluator(reader=inc_bound[0], max_reading_age=inc_bound[1]),
            decision_evidence_provider=StubDecisionEvidenceAdmissionProvider(
                lambda: datetime.now(tz=UTC)
            ),
        ),
    )
    for wf_name in ("blast-radius-gated-service-restart", "change-risk-gated-scale-in"):
        run = await inc_orch.run(
            workflows[wf_name],
            target_resource_id="res-target",
            trigger_ts=now,
            context={"requester.principal": "operator-1"},
        )
        assert run.status is ProcessStatus.FAILED
        assert run.step_results[0].reason == "gate_blocked"


async def test_three_value_loops_settle_independently_and_publish_to_outcome_assurance() -> None:
    store = InMemoryStateStore()
    producer = OutcomeAssuranceProjectionProducer(store=store)
    loops = (
        (
            "claim-resilience-mttr",
            "blast-radius-gated-service-restart",
            "objective.resilience.mttr@1.0.0",
            "mttr_seconds",
            ValueUnit.DURATION_SECONDS,
            None,
            Decimal("300"),
            ("600", "610", "590", "605", "595", "600"),
            ("240", "250", "235", "245", "240", "238"),
        ),
        (
            "claim-change-safety-lead-time",
            "change-risk-gated-scale-in",
            "objective.change-safety.lead-time@1.0.0",
            "lead_time_seconds",
            ValueUnit.DURATION_SECONDS,
            None,
            Decimal("400"),
            ("900", "920", "880", "910", "890", "905"),
            ("350", "360", "340", "355", "345", "350"),
        ),
        (
            "claim-cost-governance-savings",
            "predictive-scale",
            "objective.cost-governance.unit-cost@1.0.0",
            "hourly_waste_usd",
            ValueUnit.COST_AMOUNT,
            "USD",
            Decimal("20"),
            ("45", "48", "44", "46", "47", "45"),
            ("15", "16", "14", "15", "16", "14"),
        ),
    )
    claim_cohorts = []
    events = []
    observations = []
    for idx, (
        claim_id,
        wf_ref,
        obj_ref,
        metric_name,
        unit,
        currency,
        target,
        base_vals,
        treat_vals,
    ) in enumerate(loops, start=1):
        decl = ValueClaimDeclaration(
            claim_id=claim_id,
            workflow_ref=wf_ref,
            workflow_version="1.0.0",
            objective_ref=obj_ref,
            metric_name=metric_name,
            unit=unit,
            currency=currency,
            direction=ValueDirection.DECREASE_IS_BETTER,
            target_value=target,
            scenario_set_version="scenarios-v1",
            window_start=NOW - timedelta(days=30),
            window_end=NOW - timedelta(days=1),
            min_samples_per_cohort=5,
        )
        base = ValueCohortObservation(
            role=CohortRole.BASELINE,
            lane=ObservationLane.INDEPENDENT_OBSERVATION,
            scenario_set_version="scenarios-v1",
            currency=currency,
            complete=True,
            samples=tuple(Decimal(v) for v in base_vals),
            evidence_refs=(f"evidence:baseline:{claim_id}",),
            observed_at=NOW,
        )
        treat = ValueCohortObservation(
            role=CohortRole.TREATMENT,
            lane=ObservationLane.INDEPENDENT_OBSERVATION,
            scenario_set_version="scenarios-v1",
            currency=currency,
            complete=True,
            samples=tuple(Decimal(v) for v in treat_vals),
            evidence_refs=(f"evidence:treatment:{claim_id}",),
            observed_at=NOW,
        )
        claim_cohorts.append((decl, (base, treat)))
        events.append(
            FinalizedOutcomeEvent(
                event_id=f"ev-{idx}",
                finalized_at=NOW,
                decision_case_id=f"case-{idx}",
                protected_objective_ref=obj_ref,
                workflow_ref=wf_ref,
                action_type_id="ops.scale-in@1.0.0",
                action_run_id=f"run-{idx}",
                observed_outcome_ref=f"obs-outcome-{idx}",
                evidence_refs=(f"audit:event-{idx}",),
            )
        )
        observations.append(
            OutcomeMeasurementObservation(
                observation_id=f"obs-{idx}",
                event_id=f"ev-{idx}",
                objective_ref=obj_ref,
                metric=metric_name,
                value=float(treat_vals[0]),
                observed_at=NOW,
                recorded_at=NOW,
                evidence_ref=f"measurement:{metric_name}",
            )
        )

    receipt, settlements = await producer.settle_and_publish_value_claims(
        principal_id="operator-1",
        scope=sc.OutcomeAssuranceScope(scope_ref="global"),
        window=sc.OutcomeAssuranceWindow(
            start=NOW - timedelta(days=30),
            end=NOW,
            label="30d",
            scenario_set_version="scenarios-v1",
        ),
        sources=(
            sc.OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=sc.OutcomeAssuranceSourceState.COMPLETE,
                observed_at=NOW,
                expires_at=NOW + timedelta(days=1),
                evidence_refs=("measurement:all-three-loops",),
            ),
        ),
        readiness=(
            sc.OutcomeAssuranceReadiness(
                facet=sc.OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=sc.OutcomeAssuranceReadinessState.READY,
                observed_at=NOW,
                expires_at=NOW + timedelta(days=1),
                evidence_refs=("readiness:measurement",),
            ),
        ),
        finalized_events=tuple(events),
        observations=tuple(observations),
        claim_cohorts=tuple(claim_cohorts),
        guards=sc.OutcomeAssuranceControlSummary(
            state=sc.OutcomeAssuranceGuardState.HEALTHY,
            guard_evaluations=(
                sc.OutcomeAssuranceGuardEvaluation(
                    guard_id="policy_escape_zero",
                    threshold=0.0,
                    observed_value=0.0,
                    passed=True,
                    evidence_ref="guard:policy-escape-zero",
                ),
            ),
            evidence_refs=("promotion:three-loops",),
        ),
        as_of=NOW,
    )

    assert receipt.state is sc.OutcomeAssuranceReadState.COMPLETE
    assert len(settlements) == 3
    for settlement in settlements:
        assert settlement.status is ValueClaimStatus.IMPROVED
        assert settlement.conservative_total_improvement is not None
        assert settlement.conservative_total_improvement > Decimal(0)
