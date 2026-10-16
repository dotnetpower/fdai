"""Frozen synthetic holdout through ingestion, T1, persisted models, and Dynamic guard."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fdai.core.assurance_twin import (
    DynamicRuntimeCoordinator,
    DynamicRuntimeResult,
    DynamicSimulationRequest,
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
    StateStoreEffectModelRegistry,
)
from fdai.core.assurance_twin.prediction_evidence import retain_prediction
from fdai.core.control_loop import ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.tiers.t1_lightweight import LearnedAction, T1Tier
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.core.tiers.t1_lightweight.tier import _event_text
from fdai.shared.contracts.models import Event, ResponseOutcome
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.assurance_twin.test_feedback_reliability import _feedback
from tests.assurance_twin.test_model_registry import _NOW, _CurrentFixtureSource, _model
from tests.core.test_control_loop_t1_wire import _make_loop, _validator
from tests.product_selection import governed_execution_selection

_PROCESSING_AT = _NOW + timedelta(minutes=6)
_PREDICTION_AT = _NOW + timedelta(minutes=7)


class _Request:
    async def build(self, *, event: Event, action: LearnedAction) -> DynamicSimulationRequest:
        return DynamicSimulationRequest(
            snapshot=SimulationSnapshot(
                snapshot_id=f"snapshot:{event.event_id}",
                target_digest="0" * 64,
                metric="latency_p99_ms",
                observed_at=_PREDICTION_AT,
            ),
            branches=(SimulationBranch("scale", "ops.scale-out", 100.0, 10.0),),
            divergence_threshold=5.0,
        )


class _VerifiedModel:
    def verify(self, model: EffectModel) -> bool:
        return model.causal_evidence_receipt_digest == "a" * 64


class _RecordingRuntime(DynamicRuntimeCoordinator):
    def __init__(self, store: InMemoryStateStore) -> None:
        super().__init__(
            request_provider=_Request(),
            model_reader=StateStoreEffectModelRegistry(
                store, feedback_source=_CurrentFixtureSource()
            ),
            causal_evidence_verifier=_VerifiedModel(),
        )
        self.results: list[DynamicRuntimeResult] = []

    async def simulate(self, *, event: Event, action: LearnedAction) -> DynamicRuntimeResult:
        result = await super().simulate(event=event, action=action)
        self.results.append(result)
        return result


def _raw(index: int) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "event_id": str(UUID(int=index)),
        "idempotency_key": f"frozen-holdout:{index}",
        "source": "synthetic-regression",
        "event_type": "novel.event",
        "detected_at": _PREDICTION_AT.isoformat(),
        "ingested_at": _PREDICTION_AT.isoformat(),
        "mode": "shadow",
        "payload": {"resource": {"type": "compute.vm.novel", "id": "example-resource"}},
    }


async def test_late_feedback_changes_next_full_path_shadow_prediction_without_execution(
    tmp_path: Path,
) -> None:
    """This is wiring/regression evidence, not a production policy-effect estimate."""
    store = InMemoryStateStore()
    registry = StateStoreEffectModelRegistry(
        store, clock=lambda: _PROCESSING_AT, feedback_source=_CurrentFixtureSource()
    )
    active = _model(EffectModelStatus.ACTIVE)
    await registry.register(active, registered_by="Mimir")
    await registry.register(_model(EffectModelStatus.CHALLENGER), registered_by="Mimir")
    for index in (1, 2):
        snapshot = _feedback(index).prediction_snapshot
        assert snapshot is not None
        await retain_prediction(store, snapshot, recorded_at=_NOW)
    assert (await registry.update_from_outcome(_feedback(1))).accepted

    embedding = DeterministicEmbeddingModel()
    library = InMemoryPatternLibrary()
    first = EventIngest(validator=_validator()).ingest(_raw(100))
    assert first is not None
    library.add(
        vector=await embedding.embed(_event_text(first)),
        action=LearnedAction(
            signature="registered-example",
            rule_id="r1",
            action_type="ops.scale-out",
            params={},
            incident_id="example-incident",
            success_rate=0.99,
        ),
    )

    async def predict(index: int) -> tuple[float, float, bool]:
        runtime = _RecordingRuntime(store)
        loop = _make_loop(
            t1_engine=T1Tier(embedding_model=embedding, pattern_library=library),
            audit=store,
            tmp_path=tmp_path,
            dynamic_runtime_coordinator=runtime,
            governed_execution_selected=governed_execution_selection(True),
        )
        result = await loop.process(_raw(index))
        assert result.outcome is ControlLoopOutcome.HIL
        assert not result.execution_results
        simulation = runtime.results[-1].simulation
        assert simulation is not None
        prediction = simulation.predictions[0]
        assert prediction.active_value is not None
        assert prediction.challenger_value is not None
        return prediction.active_value, prediction.challenger_value, prediction.requires_review

    # Freeze the prediction before revealing the holdout observation. With the old
    # timestamp cursor, the second training event is discarded and this stays at 80.
    before = await predict(100)
    assert before == (100.0, 80.0, True)
    second = ResponseOutcome.model_validate(
        {
            **_feedback(2).model_dump(),
            "observed_value": 100.0,
            "label": "verified",
            "verification_status": "verified",
        }
    )
    assert (await registry.update_from_outcome(second)).accepted
    after = await predict(101)
    observed_holdout = 90.0
    baseline_error = abs(after[0] - observed_holdout)
    before_error = abs(before[1] - observed_holdout)
    after_error = abs(after[1] - observed_holdout)
    assert after == (100.0, 90.0, True)
    assert after_error == 0.0 < before_error == baseline_error == 10.0
    assert (
        await registry.get(
            status=EffectModelStatus.ACTIVE,
            action_type_id=active.action_type_id,
            metric=active.metric,
        )
        == active
    )
    challenger = await registry.get(
        status=EffectModelStatus.CHALLENGER,
        action_type_id=active.action_type_id,
        metric=active.metric,
    )
    assert challenger is not None and challenger.sample_count == 2
    _, lower, upper = challenger.predict(100.0, 10.0)
    assert lower <= observed_holdout <= upper
    assert upper - lower == 40.0
    assert await store.verify_chain()
    print(
        json.dumps(
            {
                "evidence": "synthetic_wiring_regression_only",
                "training_events": 2,
                "holdout_outcomes": 1,
                "baseline_absolute_error": baseline_error,
                "before_absolute_error": before_error,
                "after_absolute_error": after_error,
                "baseline_interval_covered": 90.0 <= observed_holdout <= 110.0,
                "challenger_interval_covered": lower <= observed_holdout <= upper,
                "baseline_interval_width": 20.0,
                "challenger_interval_width": upper - lower,
                "guard_requires_review": after[2],
                "executions": 0,
                "promotions": 0,
            },
            sort_keys=True,
        )
    )
