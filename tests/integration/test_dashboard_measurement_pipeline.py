"""Synthetic in-memory wiring evidence; never a live outcome or cohort claim."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai.core.control_loop._measurement import TerminalMeasurementRecorder
from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.measurement.metric_recorder import MetricObservationRecorder
from fdai.core.mscp_profile.response_outcome import response_outcome_audit_entry
from fdai.shared.contracts.models import (
    Event,
    Mode,
    ResponseOutcome,
    ResponseOutcomeLabel,
    ResponseVerificationStatus,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.dashboard_aggregation import aggregate_dashboard
from fdai_operator_service.dashboard_source import decode_dashboard_snapshot
from fdai_operator_service.families.operations import ProjectionUnavailableError
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts.metric_observation import MetricObservationV1, metric_observation_id

NOW = datetime(2026, 9, 12, 8, tzinfo=UTC)
EVENT_A = UUID(int=1)
EVENT_B = UUID(int=2)
ACTION_A = UUID(int=3)


def event(identity: UUID) -> Event:
    return Event(
        schema_version="1.0.0",
        event_id=identity,
        idempotency_key=f"example:{identity}",
        source="example-observer",
        event_type="resource.changed",
        mode=Mode.ENFORCE,
        detected_at=NOW - timedelta(hours=2),
        ingested_at=NOW - timedelta(hours=1),
        payload={"synthetic": False},
    )


def observation(event_id: UUID, metric_id: str, value: float) -> MetricObservationV1:
    values = {
        "metric_id": metric_id,
        "mode": "enforce",
        "arm": "treatment",
        "measurement_protocol_digest": "sha256:" + "a" * 64,
        "source_revision": "a" * 40,
        "event_id": str(event_id),
        "source_id": "example-source",
        "source_record_id": f"example:{event_id}",
        "source_refs": ("example-source-receipt",),
        "value": value,
        "unit": "USD" if metric_id == "attributed_cost_usd" else "seconds",
        "observed_at": NOW,
        "recorded_at": NOW,
        "synthetic": False,
        "complete": True,
    }
    return MetricObservationV1.model_validate(
        {
            **values,
            "observation_id": metric_observation_id(**values),
        }
    )


class NoFallback:
    async def read(self, query):
        raise AssertionError("measurement reads must not fall back to invented data")


async def test_real_recorders_require_canonical_projection_for_operator_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    terminal = TerminalMeasurementRecorder(store)
    await terminal.record(
        event(EVENT_A),
        ControlLoopResult(
            outcome=ControlLoopOutcome.EXECUTED,
            tier="t0",
            decision="auto",
            resource_type="compute.vm",
            execution_results=(
                ExecutionResult(
                    action_id=str(ACTION_A),
                    outcome=ExecutorOutcome.PUBLISHED,
                    mode=Mode.ENFORCE,
                ),
            ),
        ),
        recorded_at=NOW,
    )
    await terminal.record(
        event(EVENT_B),
        ControlLoopResult(
            outcome=ControlLoopOutcome.HIL,
            tier="t1",
            decision="hil",
            resource_type="compute.vm",
        ),
        recorded_at=NOW,
    )
    await store.append_audit_entry(
        {
            "action_kind": "hil.requested",
            "event_id": str(EVENT_B),
            "approval_id": "example-approval",
        }
    )

    def aggregate() -> dict[str, object]:
        records = [
            {
                "seq": index,
                "action_kind": row["entry"]["action_kind"],
                "entry": row["entry"],
                "created_at": NOW,
            }
            for index, row in enumerate(store.audit_entries, start=1)
        ]
        snapshot = decode_dashboard_snapshot(
            [{"cutoff_seq": len(records), "window_end": NOW, "records": records}]
        )
        return aggregate_dashboard(
            events=snapshot.events,
            outcomes=snapshot.outcomes,
            metrics=snapshot.metrics,
            touchpoints=snapshot.touchpoints,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            human_source_complete=snapshot.unattributed_touchpoints == 0,
        )

    async def fetch(self, statement, parameters=()):
        del self, statement, parameters
        return []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/test"), NoFallback()
    )
    before = aggregate()
    assert before["sample_size"] == 2
    assert before["success"]["auto_resolution_rate"]["value"] == 0
    assert before["success"]["human_touchpoints_per_100"]["value"] == 50
    assert before["success"]["mttr_seconds"]["value"] is None

    outcome = ResponseOutcome(
        schema_version="1.0.0",
        outcome_id=UUID(int=4),
        idempotency_key="example-outcome",
        action_id=ACTION_A,
        event_id=EVENT_A,
        action_type_id="example-action",
        target_digest="b" * 64,
        prediction_id="example-prediction",
        metric="availability",
        expected_min=1,
        expected_max=1,
        observed_value=1,
        predicted_at=NOW - timedelta(hours=2),
        observation_deadline=NOW,
        observed_at=NOW - timedelta(hours=1),
        label=ResponseOutcomeLabel.VERIFIED,
        verification_status=ResponseVerificationStatus.VERIFIED,
        verification_reason="verified",
        execution_mode=Mode.ENFORCE,
        execution_outcome="published",
        decision="auto",
        evidence_refs=("example-independent-observation",),
        recorded_at=NOW,
    )
    await store.append_audit_entry(response_outcome_audit_entry(outcome))
    recorder = MetricObservationRecorder(store)
    for identity, metric, value in (
        (EVENT_A, "mttr_seconds", 120.5),
        (EVENT_B, "mttr_seconds", 180.5),
        (EVENT_A, "change_lead_time_seconds", 90.0),
        (EVENT_A, "attributed_cost_usd", 2.0),
        (EVENT_B, "attributed_cost_usd", 3.0),
    ):
        item = observation(identity, metric, value)
        assert await recorder.record(item)
        assert not await recorder.record(item)
    result = aggregate()
    values = {key: metric["value"] for key, metric in result["success"].items()}
    assert values == {
        "auto_resolution_rate": 0.5,
        "human_touchpoints_per_100": 50,
        "mttr_seconds": 150.5,
        "change_lead_time_seconds": 90,
        "cost_per_resolved_event_usd": 5,
    }
    assert result["finalization"]["pending_events"] == 1

    with pytest.raises(
        ProjectionUnavailableError,
        match="authoritative autonomy measurement projection is unavailable",
    ):
        await reader._autonomy_measurement()
