from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.assurance_twin import (
    CausalEvidenceGrade,
    DynamicRuntimeCoordinator,
    DynamicSimulationRequest,
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
)
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event

_NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "anomaly",
            "detected_at": "2026-08-01T00:00:00Z",
            "ingested_at": "2026-08-01T00:00:01Z",
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


def _model(
    *,
    status: EffectModelStatus,
    bias: float = 0.0,
    grade: CausalEvidenceGrade = CausalEvidenceGrade.QUASI_EXPERIMENTAL,
    learned_through: datetime = _NOW,
) -> EffectModel:
    return EffectModel(
        model_id=f"model-{status.value}",
        version="1.0.0",
        revision=1,
        action_type_id="ops.scale-out",
        metric="latency",
        status=status,
        evidence_grade=grade,
        causal_evidence_receipt_digest="a" * 64,
        learned_at=_NOW,
        learned_through=learned_through,
        bias_correction=bias,
    )


class _Provider:
    def __init__(self, request: DynamicSimulationRequest | None) -> None:
        self.request = request

    async def build(self, *, event: Event, action: LearnedAction):  # type: ignore[no-untyped-def]
        return self.request


class _Models:
    def __init__(self, models: tuple[EffectModel, ...]) -> None:
        self.models = {
            (model.status, model.action_type_id, model.metric): model for model in models
        }

    async def get(
        self,
        *,
        status: EffectModelStatus,
        action_type_id: str,
        metric: str,
    ) -> EffectModel | None:
        return self.models.get((status, action_type_id, metric))


class _CausalEvidence:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted

    def verify(self, model: EffectModel) -> bool:
        return self.accepted and model.causal_evidence_receipt_digest == "a" * 64


def _request() -> DynamicSimulationRequest:
    return DynamicSimulationRequest(
        snapshot=SimulationSnapshot(
            snapshot_id="snapshot-1",
            target_digest="a" * 64,
            metric="latency",
            observed_at=_NOW,
        ),
        branches=(
            SimulationBranch(
                branch_id="scale-out",
                action_type_id="ops.scale-out",
                raw_prediction=80.0,
                raw_interval_radius=5.0,
            ),
        ),
        divergence_threshold=5.0,
    )


async def test_dynamic_runtime_loads_models_and_simulates() -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(
            (
                _model(status=EffectModelStatus.ACTIVE),
                _model(status=EffectModelStatus.CHALLENGER, bias=2.0),
            )
        ),
        causal_evidence_verifier=_CausalEvidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.reason == "simulation_completed"
    assert result.simulation is not None
    prediction = result.simulation.predictions[0]
    assert prediction.active_value == 80.0
    assert prediction.challenger_value == 82.0
    assert prediction.requires_review is False


async def test_dynamic_runtime_missing_active_model_requires_review() -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(()),
        causal_evidence_verifier=_CausalEvidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is not None
    assert result.simulation.requires_review is True
    assert result.simulation.predictions[0].reason == "active_model_unavailable"


async def test_dynamic_runtime_divergence_requires_review() -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(
            (
                _model(status=EffectModelStatus.ACTIVE),
                _model(status=EffectModelStatus.CHALLENGER, bias=10.0),
            )
        ),
        causal_evidence_verifier=_CausalEvidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is not None
    assert result.simulation.requires_review is True
    assert result.simulation.predictions[0].reason == "active_challenger_divergence"


async def test_dynamic_runtime_holds_when_request_is_unavailable() -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(None),
        model_reader=_Models(()),
        causal_evidence_verifier=_CausalEvidence(),
    )

    result = await coordinator.simulate(event=_event(), action=_action())

    assert result.simulation is None
    assert result.reason == "simulation_request_unavailable"


async def test_dynamic_runtime_rejects_unverified_causal_model_receipt() -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models((_model(status=EffectModelStatus.ACTIVE),)),
        causal_evidence_verifier=_CausalEvidence(accepted=False),
    )

    with pytest.raises(ValueError, match="causal evidence is unverified"):
        await coordinator.simulate(event=_event(), action=_action())


@pytest.mark.parametrize("status", [EffectModelStatus.ACTIVE, EffectModelStatus.CHALLENGER])
async def test_dynamic_runtime_rejects_model_after_snapshot_cutoff(
    status: EffectModelStatus,
) -> None:
    coordinator = DynamicRuntimeCoordinator(
        request_provider=_Provider(_request()),
        model_reader=_Models(
            (
                _model(
                    status=status,
                    learned_through=_NOW + timedelta(seconds=1),
                ),
            )
        ),
        causal_evidence_verifier=_CausalEvidence(),
    )

    with pytest.raises(ValueError, match=f"Dynamic {status.value} model crosses"):
        await coordinator.simulate(event=_event(), action=_action())
