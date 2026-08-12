from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    EffectModelStatus,
    GraphDynamicRuntimeCoordinator,
    GraphEffectModel,
    InvariantOperator,
    InvariantStatus,
)
from fdai.core.operational_context import (
    OperationalContextEvidenceLink,
    OperationalContextEvidencePath,
    OperationalContextSnapshot,
    SourceFreshness,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.delivery.azure.graph_dynamic_evidence import (
    AzureGraphDynamicSimulationRequestProvider,
    AzureGraphEvidencePins,
    AzureGraphInterventionPolicy,
    AzureGraphInventoryEvidence,
    AzureGraphMetricEvidence,
    AzureGraphMetricObservation,
    AzureGraphTopologyEvidence,
    AzureReviewedMetricSemantic,
)
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    Autonomy,
    BlastRadiusComputation,
    Event,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_NOW = datetime(2026, 8, 12, 12, tzinfo=UTC)
_RELEASE = "sha256:" + "a" * 64
_TARGET = "workload:api"
_ACTION_TYPE = "ops.scale-out"


def _state_metadata(
    *,
    synthetic: bool = False,
    conflicts: tuple[str, ...] = (),
    completeness: float = 1.0,
    recorded_at: datetime = _NOW,
) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="azure-inventory",
        source_revision="inventory-7",
        effective_at=_NOW - timedelta(seconds=10),
        recorded_at=recorded_at,
        evidence_cutoff=_NOW,
        freshness_ceiling_seconds=60,
        completeness=completeness,
        synthetic=synthetic,
        conflicts=conflicts,
        evidence_refs=("evidence:inventory:7",),
    )


def _link_metadata() -> LinkObservationMetadata:
    return LinkObservationMetadata(
        state_fact=_state_metadata(),
        verification_method="independent-source",
        verified=True,
        verifier_identity="topology-verifier",
        verifier_revision="verifier-3",
        verification_receipt_ref="verification:topology:3",
        inventory_generation="inventory-7",
        mapping_id="azure-resource-service",
        mapping_revision="mapping-2",
        source_schema_version="2026-01-01",
        source_schema_digest="sha256:" + "b" * 64,
    )


def _pins(**changes: object) -> AzureGraphEvidencePins:
    values: dict[str, object] = {
        "ontology_release": _RELEASE,
        "graph_revision": "graph-4",
        "inventory_generation": "inventory-7",
        "evidence_cutoff": _NOW,
        "base_snapshot_id": "snapshot-9",
        "target_revision": 3,
        "model_cutoff": _NOW,
    }
    values.update(changes)
    return AzureGraphEvidencePins(**values)  # type: ignore[arg-type]


def _objects() -> tuple[OntologyObjectRecord, ...]:
    return (
        OntologyObjectRecord(_TARGET, "Workload", {"id": _TARGET}, revision=3),
        OntologyObjectRecord("service:api", "BusinessService", {"id": "service:api"}, revision=2),
        OntologyObjectRecord(
            "objective:service", "ServiceObjective", {"threshold": 60.0}, revision=4
        ),
        OntologyObjectRecord("objective:cost", "CostObjective", {"threshold": 50.0}, revision=5),
        OntologyObjectRecord(
            "objective:recovery", "RecoveryObjective", {"threshold": 30.0}, revision=6
        ),
        OntologyObjectRecord(
            "constraint:architecture",
            "ArchitectureConstraint",
            {"threshold": 5.0},
            revision=7,
        ),
    )


def _topology(*, graph: OntologyGraphSnapshot | None = None) -> AzureGraphTopologyEvidence:
    metadata = _link_metadata()
    return AzureGraphTopologyEvidence(
        pins=_pins(),
        graph=graph
        or OntologyGraphSnapshot(
            objects=_objects(),
            links=(
                OntologyLinkRecord(
                    "implements",
                    _TARGET,
                    "service:api",
                    {LINK_OBSERVATION_METADATA_PROPERTY: metadata.to_mapping()},
                ),
            ),
        ),
    )


def _context(**changes: object) -> OperationalContextSnapshot:
    metadata = _link_metadata()
    objects = _objects()
    values: dict[str, object] = {
        "snapshot_id": "snapshot-9",
        "target_resource_id": _TARGET,
        "cutoff": _NOW,
        "recorded_at": _NOW + timedelta(seconds=1),
        "catalog_versions": (("ontology", _RELEASE),),
        "service_ids": ("service:api",),
        "workload_ids": (_TARGET,),
        "objective_ids": (
            "objective:service",
            "objective:cost",
            "objective:recovery",
        ),
        "service_objective_ids": ("objective:service",),
        "recovery_objective_ids": ("objective:recovery",),
        "cost_objective_ids": ("objective:cost",),
        "constraint_ids": ("constraint:architecture",),
        "ownership_ids": (),
        "dependency_ids": (),
        "source_freshness": (SourceFreshness("azure", _NOW - timedelta(seconds=10), 60),),
        "evidence_links": (
            OperationalContextEvidenceLink("implements", _TARGET, "service:api", metadata),
        ),
        "evidence_paths": tuple(
            OperationalContextEvidencePath(
                object_id=item.id,
                object_type=item.object_type,
                revision=item.revision,
                effective_from=_NOW - timedelta(days=1),
                effective_to=None,
                provenance_refs=(f"provenance:{item.id}",),
                links=(),
            )
            for item in objects
        ),
        "temporal_exclusions": (),
        "stale_sources": (),
        "conflicts": (),
        "autonomy_ceiling": Autonomy.ENFORCE_HIL,
    }
    values.update(changes)
    return OperationalContextSnapshot(**values)  # type: ignore[arg-type]


def _inventory(**changes: object) -> AzureGraphInventoryEvidence:
    values: dict[str, object] = {
        "pins": _pins(),
        "target_ref": _TARGET,
        "target_type": "Workload",
        "observed_at": _NOW,
        "evidence_refs": ("evidence:inventory:7",),
    }
    values.update(changes)
    return AzureGraphInventoryEvidence(**values)  # type: ignore[arg-type]


def _semantic(
    objective_ref: str,
    objective_type: str,
    revision: int,
    metric: str,
    target_ref: str,
) -> AzureReviewedMetricSemantic:
    return AzureReviewedMetricSemantic(
        semantic_ref=f"semantic:{objective_ref}",
        objective_ref=objective_ref,
        objective_type=objective_type,
        objective_revision=revision,
        metric=metric,
        operator=InvariantOperator.LESS_THAN_OR_EQUAL,
        target_ref=target_ref,
        effective_from=_NOW - timedelta(days=1),
        effective_to=None,
        reviewed_at=_NOW,
        review_receipt_ref=f"review:{objective_ref}",
        threshold_property="threshold",
    )


def _metrics(
    *,
    metadata: StateFactMetadata | None = None,
    **changes: object,
) -> AzureGraphMetricEvidence:
    state_metadata = metadata or _state_metadata()
    values: dict[str, object] = {
        "pins": _pins(),
        "observations": (
            AzureGraphMetricObservation(_TARGET, "Workload", "replicas", 2.0, state_metadata),
            AzureGraphMetricObservation(
                _TARGET, "Workload", "affected_resources", 1.0, state_metadata
            ),
            AzureGraphMetricObservation(
                _TARGET, "Workload", "architecture_score", 1.0, state_metadata
            ),
            AzureGraphMetricObservation(
                "service:api", "BusinessService", "latency", 50.0, state_metadata
            ),
            AzureGraphMetricObservation(
                "service:api", "BusinessService", "cost", 20.0, state_metadata
            ),
            AzureGraphMetricObservation(
                "service:api", "BusinessService", "recovery_minutes", 10.0, state_metadata
            ),
        ),
        "semantics": (
            _semantic("objective:service", "ServiceObjective", 4, "latency", "service:api"),
            _semantic("objective:cost", "CostObjective", 5, "cost", "service:api"),
            _semantic(
                "objective:recovery",
                "RecoveryObjective",
                6,
                "recovery_minutes",
                "service:api",
            ),
            _semantic(
                "constraint:architecture",
                "ArchitectureConstraint",
                7,
                "architecture_score",
                _TARGET,
            ),
        ),
    }
    values.update(changes)
    return AzureGraphMetricEvidence(**values)  # type: ignore[arg-type]


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "graph-event-1",
            "source": "azure-monitor",
            "event_type": "capacity-pressure",
            "resource_ref": _TARGET,
            "detected_at": _NOW.isoformat(),
            "ingested_at": (_NOW + timedelta(seconds=1)).isoformat(),
            "mode": "shadow",
            "payload": {},
        }
    )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="signature-1",
        rule_id="learned.capacity-pressure",
        action_type=_ACTION_TYPE,
        params={},
        incident_id="incident-1",
        success_rate=0.99,
    )


def _action_type() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=_ACTION_TYPE,
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        promotion_gate=PromotionGate(
            min_shadow_days=7,
            min_samples=50,
            min_accuracy=0.99,
            max_policy_escapes=0,
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            max_affected_resources=3,
        ),
    )


class _ContextSource:
    def __init__(self, context: OperationalContextSnapshot | None = None) -> None:
        self.context = context if context is not None else _context()

    async def get(
        self, *, event: Event, action: LearnedAction
    ) -> OperationalContextSnapshot | None:
        del event, action
        return self.context


class _Reader:
    def __init__(self, value: object, *, barrier: _Barrier | None = None) -> None:
        self.value = value
        self.barrier = barrier

    async def read(self, *, context: OperationalContextSnapshot) -> object:
        del context
        if self.barrier is not None:
            await self.barrier.enter()
        return self.value


class _Barrier:
    def __init__(self) -> None:
        self.started = 0
        self.all_started = asyncio.Event()

    async def enter(self) -> None:
        self.started += 1
        if self.started == 3:
            self.all_started.set()
        await self.all_started.wait()


class _BlockingReader:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def read(self, *, context: OperationalContextSnapshot) -> object:
        del context
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("blocking reader unexpectedly resumed")


def _provider(
    *,
    context: OperationalContextSnapshot | None = None,
    topology: AzureGraphTopologyEvidence | object | None = None,
    inventory: AzureGraphInventoryEvidence | object | None = None,
    metrics: AzureGraphMetricEvidence | object | None = None,
    read_timeout_seconds: float = 0.1,
    build_timeout_seconds: float = 0.2,
) -> AzureGraphDynamicSimulationRequestProvider:
    return AzureGraphDynamicSimulationRequestProvider(
        contexts=_ContextSource(context),
        topology=_Reader(_topology() if topology is None else topology),  # type: ignore[arg-type]
        inventory=_Reader(_inventory() if inventory is None else inventory),  # type: ignore[arg-type]
        metrics=_Reader(_metrics() if metrics is None else metrics),  # type: ignore[arg-type]
        action_types={_ACTION_TYPE: _action_type()},
        policies={
            _ACTION_TYPE: AzureGraphInterventionPolicy(
                metric="replicas",
                delta=1.0,
                max_abs_delta=2.0,
                horizon=timedelta(minutes=5),
                divergence_threshold=0.5,
            )
        },
        read_timeout_seconds=read_timeout_seconds,
        build_timeout_seconds=build_timeout_seconds,
    )


async def test_provider_builds_pinned_no_action_and_bounded_intervention() -> None:
    request = await asyncio.wait_for(
        _provider().build(event=_event(), action=_action()), timeout=0.5
    )

    assert request is not None
    assert request.baseline.ontology_release == _RELEASE
    assert request.baseline.graph_revision == "graph-4"
    assert request.baseline.inventory_generation == "inventory-7"
    assert request.baseline.base_snapshot_id == "snapshot-9"
    assert request.baseline.evidence_cutoff == _NOW
    assert "branch:no-action" in request.baseline.source_watermarks
    assert request.interventions[0].metric == "replicas"
    assert request.interventions[0].delta == 1.0
    assert {item.invariant_id for item in request.invariants} == {
        "semantic:objective:service",
        "semantic:objective:cost",
        "semantic:objective:recovery",
        "semantic:constraint:architecture",
        "action-type.blast-radius",
    }
    blast_radius = next(
        item for item in request.invariants if item.invariant_id == "action-type.blast-radius"
    )
    assert blast_radius.threshold == 3.0


async def test_provider_runs_independent_evidence_reads_concurrently() -> None:
    barrier = _Barrier()
    provider = AzureGraphDynamicSimulationRequestProvider(
        contexts=_ContextSource(),
        topology=_Reader(_topology(), barrier=barrier),  # type: ignore[arg-type]
        inventory=_Reader(_inventory(), barrier=barrier),  # type: ignore[arg-type]
        metrics=_Reader(_metrics(), barrier=barrier),  # type: ignore[arg-type]
        action_types={_ACTION_TYPE: _action_type()},
        policies={
            _ACTION_TYPE: AzureGraphInterventionPolicy(
                metric="replicas",
                delta=1.0,
                max_abs_delta=1.0,
                horizon=timedelta(minutes=1),
            )
        },
        read_timeout_seconds=0.1,
        build_timeout_seconds=0.2,
    )

    request = await asyncio.wait_for(provider.build(event=_event(), action=_action()), timeout=0.5)

    assert request is not None
    assert barrier.started == 3


@pytest.mark.parametrize(
    ("context", "topology", "inventory", "metrics"),
    [
        (_context(stale_sources=("azure",)), _topology(), _inventory(), _metrics()),
        (_context(conflicts=("target-revision",)), _topology(), _inventory(), _metrics()),
        (_context(), replace(_topology(), complete=False), _inventory(), _metrics()),
        (_context(), replace(_topology(), synthetic=True), _inventory(), _metrics()),
        (_context(), replace(_topology(), conflicts=("edge",)), _inventory(), _metrics()),
        (
            _context(),
            replace(_topology(), graph=replace(_topology().graph, truncated=True)),
            _inventory(),
            _metrics(),
        ),
        (_context(), _topology(), replace(_inventory(), complete=False), _metrics()),
        (_context(), _topology(), replace(_inventory(), truncated=True), _metrics()),
        (_context(), _topology(), replace(_inventory(), synthetic=True), _metrics()),
        (_context(), _topology(), replace(_inventory(), conflicts=("target",)), _metrics()),
        (
            _context(),
            _topology(),
            replace(_inventory(), observed_at=_NOW + timedelta(seconds=1)),
            _metrics(),
        ),
        (_context(), _topology(), _inventory(), replace(_metrics(), complete=False)),
        (_context(), _topology(), _inventory(), replace(_metrics(), truncated=True)),
        (_context(), _topology(), _inventory(), replace(_metrics(), synthetic=True)),
        (_context(), _topology(), _inventory(), replace(_metrics(), conflicts=("metric",))),
        (
            _context(),
            _topology(),
            _inventory(),
            _metrics(metadata=_state_metadata(synthetic=True)),
        ),
        (
            _context(),
            _topology(),
            _inventory(),
            _metrics(metadata=_state_metadata(completeness=0.5)),
        ),
        (
            _context(),
            _topology(),
            _inventory(),
            _metrics(metadata=_state_metadata(conflicts=("telemetry",))),
        ),
        (
            _context(),
            _topology(),
            replace(_inventory(), pins=_pins(graph_revision="graph-future")),
            _metrics(),
        ),
    ],
    ids=(
        "stale-context",
        "conflicting-context",
        "incomplete-topology",
        "synthetic-topology",
        "conflicting-topology",
        "truncated-topology",
        "incomplete-inventory",
        "truncated-inventory",
        "synthetic-inventory",
        "conflicting-inventory",
        "future-inventory",
        "incomplete-metrics",
        "truncated-metrics",
        "synthetic-metrics",
        "conflicting-metrics",
        "synthetic-state-fact",
        "partial-state-fact",
        "conflicting-state-fact",
        "pin-mismatch",
    ),
)
async def test_provider_holds_unusable_evidence(
    context: OperationalContextSnapshot,
    topology: AzureGraphTopologyEvidence,
    inventory: AzureGraphInventoryEvidence,
    metrics: AzureGraphMetricEvidence,
) -> None:
    result = await asyncio.wait_for(
        _provider(
            context=context,
            topology=topology,
            inventory=inventory,
            metrics=metrics,
        ).build(event=_event(), action=_action()),
        timeout=0.5,
    )

    assert result is None


async def test_provider_holds_when_target_revision_differs_from_pin() -> None:
    context = _context()
    revised_paths = tuple(
        replace(item, revision=4) if item.object_id == _TARGET else item
        for item in context.evidence_paths
    )
    topology = _topology()
    revised_objects = tuple(
        replace(item, revision=4) if item.id == _TARGET else item for item in topology.graph.objects
    )

    result = await asyncio.wait_for(
        _provider(
            context=replace(context, evidence_paths=revised_paths),
            topology=replace(
                topology,
                graph=replace(topology.graph, objects=revised_objects),
            ),
        ).build(event=_event(), action=_action()),
        timeout=0.5,
    )

    assert result is None


async def test_provider_holds_when_one_read_times_out() -> None:
    blocking = _BlockingReader()
    provider = AzureGraphDynamicSimulationRequestProvider(
        contexts=_ContextSource(),
        topology=blocking,  # type: ignore[arg-type]
        inventory=_Reader(_inventory()),  # type: ignore[arg-type]
        metrics=_Reader(_metrics()),  # type: ignore[arg-type]
        action_types={_ACTION_TYPE: _action_type()},
        policies={
            _ACTION_TYPE: AzureGraphInterventionPolicy(
                metric="replicas",
                delta=1.0,
                max_abs_delta=1.0,
                horizon=timedelta(minutes=1),
            )
        },
        read_timeout_seconds=0.02,
        build_timeout_seconds=0.05,
    )

    result = await asyncio.wait_for(provider.build(event=_event(), action=_action()), timeout=0.5)

    assert result is None
    assert blocking.cancelled is True


async def test_provider_propagates_caller_cancellation() -> None:
    blocking = _BlockingReader()
    provider = AzureGraphDynamicSimulationRequestProvider(
        contexts=_ContextSource(),
        topology=blocking,  # type: ignore[arg-type]
        inventory=_Reader(_inventory()),  # type: ignore[arg-type]
        metrics=_Reader(_metrics()),  # type: ignore[arg-type]
        action_types={_ACTION_TYPE: _action_type()},
        policies={
            _ACTION_TYPE: AzureGraphInterventionPolicy(
                metric="replicas",
                delta=1.0,
                max_abs_delta=1.0,
                horizon=timedelta(minutes=1),
            )
        },
        read_timeout_seconds=0.4,
        build_timeout_seconds=0.5,
    )
    task = asyncio.create_task(provider.build(event=_event(), action=_action()))
    await asyncio.wait_for(blocking.started.wait(), timeout=0.5)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)
    assert blocking.cancelled is True


class _Models:
    async def list_models(
        self,
        *,
        status: EffectModelStatus,
        trigger_refs: tuple[str, ...],
    ) -> tuple[GraphEffectModel, ...]:
        assert trigger_refs == (_ACTION_TYPE,)
        gain = 5.0 if status is EffectModelStatus.ACTIVE else 50.0
        return (
            GraphEffectModel(
                model_id=f"model-{status.value}",
                version="1.0.0",
                revision=1,
                status=status,
                trigger_ref=_ACTION_TYPE,
                source_type="Workload",
                link_path=("implements",),
                target_type="BusinessService",
                target_metric="latency",
                propagation_lag_seconds=10,
                gain=gain,
                offset=0.0,
                interval_radius=1.0,
                evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
                causal_evidence_receipt_digest="c" * 64,
                learned_through=_NOW,
            ),
        )


class _EvidenceVerifier:
    def verify(self, model: GraphEffectModel) -> bool:
        return model.causal_evidence_receipt_digest == "c" * 64


async def test_graph_runtime_uses_active_for_invariants_and_challenger_for_divergence() -> None:
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=_provider(),
        model_reader=_Models(),
        causal_evidence_verifier=_EvidenceVerifier(),
    )

    result = await asyncio.wait_for(
        coordinator.simulate(event=_event(), action=_action()), timeout=0.5
    )

    assert result.simulation is not None
    simulation = result.simulation
    assert simulation.challenger_trajectory is not None
    active_latency = next(
        item
        for item in simulation.active_trajectory.slices
        if item.metric == "latency" and item.effective_at > _NOW
    )
    challenger_latency = next(
        item
        for item in simulation.challenger_trajectory.slices
        if item.metric == "latency" and item.effective_at > _NOW
    )
    assert active_latency.value == 55.0
    assert challenger_latency.value == 100.0
    assert "active_challenger_divergence" in simulation.reason_codes
    service_result = next(
        item
        for item in simulation.invariant_results
        if item.invariant_id == "semantic:objective:service"
    )
    assert service_result.status is InvariantStatus.PASSED
    assert service_result.violating_keys == ()
