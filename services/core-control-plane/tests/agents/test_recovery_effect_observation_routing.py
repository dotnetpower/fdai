"""Observer-path routing for independent recovery post-effect observations.

An external recovery post-effect observation is a *claim* until the workflow
intake proves it. These tests drive the whole real path a claim travels:
``Huginn.ingest`` normalizes the raw external signal onto the shared ingress
topic, Heimdall - the pantheon's terminal effect observer - recognizes the
versioned event, proves Huginn normalized it, and relays a bounded record onto
the Heimdall-owned observation topic, where the dedicated observer consumer
group picks it up.

The successful path is never simulated: no test hands the intake a
fully-formed payload and no test calls Heimdall's handler in place of a
delivery, because either would prove routing that production does not have.
The principal an observation is validated against is therefore always the one
the bus authenticated on publish, never one a payload claims.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.agents._framework import runtime_subscriptions
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.heimdall_huginn_projection import (
    recovery_effect_observation_record,
)
from fdai.agents._framework.pantheon import PANTHEON_SPECS
from fdai.agents._framework.registry import PantheonRegistryError, load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.agents.huginn import Huginn
from fdai.core.workflow.recovery_effect_ingress import (
    DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS,
    RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION,
)

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
_TOPIC = runtime_subscriptions.RECOVERY_EFFECT_OBSERVATION_TOPIC


def _observation_attributes(**overrides: Any) -> dict[str, Any]:
    """Return the observation fields exactly as an external observer reports them."""

    attributes: dict[str, Any] = {
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
    attributes.update(overrides)
    return attributes


def _raw_signal(
    *,
    event_type: str = RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
    **attribute_overrides: Any,
) -> dict[str, Any]:
    """Return the raw external signal an ingress adapter hands to Huginn."""

    return {
        "id": "recovery-effect-1",
        "correlation_id": "correlation-recovery-1",
        "resource_id": "resource:example/rg/recovery-1",
        "source": "azure-resource-graph",
        "event_type": event_type,
        "attributes": _observation_attributes(**attribute_overrides),
    }


class _RecordingIntake:
    """Capture the topic, payload, and principal the observer subscription delivers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    async def observe(self, topic: str, payload: dict[str, Any]) -> None:
        if payload.get("event_type") != RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE:
            return
        self.calls.append((topic, payload, str(payload.get("producer_principal") or "")))


def _chain() -> tuple[InMemoryBus, Huginn, Heimdall, _RecordingIntake]:
    """Wire the production chain: Huginn ingress, Heimdall relay, observer intake."""

    bus = InMemoryBus(registry=load_pantheon(), isolate_handlers=False)
    huginn = Huginn(bus=bus)
    heimdall = Heimdall(bus=bus)
    bus.subscribe("object.event", "Heimdall", heimdall.on_typed_message)
    intake = _RecordingIntake()
    count = runtime_subscriptions.bind_recovery_effect_observation(
        bus,  # type: ignore[arg-type]
        intake.observe,
    )
    assert count == 1
    return bus, huginn, heimdall, intake


def test_an_external_observation_reaches_the_intake_through_huginn_and_heimdall() -> None:
    bus, huginn, heimdall, intake = _chain()

    asyncio.run(huginn.ingest(_raw_signal()))

    assert len(intake.calls) == 1
    topic, payload, principal = intake.calls[0]
    assert topic == _TOPIC
    assert principal == "Heimdall"
    assert payload["event_type"] == RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE
    assert payload["observation_schema_version"] == RECOVERY_EFFECT_OBSERVATION_SCHEMA_VERSION
    assert payload["attempt_identity_digest"] == "sha256:" + "1" * 64
    assert payload["correlation_id"] == "correlation-recovery-1"
    assert heimdall.behavior_snapshot()["recovery_effect_observation:relayed"] == 1
    # Huginn produced the claim; only Heimdall produced onto the intake topic.
    assert [message.principal for message in bus.messages_on("object.event")] == ["Huginn"]
    assert [message.principal for message in bus.messages_on(_TOPIC)] == ["Heimdall"]


def test_the_intake_topic_is_owned_by_the_one_principal_it_authorizes() -> None:
    """Heimdall owns the observation topic and is the only authorized producer."""

    assert DEFAULT_RECOVERY_EFFECT_OBSERVER_PRINCIPALS == frozenset({"Heimdall"})
    assert load_pantheon().owner_of_topic(_TOPIC) == "Heimdall"
    assert "RecoveryEffectObservation" in load_pantheon().get("Heimdall").owns


def test_a_claimed_producer_principal_never_survives_the_chain() -> None:
    """A forged attribute cannot displace the principal the bus authenticated."""

    _, huginn, _, intake = _chain()

    asyncio.run(huginn.ingest(_raw_signal(producer_principal="Thor")))

    assert len(intake.calls) == 1
    _, payload, principal = intake.calls[0]
    assert principal == "Heimdall"
    assert payload["producer_principal"] == "Heimdall"


def test_the_relayed_record_carries_only_declared_observation_fields() -> None:
    """The relay is an allowlist, so an external signal smuggles no extra key."""

    _, huginn, _, intake = _chain()

    asyncio.run(huginn.ingest(_raw_signal(smuggled_authority="granted")))

    _, payload, _ = intake.calls[0]
    assert "smuggled_authority" not in payload
    assert "attributes" not in payload


def test_the_relay_refuses_a_record_huginn_did_not_normalize() -> None:
    """Provenance is proven on every relayed record, not assumed from the topic."""

    normalized = {
        "producer_principal": "Huginn",
        "correlation_id": "correlation-recovery-1",
        "attributes": _observation_attributes(),
    }

    assert recovery_effect_observation_record(normalized) is not None
    assert recovery_effect_observation_record({**normalized, "producer_principal": "Thor"}) is None
    assert recovery_effect_observation_record({**normalized, "attributes": None}) is None


def test_no_peer_principal_can_inject_a_claim_onto_the_ingress_topic() -> None:
    """`object.event` has a single writer, so a claim can enter only via Huginn."""

    bus = InMemoryBus(registry=load_pantheon())

    with pytest.raises(PantheonRegistryError):
        asyncio.run(bus.publish("Thor", "object.event", _raw_signal()))


def test_an_unrelated_ingested_event_is_never_routed_to_the_intake() -> None:
    _, huginn, _, intake = _chain()

    asyncio.run(huginn.ingest(_raw_signal(event_type="change_detected")))

    assert intake.calls == []


def test_the_intake_never_reads_the_shared_ingress_topic() -> None:
    """Negative control for the routing defect this module exists to prevent.

    A fully-formed payload published straight onto `object.event` MUST NOT
    reach the intake: the intake reads only the Heimdall-owned topic, so the
    relay cannot be skipped.
    """

    bus, _, _, intake = _chain()

    asyncio.run(
        bus.publish(
            "Huginn",
            "object.event",
            {
                "correlation_id": "correlation-recovery-1",
                "idempotency_key": "recovery-effect-1",
                "resource_id": "resource:example/rg/recovery-1",
                "event_type": RECOVERY_EFFECT_OBSERVATION_EVENT_TYPE,
                **_observation_attributes(),
            },
        )
    )

    assert intake.calls == []
    assert runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL not in {
        name for name, _ in bus.subscribers["object.event"]
    }


def test_no_observer_subscription_exists_without_a_bound_handler() -> None:
    bus = InMemoryBus(registry=load_pantheon())

    count = runtime_subscriptions.bind_recovery_effect_observation(
        bus,  # type: ignore[arg-type]
        None,
    )

    assert count == 0
    assert bus.subscribers[_TOPIC] == []


def test_the_observer_group_is_distinct_from_every_agent() -> None:
    bus, _, _, _ = _chain()

    principals = {name for name, _ in bus.subscribers[_TOPIC]}

    assert principals == {runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL}
    assert runtime_subscriptions.RECOVERY_EFFECT_OBSERVER_PRINCIPAL not in {
        spec.name for spec in PANTHEON_SPECS
    }
