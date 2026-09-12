"""Terminal evidence preserves source identity without implying operational success."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fdai_service_contracts.control_loop_measurement import (
    CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    CONTROL_LOOP_MEASUREMENT_ACTOR,
    ControlLoopMeasurement,
    control_loop_measurement_id,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 12, 7, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "measurement_id": control_loop_measurement_id("source-key"),
        "event_id": UUID("00000000-0000-0000-0000-000000000123"),
        "idempotency_key": "source-key",
        "correlation_id": "correlation-1",
        "source": "synthetic-observer",
        "event_type": "resource.changed",
        "mode": "shadow",
        "occurred_at": NOW - timedelta(minutes=2),
        "ingested_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "tier": None,
        "terminal_outcome": "abstained_routing",
        "gate_route": "abstain",
        "resource_type": None,
    }


def test_json_roundtrip_preserves_unclassified_tier_and_distinct_times() -> None:
    measurement = ControlLoopMeasurement.model_validate(_payload())
    restored = ControlLoopMeasurement.model_validate_json(measurement.model_dump_json())
    assert restored == measurement
    assert restored.tier is None
    assert restored.occurred_at < restored.ingested_at < restored.recorded_at
    assert "tier" in restored.model_dump(exclude_none=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2.0.0"),
        ("mode", "auto"),
        ("synthetic", "false"),
        ("synthetic", 1),
        ("tier", "abstain"),
        ("tier", "T0"),
        ("terminal_outcome", "deduped"),
        ("terminal_outcome", "x" * 129),
        ("gate_route", ""),
        ("source", "x" * 4097),
        ("event_type", "x" * 4097),
        ("correlation_id", "x" * 4097),
        ("idempotency_key", "x" * 513),
        ("measurement_id", UUID(int=0)),
        ("occurred_at", NOW.replace(tzinfo=None)),
        ("ingested_at", NOW.replace(tzinfo=None)),
        ("recorded_at", NOW.replace(tzinfo=None)),
        ("recorded_at", float("inf")),
        ("recorded_at", True),
        ("occurred_at", 0),
        ("ingested_at", 1.0),
        ("occurred_at", "0"),
        ("verification_passed", True),
        ("success", True),
        ("decision", "auto"),
        ("action_ids", None),
        ("action_ids", "action-1"),
        ("action_ids", {"action-1"}),
        ("action_ids", {"action-1": True}),
        ("action_ids", [1]),
        ("action_ids", [True]),
        ("action_ids", [None]),
        ("action_ids", [""]),
        ("action_ids", ["x" * 4097]),
        ("action_ids", ["action-1"] * 4097),
    ],
)
def test_invalid_or_authority_bearing_fields_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ControlLoopMeasurement.model_validate({**_payload(), field: value})


def test_raw_terminal_and_gate_route_are_not_interchangeable() -> None:
    measurement = ControlLoopMeasurement.model_validate(
        {**_payload(), "tier": "t0", "terminal_outcome": "executed", "gate_route": "auto"}
    )
    assert measurement.terminal_outcome == "executed"
    assert measurement.gate_route == "auto"
    assert not hasattr(measurement, "verification_passed")
    assert not hasattr(measurement, "scorable")


def test_complete_identity_is_not_trimmed_or_prefix_deduplicated() -> None:
    key = "x" * 500 + " source-key"
    measurement = ControlLoopMeasurement.model_validate(
        {
            **_payload(),
            "idempotency_key": key,
            "measurement_id": control_loop_measurement_id(key),
        }
    )
    assert measurement.idempotency_key == key
    assert control_loop_measurement_id(key) != control_loop_measurement_id(key + "2")


def test_clock_skew_is_retained_not_rewritten_as_fresh_evidence() -> None:
    measurement = ControlLoopMeasurement.model_validate(
        {**_payload(), "occurred_at": NOW + timedelta(minutes=1)}
    )
    assert measurement.occurred_at > measurement.recorded_at


@pytest.mark.parametrize("synthetic", [True, False, None])
def test_strict_audit_parser_preserves_source_marker(synthetic: bool | None) -> None:
    payload = {**_payload(), "synthetic": synthetic}
    measurement = ControlLoopMeasurement.from_audit_entry(
        {
            **payload,
            "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
            "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
        }
    )
    assert measurement == ControlLoopMeasurement.model_validate(payload)
    assert measurement.synthetic is synthetic


@pytest.mark.parametrize(
    "overrides",
    [
        {"actor": "untrusted-writer"},
        {"action_kind": "measurement.action_outcome.v1"},
        {"action_kind": "measurement.control_loop.v2"},
        {"schema_version": None},
        {"seq": 1},
        {"entry_hash": "0" * 64},
        {"verification_passed": True},
    ],
)
def test_audit_parser_rejects_wrong_envelopes_and_additional_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ControlLoopMeasurement.from_audit_entry(
            {
                **_payload(),
                "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
                "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
                **overrides,
            }
        )


def test_audit_parser_requires_inner_entry_not_hash_chain_wrapper() -> None:
    entry = {
        **_payload(),
        "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
        "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
    }
    with pytest.raises(ValueError, match="actor"):
        ControlLoopMeasurement.from_audit_entry(
            {"entry": entry, "previous_hash": "0" * 64, "entry_hash": "1" * 64}
        )
    entry.pop("schema_version")
    with pytest.raises(ValueError, match="schema version"):
        ControlLoopMeasurement.from_audit_entry(entry)


def test_action_ids_default_is_empty_and_explicit_order_survives_wire_roundtrip() -> None:
    assert ControlLoopMeasurement.model_validate(_payload()).action_ids == ()
    action_ids = ("action-1", "unbuilt::source-key::rule-1", "action-1")
    measurement = ControlLoopMeasurement.model_validate({**_payload(), "action_ids": action_ids})
    wire = measurement.model_dump(mode="json")
    assert wire["action_ids"] == list(action_ids)
    restored = ControlLoopMeasurement.from_audit_entry(
        {
            **wire,
            "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
            "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
        }
    )
    assert restored.action_ids == action_ids


@pytest.mark.parametrize("action_ids", [[1], [None], [""]])
def test_strict_audit_parser_rejects_invalid_action_identity_types(
    action_ids: list[object],
) -> None:
    with pytest.raises(ValueError):
        ControlLoopMeasurement.from_audit_entry(
            {
                **_payload(),
                "actor": CONTROL_LOOP_MEASUREMENT_ACTOR,
                "action_kind": CONTROL_LOOP_MEASUREMENT_ACTION_KIND,
                "action_ids": action_ids,
            }
        )
