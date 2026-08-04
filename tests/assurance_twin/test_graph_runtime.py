from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    DynamicInvariant,
    EffectModelStatus,
    GraphDynamicRuntimeCoordinator,
    GraphDynamicSimulationRequest,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    InvariantOperator,
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "anomaly",
            "detected_at": "2026-08-04T00:00:00Z",
            "ingested_at": "2026-08-04T00:00:01Z",
            "mode": "shadow",
            "payload": {},
        }
    )


def _action() -> LearnedAction:
    return LearnedAction(
        signature="sig-1",
        rule_id="learned.operational.example",
        action_type="ops.scale-out",
        params={},
        incident_id="incident-1",
        success_rate=0.99,
    )


def _request() -> GraphDynamicSimulationRequest:
    baseline = OperationalStateTrajectory(
        kind=TrajectoryKind.OBSERVED,
        ontology_release="sha256:" + "a" * 64,
        graph_revision="graph-1",
        inventory_generation="inventory-1",
        base_snapshot_id="snapshot-1",
        evidence_cutoff=_NOW,
        horizon_end=_NOW + timedelta(minutes=1),
        slices=(
            StateSlice(
                "service:api",
                "BusinessService",
                "latency",
                50.0,
                _NOW,
                evidence_refs=("metric:1",),
                independent_observer=True,
            ),
            StateSlice(
                "workload:api",
                "Workload",
                "replicas",
                2.0,
                _NOW,
                evidence_refs=("inventory:1",),
                independent_observer=True,
            ),
        ),
    )
    return GraphDynamicSimulationRequest(
        baseline=baseline,
        topology=(
            GraphTopologyEdge(
                "workload:api",
                "Workload",
                "implements",
                "service:api",
                "BusinessService",
            ),
        ),
        interventions=(
            GraphIntervention(
                "intervention:1",
                "ops.scale-out",
                "workload:api",
                "Workload",
                "replicas",
                1.0,
                _NOW,
            ),
        ),
        invariants=(
            DynamicInvariant(
                invariant_id="slo.api.latency",
                metric="latency",
                operator=InvariantOperator.LESS_THAN_OR_EQUAL,
                threshold=100.0,
                target_ref="service:api",
            ),
        ),
    )


def _model(status: EffectModelStatus) -> GraphEffectModel:
    return GraphEffectModel(
        model_id=f"graph-{status.value}",
        version="1.0.0",
        revision=1,
        status=status,
        trigger_ref="ops.scale-out",
        source_type="Workload",
        link_path=("implements",),
        target_type="BusinessService",
        target_metric="latency",
        propagation_lag_seconds=10,
        gain=5.0,
        offset=0.0,
        interval_radius=1.0,
        evidence_grade=CausalEvidenceGrade.QUASI_EXPERIMENTAL,
        causal_evidence_receipt_digest="b" * 64,
        learned_through=_NOW,
    )


class _Provider:
    def __init__(self, request: GraphDynamicSimulationRequest | None) -> None:
        self.request = request

    async def build(self, *, event: Event, action: LearnedAction):  # type: ignore[no-untyped-def]
        return self.request


class _Models:
    async def list_models(
        self,
        *,
        status: EffectModelStatus,
        trigger_refs: tuple[str, ...],
    ) -> tuple[GraphEffectModel, ...]:
        assert trigger_refs == ("ops.scale-out",)
        return (_model(status),)


class _Evidence:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted

    def verify(self, model: GraphEffectModel) -> bool:
        return self.accepted and model.causal_evidence_receipt_digest == "b" * 64


class _Ledger:
    def __init__(self) -> None:
        self.calls = []

    async def record_prediction(self, predicted, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append((predicted, kwargs))
        return True


async def test_graph_runtime_loads_verified_models_and_simulates() -> None:
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(),
        causal_evidence_verifier=_Evidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.reason == "graph_simulation_completed"
    assert result.simulation is not None
    predicted = next(
        item
        for item in result.simulation.active_trajectory.slices
        if item.effective_at == _NOW + timedelta(seconds=10)
    )
    assert predicted.value == 55.0


async def test_graph_runtime_records_prediction_for_challenger_closure() -> None:
    ledger = _Ledger()
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(),
        causal_evidence_verifier=_Evidence(),
        trajectory_ledger=ledger,  # type: ignore[arg-type]
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is not None
    assert result.simulation.challenger_trajectory is not None
    assert len(ledger.calls) == 1
    predicted, metadata = ledger.calls[0]
    assert predicted == result.simulation.challenger_trajectory
    assert metadata["challenger_model_refs"] == ("graph-challenger@1.0.0:r1",)
    assert metadata["recorded_by"] == "Forseti"


async def test_graph_runtime_holds_when_request_is_unavailable() -> None:
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=_Provider(None),
        model_reader=_Models(),
        causal_evidence_verifier=_Evidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is None
    assert result.reason == "graph_simulation_request_unavailable"


async def test_graph_runtime_rejects_unverified_model_receipt() -> None:
    coordinator = GraphDynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(),
        causal_evidence_verifier=_Evidence(False),
    )

    with pytest.raises(ValueError, match="causal evidence is unverified"):
        await coordinator.simulate(event=_event(), action=_action())


def test_graph_request_rejects_empty_invariants() -> None:
    request = _request()

    with pytest.raises(ValueError, match="non-empty, unique, and bounded"):
        GraphDynamicSimulationRequest(
            baseline=request.baseline,
            topology=request.topology,
            interventions=request.interventions,
            invariants=(),
        )
