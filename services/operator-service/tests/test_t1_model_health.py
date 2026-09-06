"""Core timing projections cannot invent current or endpoint-bearing health."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fdai_operator_service.families.conversation.contracts import ConversationQuery, PrincipalScope
from fdai_operator_service.families.conversation.semantic_turn_runtime import (
    SemanticTurnConversationAdapters,
)
from fdai_operator_service.families.conversation.t1_model_health import (
    T1ModelHealthReader,
    t1_model_health,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _projection(now=NOW):
    return {
        "schema_version": 1,
        "source": "core-t1-mini-routing",
        "execution_authority": False,
        "model": "narrator-mini",
        "endpoint": "https://example.com",
        "router": {
            "chose": "narrator-mini",
            "reason": "latency",
            "updated_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=600)).isoformat(),
            "interval_seconds": 300,
            "candidates": [
                {
                    "deployment": "narrator-mini",
                    "status": "measured",
                    "measured_at": now.isoformat(),
                    "p50_ms": 100.0,
                    "p95_ms": 100.0,
                    "samples": 1,
                    "history_ms": [100.0],
                    "endpoint": "https://example.com",
                }
            ],
        },
    }


def test_current_core_measurement_is_visible_without_endpoints():
    result = t1_model_health(_projection(), now=NOW)
    assert result["model"] == "narrator-mini"
    assert result["router"]["reason"] == "latency"
    assert "endpoint" not in str(result)


def test_expired_measurement_cannot_claim_current_model_or_fastest():
    result = t1_model_health(_projection(), now=NOW + timedelta(seconds=601))
    assert result["model"] is None
    assert result["router"]["reason"] == "stale"
    assert result["router"]["candidates"][0]["samples"] == 0


def test_individual_sample_expires_before_a_newer_projection_heartbeat():
    value = _projection()
    value["router"]["candidates"][0]["measured_at"] = (NOW - timedelta(seconds=100)).isoformat()
    result = t1_model_health(value, now=NOW + timedelta(seconds=501))
    assert result["model"] is None
    assert result["router"]["reason"] == "stale"


@pytest.mark.parametrize(
    "change",
    [
        {"source": "operator-authored"},
        {"execution_authority": True},
        {"model": "unmeasured-mini"},
        {"schema_version": 2},
    ],
)
def test_invalid_provenance_is_unavailable(change):
    value = _projection()
    value.update(change)
    assert t1_model_health(value, now=NOW) == {"model": None}


@pytest.mark.parametrize(
    "change",
    [
        {"p50_ms": float("nan")},
        {"samples": 0},
        {"status": "failed"},
        {"measured_at": "2025-01-01T00:00:00+00:00"},
    ],
)
def test_invalid_latency_claim_is_unavailable(change):
    value = deepcopy(_projection())
    value["router"]["candidates"][0].update(change)
    assert t1_model_health(value, now=NOW) == {"model": None}


def test_missing_core_projection_preserves_unknown_model():
    assert t1_model_health({}, now=NOW) == {"model": None}


async def test_semantic_health_reads_the_core_projection_without_enabling_legacy_stream():
    class Store:
        async def read_state(self, key):
            assert key == "conversation:t1-mini-routing:v1"
            return _projection(datetime.now(UTC))

    adapters = SemanticTurnConversationAdapters(
        bridge=SimpleNamespace(health=lambda: {"available": True, "mode": "semantic-event-bus"}),
        fallback_projections=object(),
        fallback_outbox=object(),
        fallback_streams=object(),
        t1_model_health_reader=T1ModelHealthReader(Store()),
    )
    health = await adapters.read(
        ConversationQuery(
            operation="chat.health", scope=PrincipalScope("reader", frozenset({"Reader"}))
        )
    )
    assert health.body["available"] is True
    assert health.body["mode"] == "semantic-event-bus"
    assert health.body["model"] == "narrator-mini"
    assert health.body["router"]["reason"] == "latency"
    assert health.body["endpoint"] is None
