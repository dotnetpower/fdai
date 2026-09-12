"""Canonical source decoding and snapshot-boundary regressions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_operator_service.dashboard_source import (
    MEASUREMENT_ROW_LIMIT,
    MEASUREMENT_SNAPSHOT_SQL,
    decode_dashboard_snapshot,
)
from fdai_service_contracts.control_loop_measurement import (
    ControlLoopMeasurement,
    control_loop_measurement_id,
)
from fdai_service_contracts.metric_observation import MetricObservationV1, metric_observation_id

NOW = datetime(2026, 9, 1, tzinfo=UTC)
EVENT_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTION_ID = UUID("00000000-0000-0000-0000-000000000002")
OUTCOME_ID = UUID("00000000-0000-0000-0000-000000000003")


def classification(**changes):
    values = {
        "measurement_id": control_loop_measurement_id("example-key"),
        "event_id": EVENT_ID,
        "idempotency_key": "example-key",
        "source": "example-observer",
        "event_type": "resource.changed",
        "mode": "enforce",
        "synthetic": False,
        "occurred_at": NOW - timedelta(hours=2),
        "ingested_at": NOW - timedelta(hours=1),
        "recorded_at": NOW,
        "tier": "t0",
        "terminal_outcome": "executed",
        "gate_route": "auto",
        "action_ids": (str(ACTION_ID),),
    }
    values.update(changes)
    record = ControlLoopMeasurement.model_validate(values).model_dump(mode="json")
    return {"actor": "fdai.measurement", "action_kind": "measurement.control_loop.v1", **record}


def outcome(**changes):
    values = {
        "actor": "fdai.measurement",
        "action_kind": "measurement.action_outcome.v1",
        "schema_version": "1.0.0",
        "event_id": str(EVENT_ID),
        "action_id": str(ACTION_ID),
        "outcome_id": str(OUTCOME_ID),
        "mode": "enforce",
        "execution_mode": "enforce",
        "decision": "auto",
        "label": "verified",
        "verification_status": "verified",
        "verification_passed": True,
        "scorable": True,
        "predicted_at": (NOW - timedelta(hours=2)).isoformat(),
        "observed_at": (NOW - timedelta(hours=1)).isoformat(),
        "observation_deadline": NOW.isoformat(),
        "recorded_at": NOW.isoformat(),
        "expected_min": 0,
        "expected_max": 10,
        "observed_value": 5,
        "evidence_refs": ["example-effect-receipt"],
    }
    values.update(changes)
    return values


def metric(**changes):
    values = {
        "metric_id": "mttr_seconds",
        "mode": "enforce",
        "arm": "treatment",
        "measurement_protocol_digest": "sha256:" + "a" * 64,
        "source_revision": "a" * 40,
        "event_id": str(EVENT_ID),
        "source_id": "example-source",
        "source_record_id": "example-incident",
        "source_refs": ("example-evidence",),
        "value": 2.5,
        "unit": "seconds",
        "observed_at": NOW,
        "recorded_at": NOW,
        "synthetic": False,
        "complete": True,
        **changes,
    }
    return MetricObservationV1.model_validate(
        {
            **values,
            "observation_id": metric_observation_id(**values),
        }
    ).to_audit_entry()


def row(entry, seq=1, **changes):
    return {
        "seq": seq,
        "action_kind": entry["action_kind"],
        "entry": entry,
        "created_at": NOW.isoformat(),
        **changes,
    }


def snapshot(*rows, **changes):
    return [{"cutoff_seq": 10, "window_end": NOW, "records": list(rows), **changes}]


def test_empty_snapshot_is_complete_without_made_up_measurements() -> None:
    result = decode_dashboard_snapshot(snapshot())
    assert result.events == ()
    assert result.outcomes == ()
    assert result.window_start == NOW - timedelta(days=30)


def test_canonical_sources_preserve_identity_action_set_and_times() -> None:
    result = decode_dashboard_snapshot(snapshot(row(classification()), row(outcome(), 2)))
    assert result.events[0].identity == "example-key"
    assert result.events[0].action_ids == (str(ACTION_ID),)
    assert result.outcomes[0].verified is True
    assert result.cutoff_seq == 10


@pytest.mark.parametrize(
    "change",
    [
        {"actor": "untrusted"},
        {"verification_passed": "true"},
        {"verification_passed": 1},
        {"scorable": False},
        {"verification_status": "hold"},
        {"expected_min": 6},
        {"observed_value": float("nan")},
        {"rollback_succeeded": "false"},
        {"evidence_refs": []},
        {"observed_at": (NOW + timedelta(seconds=1)).isoformat()},
        {"recorded_at": NOW.replace(tzinfo=None).isoformat()},
    ],
)
def test_invalid_outcome_evidence_is_not_promoted_to_verified(change) -> None:
    with pytest.raises(ValueError):
        decode_dashboard_snapshot(snapshot(row(outcome(**change))))


def test_unknown_latest_outcome_is_retained_as_a_withdrawal() -> None:
    result = decode_dashboard_snapshot(
        snapshot(
            row(
                outcome(
                    label="unscorable",
                    verification_status="hold",
                    verification_passed=False,
                    scorable=False,
                    observed_at=None,
                )
            )
        )
    )
    assert result.outcomes[0].verified is False
    assert result.outcomes[0].observed_at is None


def test_explicit_synthetic_classification_is_not_live_evidence() -> None:
    result = decode_dashboard_snapshot(snapshot(row(classification(synthetic=True))))
    assert result.events[0].synthetic is True


def test_human_input_uses_exact_event_or_parked_action_identity() -> None:
    human = {"action_kind": "hil.requested", "approval_id": "approval-a"}
    result = decode_dashboard_snapshot(
        snapshot(
            row(classification()),
            row(human, 2, approval_event_id=str(EVENT_ID)),
        )
    )
    assert result.touchpoints[0].event_id == str(EVENT_ID)
    assert result.touchpoints[0].identity == "approval-a"
    assert result.unattributed_touchpoints == 0


def test_unattributed_human_input_is_not_silently_zero() -> None:
    result = decode_dashboard_snapshot(
        snapshot(
            row(classification()),
            row({"action_kind": "hil.requested", "approval_id": "approval-a"}, 2),
        )
    )
    assert result.unattributed_touchpoints == 1


def test_snapshot_and_payload_bounds_fail_closed() -> None:
    with pytest.raises(ValueError, match="cutoff"):
        decode_dashboard_snapshot(snapshot(row(classification(), 11)))
    with pytest.raises(ValueError, match="kinds disagree"):
        decode_dashboard_snapshot(snapshot(row(classification(), action_kind="other")))
    with pytest.raises(ValueError, match="complete read bound"):
        decode_dashboard_snapshot(snapshot(records=[{}] * (MEASUREMENT_ROW_LIMIT + 1)))


def test_snapshot_sql_bounds_all_streams_in_one_read() -> None:
    assert "CURRENT_TIMESTAMP AS window_end" in MEASUREMENT_SNAPSHOT_SQL
    assert "audit.seq <= boundary.cutoff_seq" in MEASUREMENT_SNAPSHOT_SQL
    assert "audit.action_kind = ANY(%s)" in MEASUREMENT_SNAPSHOT_SQL
    assert "LIMIT %s" in MEASUREMENT_SNAPSHOT_SQL


def test_metric_provenance_is_retained_and_incomplete_values_withdraw() -> None:
    result = decode_dashboard_snapshot(snapshot(row(metric())))
    assert result.metrics[0].value == 2.5
    assert result.metrics[0].source_context == (
        "sha256:" + "a" * 64,
        "a" * 40,
        "example-source",
        "enforce",
    )
    missing = decode_dashboard_snapshot(snapshot(row(metric(complete=False))))
    assert missing.metrics[0].value is None
    synthetic = decode_dashboard_snapshot(snapshot(row(metric(synthetic=True))))
    assert synthetic.metrics[0].value is None


def test_rejected_terminal_cannot_silently_shrink_the_denominator() -> None:
    rejected = {
        "actor": "fdai.measurement",
        "action_kind": "measurement.control_loop.rejected.v1",
        "measurement_id": str(control_loop_measurement_id("example-key")),
        "event_id": str(EVENT_ID),
        "occurred_at": (NOW - timedelta(hours=2)).isoformat(),
        "synthetic": False,
    }
    with pytest.raises(ValueError, match="incomplete after rejection"):
        decode_dashboard_snapshot(snapshot(row(rejected)))
    with pytest.raises(ValueError, match="incomplete after rejection"):
        decode_dashboard_snapshot(snapshot(row(rejected), row(classification(synthetic=True), 2)))
    recovered = decode_dashboard_snapshot(snapshot(row(rejected), row(classification(), 2)))
    assert len(recovered.events) == 1
