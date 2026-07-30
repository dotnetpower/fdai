from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from fdai.agents import instantiate_pantheon
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.shared.contracts.models import ResponseOutcome

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _outcome(identifier: int, *, label: str, mode: str) -> ResponseOutcome:
    return ResponseOutcome.model_validate(
        {
            "schema_version": "1.0.0",
            "outcome_id": UUID(int=identifier),
            "idempotency_key": f"response-outcome:{identifier}",
            "action_id": UUID(int=100 + identifier),
            "event_id": UUID(int=200 + identifier),
            "action_type_id": "ops.scale-out",
            "target_digest": "a" * 64,
            "prediction_id": f"prediction-{identifier}",
            "metric": "availability",
            "expected_min": 0.99,
            "expected_max": 1.0,
            "observed_value": 0.995 if label == "verified" else 0.5,
            "predicted_at": _NOW,
            "observation_deadline": _NOW + timedelta(minutes=5),
            "observed_at": _NOW + timedelta(minutes=1),
            "label": label,
            "verification_status": "verified" if label == "verified" else "mismatch",
            "verification_reason": "test-evidence",
            "execution_mode": mode,
            "execution_outcome": "succeeded",
            "decision": "auto",
            "evidence_refs": [f"effect:prediction-{identifier}"],
            "recorded_at": _NOW + timedelta(minutes=2, seconds=identifier),
        }
    )


def _raw(outcome: ResponseOutcome) -> dict[str, Any]:
    return {
        "id": outcome.idempotency_key,
        "event_id": str(outcome.event_id),
        "correlation_id": str(outcome.action_id),
        "idempotency_key": outcome.idempotency_key,
        "source": "fdai.measurement",
        "event_type": "measurement.action_outcome.v1",
        "resource_id": outcome.target_digest,
        "attributes": outcome.model_dump(mode="json", exclude_none=True),
    }


async def test_strict_outcomes_reach_guarded_inert_candidate() -> None:
    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    pantheon = instantiate_pantheon()
    huginn = cast(Any, pantheon["Huginn"])
    muninn = cast(Any, pantheon["Muninn"])
    norns = cast(Any, pantheon["Norns"])
    mimir = cast(Any, pantheon["Mimir"])
    for agent in (huginn, muninn, norns, mimir):
        agent.bind_bus(bus)
    bus.subscribe("object.event", "Muninn", muninn.on_typed_message)
    bus.subscribe("object.context-index", "Norns", norns.on_typed_message)
    bus.subscribe("object.rule-candidate", "Mimir", mimir.on_typed_message)

    await huginn.ingest(_raw(_outcome(1, label="verified", mode="enforce")))
    await huginn.ingest(_raw(_outcome(2, label="mismatch", mode="shadow")))

    cohorts = bus.messages_on("object.context-index")
    assert len(cohorts) == 1
    assert cohorts[0].payload["kind"] == "operating_pattern_cohort"
    assert {case["reusable"] for case in cohorts[0].payload["cases"]} == {True, False}
    assert len(bus.messages_on("object.rule-candidate")) == 1
    assert len(mimir.pending_candidates()) == 1
    assert mimir.pending_candidates()[0]["source_signal"] == "operating_pattern_cohort"

    await huginn.ingest(_raw(_outcome(2, label="mismatch", mode="shadow")))
    assert len(bus.messages_on("object.context-index")) == 1
