"""Heimdall repeated-event detection opens a real Incident only for one sustained episode."""

from __future__ import annotations

from typing import Any

from fdai.agents import Heimdall
from fdai.agents._framework.runtime import PantheonRuntime
from fdai.core.incident import (
    IncidentAutoOpenPolicy,
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    open_detected_incident_candidate,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_RAW_TOPIC = "fdai.change.events"


def _runtime() -> tuple[Heimdall, IncidentRegistry]:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    workflow = IncidentLifecycleWorkflow(
        registry=registry,
        allowed_agent_principals={"Huginn", "Heimdall", "Forseti"},
    )
    policy = IncidentAutoOpenPolicy()

    async def hook(candidate: dict[str, Any]) -> bool:
        return (
            await open_detected_incident_candidate(
                workflow=workflow, candidate=candidate, policy=policy
            )
            is not None
        )

    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic=_RAW_TOPIC,
        incident_candidate_hook=hook,
    )
    heimdall = runtime.agents["Heimdall"]
    assert isinstance(heimdall, Heimdall)
    return heimdall, registry


def _event(index: int, **overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "resource_id": "api-example",
        "event_type": "availability.probe_failed",
        "correlation_id": "episode-1",
        "idempotency_key": f"event-{index}",
        "severity": "high",
    }
    event.update(overrides)
    return event


async def test_a_sustained_correlated_episode_opens_exactly_one_incident() -> None:
    heimdall, registry = _runtime()

    for index in range(8):
        await heimdall.on_typed_message("object.event", _event(index))

    assert len(registry.snapshot()) == 1


async def test_findings_with_distinct_correlation_ids_never_reach_the_threshold() -> None:
    heimdall, registry = _runtime()

    for index in range(8):
        await heimdall.on_typed_message(
            "object.event", _event(index, correlation_id=f"episode-{index}")
        )

    assert registry.snapshot() == {}


async def test_correlation_disabled_events_never_open_an_incident() -> None:
    heimdall, registry = _runtime()

    for index in range(8):
        await heimdall.on_typed_message("object.event", _event(index, incident_correlation="none"))

    assert registry.snapshot() == {}


async def test_a_below_minimum_severity_episode_is_held_without_writing() -> None:
    heimdall, registry = _runtime()

    for index in range(8):
        await heimdall.on_typed_message("object.event", _event(index, severity="low"))

    assert registry.snapshot() == {}
