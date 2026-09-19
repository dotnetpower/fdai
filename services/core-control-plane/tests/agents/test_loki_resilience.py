"""Loki ResilienceScore producer and authority-boundary regressions."""

from __future__ import annotations

import math

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.loki import Loki


def _resilience_event(**attributes: object) -> dict[str, object]:
    return {
        "producer_principal": "Huginn",
        "correlation_id": "resilience-correlation-1",
        "idempotency_key": "resilience-score-1",
        "event_id": "event:resilience-score-1",
        "event_type": "specialist.resilience_score",
        "detected_at": "2028-01-02T00:00:00+00:00",
        "resource_id": "resource-1",
        "attributes": attributes,
    }


def _valid_attributes() -> dict[str, object]:
    return {
        "score": 0.72,
        "action_type": "ops.restart-service",
        "effects": [
            {
                "objective_id": "objective.availability",
                "utility": 0.8,
                "confidence": 0.9,
                "metric": "availability",
                "expected_min": 0.7,
                "expected_max": 0.9,
                "observation_window_seconds": 300,
            }
        ],
        "evidence_refs": ["event:resilience-score-1"],
    }


async def test_loki_publishes_valid_resilience_score_candidate() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    loki = Loki(bus=bus)
    forseti = Forseti(bus=bus)
    bus.subscribe("object.resilience-score", "Forseti", forseti.on_typed_message)

    await loki.on_typed_message("object.event", _resilience_event(**_valid_attributes()))

    (message,) = bus.messages_on("object.resilience-score")
    assert message.principal == "Loki"
    assert message.payload["kind"] == "cross_vertical_candidate"
    assert message.payload["score"] == 0.72
    assert message.payload["resource_id"] == "resource-1"
    assert forseti.behavior_snapshot()["cross_vertical_candidate:pending"] == 1
    assert bus.messages_on("object.verdict") == []
    answer = await loki.introspect("resilience score for resource-1", {"locale": "en"})
    assert answer.facts["resilience_score_available"] is True
    assert answer.facts["resilience_score"] == 0.72
    assert "0.720" in answer.answer


@pytest.mark.parametrize("score", [True, math.nan, math.inf, -0.1, 1.1])
async def test_loki_rejects_invalid_resilience_scores(score: object) -> None:
    bus = InMemoryBus(registry=load_pantheon())
    loki = Loki(bus=bus)
    attributes = _valid_attributes()
    attributes["score"] = score

    await loki.on_typed_message("object.event", _resilience_event(**attributes))

    assert bus.messages_on("object.resilience-score") == []
    assert loki.behavior_snapshot()["resilience_score:invalid"] == 1


@pytest.mark.parametrize(
    "attribute, value",
    [
        ("action_type", ""),
        ("effects", []),
        ("evidence_refs", []),
    ],
)
async def test_loki_rejects_incomplete_resilience_candidates(attribute: str, value: object) -> None:
    bus = InMemoryBus(registry=load_pantheon())
    loki = Loki(bus=bus)
    attributes = _valid_attributes()
    attributes[attribute] = value

    await loki.on_typed_message("object.event", _resilience_event(**attributes))

    assert bus.messages_on("object.resilience-score") == []
    assert loki.behavior_snapshot()["resilience_score:invalid"] == 1


async def test_loki_rejects_forged_resilience_event_principal() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    loki = Loki(bus=bus)
    event = _resilience_event(**_valid_attributes())
    event["producer_principal"] = "External"

    await loki.on_typed_message("object.event", event)

    assert bus.messages_on("object.resilience-score") == []
    assert loki.behavior_snapshot()["resilience_score:invalid"] == 1


async def test_loki_score_substitution_closes_candidate_set_to_hil() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    loki = Loki(bus=bus)
    forseti = Forseti(bus=bus)
    bus.subscribe("object.resilience-score", "Forseti", forseti.on_typed_message)
    first = _valid_attributes()
    substituted = _valid_attributes()
    substituted["score"] = 0.73

    await loki.on_typed_message("object.event", _resilience_event(**first))
    await loki.on_typed_message("object.event", _resilience_event(**substituted))

    assert len(bus.messages_on("object.resilience-score")) == 2
    (verdict,) = bus.messages_on("object.verdict")
    assert verdict.payload["risk_verdict"] == "hil"
    assert verdict.payload["reason"] == "cross_vertical_candidate_replay_conflict"
