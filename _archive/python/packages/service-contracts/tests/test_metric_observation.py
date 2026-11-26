"""Canonical metric facts reject coercion, ambiguous units, and identity tampering."""

from datetime import UTC, datetime, timedelta

import pytest
from fdai_service_contracts.metric_observation import (
    MetricObservationV1,
    metric_observation_id,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _facts(**updates: object) -> dict[str, object]:
    return {
        "metric_id": "mttr_seconds",
        "mode": "enforce",
        "arm": "treatment",
        "measurement_protocol_digest": "sha256:" + "a" * 64,
        "source_revision": "a" * 40,
        "event_id": "event-1",
        "source_id": "incident-source",
        "source_record_id": "incident-1",
        "source_refs": ("incident:1",),
        "value": 120.0,
        "unit": "seconds",
        "observed_at": NOW,
        "recorded_at": NOW,
        "synthetic": False,
        "complete": True,
        **updates,
    }


def test_round_trip_and_recording_retry_keep_source_identity() -> None:
    facts = _facts()
    digest = metric_observation_id(**facts)
    observation = MetricObservationV1.model_validate({**facts, "observation_id": digest})
    assert MetricObservationV1.model_validate_json(observation.model_dump_json()) == observation
    assert metric_observation_id(**_facts(recorded_at=NOW + timedelta(hours=1))) == digest
    assert observation.action_kind == "measurement.metric.v1"
    assert metric_observation_id(**_facts(value=121.0)) != digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", True),
        ("value", "12"),
        ("value", -1),
        ("value", float("nan")),
        ("value", float("inf")),
        ("unit", "milliseconds"),
        ("unit", "USD"),
        ("metric_id", "estimated_savings"),
        ("mode", "auto"),
        ("arm", "baseline"),
        ("measurement_protocol_digest", "unversioned"),
        ("source_revision", "main"),
        ("event_id", " "),
        ("event_id", " event-1 "),
        ("source_id", ""),
        ("source_record_id", "a" * 257),
        ("source_refs", ()),
        ("source_refs", ("b", "a")),
        ("source_refs", ("a", "a")),
        ("observed_at", NOW.replace(tzinfo=None)),
        ("observed_at", 0),
        ("recorded_at", NOW - timedelta(seconds=1)),
        ("complete", "true"),
        ("synthetic", 0),
        ("verified", True),
        ("execution_authority", False),
    ],
)
def test_invalid_measurement_facts_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        metric_observation_id(**_facts(**{field: value}))


def test_usd_spend_has_exact_currency_unit_and_can_report_missing_coverage() -> None:
    facts = _facts(metric_id="attributed_cost_usd", unit="USD", value=0.0, complete=False)
    row = MetricObservationV1.model_validate(
        {**facts, "observation_id": metric_observation_id(**facts)}
    )
    assert row.value == 0
    assert row.complete is False
    with pytest.raises(ValidationError, match="unit"):
        metric_observation_id(**{**facts, "unit": "seconds"})


def test_correction_identity_is_sealed_and_does_not_mutate_original() -> None:
    facts = _facts()
    digest = metric_observation_id(**facts)
    correction = _facts(value=130.0, supersedes_observation_id=digest)
    assert metric_observation_id(**correction) != digest
    with pytest.raises(ValidationError, match="identity"):
        MetricObservationV1.model_validate({**correction, "observation_id": digest})


def test_strict_audit_parser_preserves_event_mode_and_source_facts() -> None:
    facts = _facts()
    row = MetricObservationV1.model_validate(
        {**facts, "observation_id": metric_observation_id(**facts)}
    )
    assert MetricObservationV1.from_audit_entry(row.to_audit_entry()) == row
    assert row.to_audit_entry()["mode"] == "enforce"
    assert row.to_audit_entry()["synthetic"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor", "client"),
        ("action_kind", "incident.transition"),
        ("execution_authority", True),
        ("execution_authority", 0),
        ("claim_eligibility_authority", "false"),
        ("idempotency_key", "stage-row"),
        ("seq", 123),
        ("verification_passed", True),
        ("source_authoritative", True),
    ],
)
def test_strict_audit_parser_rejects_noncanonical_wrappers(field, value) -> None:
    facts = _facts()
    row = MetricObservationV1.model_validate(
        {**facts, "observation_id": metric_observation_id(**facts)}
    )
    with pytest.raises(ValueError):
        MetricObservationV1.from_audit_entry({**row.to_audit_entry(), field: value})


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "action_kind",
        "schema_version",
        "idempotency_key",
        "execution_authority",
        "claim_eligibility_authority",
        "mode",
        "synthetic",
        "arm",
        "measurement_protocol_digest",
        "source_revision",
    ],
)
def test_strict_audit_parser_rejects_missing_identity_or_wrapper(field) -> None:
    facts = _facts()
    row = MetricObservationV1.model_validate(
        {**facts, "observation_id": metric_observation_id(**facts)}
    ).to_audit_entry()
    row.pop(field)
    with pytest.raises(ValueError):
        MetricObservationV1.from_audit_entry(row)
