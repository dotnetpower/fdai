"""Observer-path routing for independent recovery post-effect observations.

The recovery effect observation must reach its durable intake through a
dedicated observer consumer group, and the principal it is validated against
must be the one the bus authenticated on publish, never one a payload claims.
These tests drive the exact versioned event over the pantheon bus.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.agents._framework import runtime_subscriptions
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.registry import load_pantheon
from fdai.core.workflow.recovery_effect_ingress import (
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
)

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def _event(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "recovery-effect-1",
        "correlation_id": "correlation-recovery-1",
        "resource_id": "resource:example/rg/recovery-1",
        "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
        "observation_schema_version": RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
        "process_id": "process-recovery-1",
        "recovery_step_id": f"recover_{'a' * 32}",
        "attempt_identity_digest": "sha256:" + "1" * 64,
        "target_resource_id": "resource:example/rg/recovery-1",
        "provider_receipt_digest": "sha256:" + "d" * 64,
        "observer_identity": "heimdall-observer@example.com",
        "observer_authority_class": "authoritative_external",
        "provider_identity": "provider@example.com",
        "purpose_version": "1.0.0",
        "method_version": "1.0.0",
        "event_time": (_NOW - timedelta(minutes=3)).isoformat(),
        "recorded_time": (_NOW - timedelta(minutes=2)).isoformat(),
        "freshness_policy_seconds": 600,
        "completeness": True,
        "provenance": "azure-resource-graph",
        "conflict_status": "none",
        "synthetic": False,
        "evidence_digest": "sha256:" + "7" * 64,
        "expected_effect_digest": "sha256:" + "8" * 64,
        "approved_envelope_digest": "sha256:" + "9" * 64,
        "action_digest": "sha256:" + "3" * 64,
        "evidence_window_start": (_NOW - timedelta(minutes=4)).isoformat(),
        "evidence_window_end": (_NOW - timedelta(minutes=1)).isoformat(),
        "watermarks": [
            {
                "source_id": "azure-activity-log",
                "watermark": (_NOW - timedelta(minutes=1)).isoformat(),
                "final": True,
                "watermark_digest": "sha256:" + "4" * 64,
            }
        ],
        "forbidden_effect_observed": False,
        "envelope_contained": True,
        "success": True,
    }
    payload.update(overrides)
    return payload


class _RecordingIngress:
    """Capture the payload and principal the observer subscription delivers."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []

    async def observe(self, topic: str, payload: dict[str, Any]) -> None:
        del topic
        if payload.get("event_type") != RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
            return
        self.calls.append((payload, str(payload.get("producer_principal") or "")))


def _bound() -> tuple[InMemoryBus, _RecordingIngress]:
    bus = InMemoryBus(registry=load_pantheon())
    handler = _RecordingIngress()
    count = runtime_subscriptions.bind_recovery_effect_observation(
        bus,  # type: ignore[arg-type]
        handler.observe,
    )
    assert count == 1
    return bus, handler


def test_the_observer_subscription_receives_the_versioned_event() -> None:
    bus, handler = _bound()

    asyncio.run(bus.publish("Huginn", "object.event", _event()))

    assert len(handler.calls) == 1
    payload, principal = handler.calls[0]
    assert principal == "Huginn"
    assert payload["event_type"] == RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE
    assert payload["observation_schema_version"] == RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION


def test_the_bus_overwrites_a_claimed_producer_principal() -> None:
    bus, handler = _bound()

    asyncio.run(bus.publish("Huginn", "object.event", _event(producer_principal="Thor")))

    assert len(handler.calls) == 1
    _, principal = handler.calls[0]
    assert principal == "Huginn"


def test_an_unrelated_event_is_never_routed_to_the_intake() -> None:
    bus, handler = _bound()

    asyncio.run(bus.publish("Huginn", "object.event", _event(event_type="change_detected")))

    assert handler.calls == []


def test_no_observer_subscription_exists_without_a_bound_handler() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    count = runtime_subscriptions.bind_recovery_effect_observation(
        bus,  # type: ignore[arg-type]
        None,
    )

    assert count == 0
    assert bus.subscribers["object.event"] == []


def test_the_observer_group_is_distinct_from_every_agent() -> None:
    bus, _ = _bound()

    principals = {name for name, _ in bus.subscribers["object.event"]}

    assert principals == {runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL}
    assert runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL not in {
        spec.name for spec in PANTHEON_SPECS
    }
