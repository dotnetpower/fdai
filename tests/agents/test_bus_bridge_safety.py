"""Safety regressions for the Pantheon event-bus boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.registry import load_pantheon
from fdai.shared.providers.event_bus import EventEnvelope
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


def _bridge(provider: InMemoryEventBus | None = None) -> EventBusBridge:
    return EventBusBridge(
        provider=provider or InMemoryEventBus(),
        registry=load_pantheon(),
    )


def test_publish_stamps_authoritative_principal_and_schema_version() -> None:
    provider = InMemoryEventBus()
    bridge = _bridge(provider)

    asyncio.run(
        bridge.publish(
            "Forseti",
            "object.verdict",
            {
                "correlation_id": "corr-1",
                "producer_principal": "Bragi",
                "schema_version": 999,
            },
        )
    )

    payload = provider._records["object.verdict"][0][1]
    assert payload["producer_principal"] == "Forseti"
    assert payload["schema_version"] == 999
    assert payload["envelope_schema_version"] == 1


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        (
            {"resource_id": "vm-1", "idempotency_key": "idem-1"},
            "correlation_id",
        ),
        (
            {"correlation_id": "corr-1", "idempotency_key": "idem-1"},
            "resource_id",
        ),
        (
            {"correlation_id": "corr-1", "resource_id": "vm-1"},
            "idempotency_key",
        ),
    ],
)
def test_publish_rejects_incomplete_mutation_envelope(
    payload: dict[str, object],
    missing_field: str,
) -> None:
    provider = InMemoryEventBus()
    bridge = _bridge(provider)

    with pytest.raises(ValueError, match=missing_field):
        asyncio.run(bridge.publish("Thor", "object.action-run", payload))

    assert "object.action-run" not in provider._records


def test_subscribe_rejects_unknown_object_topic() -> None:
    bridge = _bridge()

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        return None

    with pytest.raises(ValueError, match="unknown pantheon object topic"):
        bridge.subscribe("object.verdit", "Thor", handler)


def test_owned_topic_principal_verification_cannot_be_disabled() -> None:
    provider = InMemoryEventBus()
    bridge = _bridge(provider)
    seen: list[dict[str, object]] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        seen.append(payload)

    bridge.subscribe("object.verdict", "Thor", handler)
    asyncio.run(
        provider.publish(
            "object.verdict",
            "corr-1",
            {"correlation_id": "corr-1", "producer_principal": "Bragi"},
        )
    )
    _drain(bridge)

    assert seen == []
    assert bridge.metrics.producer_principal_mismatch == 1


def test_ordered_poison_halt_and_handler_timeout_are_safe_defaults() -> None:
    bridge = _bridge()

    assert bridge.halt_ordered_topic_on_poison is True
    assert bridge.handler_timeout is not None
    assert bridge.handler_timeout > 0


class _FailingDeadLetterBus(InMemoryEventBus):
    async def dead_letter(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
        reason: str,
    ) -> None:
        del topic, key, payload, reason
        raise ConnectionError("DLQ unavailable")


def test_dead_letter_failure_retries_then_propagates() -> None:
    provider = _FailingDeadLetterBus()
    bridge = EventBusBridge(
        provider=provider,
        registry=load_pantheon(),
        dead_letter_max_retries=2,
        dead_letter_retry_backoff=0.0,
    )
    envelope = EventEnvelope(
        topic="object.verdict",
        key="corr-1",
        payload={"correlation_id": "corr-1", "producer_principal": "Bragi"},
        offset=1,
    )

    with pytest.raises(ConnectionError, match="DLQ unavailable"):
        asyncio.run(
            bridge._safe_dead_letter(
                group_id="fdai-pantheon.Thor",
                topic="object.verdict",
                envelope=envelope,
                reason="forged producer",
            )
        )

    assert bridge.metrics.dead_letter_errors == 3


def test_redrive_rejects_forged_owned_topic_payload() -> None:
    provider = InMemoryEventBus()
    bridge = _bridge(provider)
    seen: list[dict[str, object]] = []

    async def handler(_topic: str, payload: dict[str, object]) -> None:
        seen.append(payload)

    asyncio.run(
        provider.dead_letter(
            "object.verdict",
            "corr-1",
            {"correlation_id": "corr-1", "producer_principal": "Bragi"},
            reason="seed",
        )
    )

    result = asyncio.run(bridge.redrive("object.verdict", handler))

    assert result == {"redriven": 0, "failed": 1}
    assert seen == []


def test_redrive_reparks_original_payload_without_nested_wrapper() -> None:
    provider = InMemoryEventBus()
    bridge = _bridge(provider)

    async def handler(_topic: str, _payload: dict[str, object]) -> None:
        raise RuntimeError("still failing")

    original = {
        "correlation_id": "corr-1",
        "producer_principal": "Forseti",
        "schema_version": 1,
    }
    asyncio.run(provider.dead_letter("object.verdict", "corr-1", original, reason="seed"))

    result = asyncio.run(bridge.redrive("object.verdict", handler))

    assert result == {"redriven": 0, "failed": 1}
    reparking_wrapper = provider._records["object.verdict.dlq"][-1][1]
    assert reparking_wrapper["payload"] == original


def test_redrive_rejects_non_positive_record_limit() -> None:
    bridge = _bridge()

    with pytest.raises(ValueError, match="max_records"):
        asyncio.run(bridge.redrive("object.verdict", _noop_handler, max_records=0))


async def _noop_handler(_topic: str, _payload: dict[str, object]) -> None:
    return None


def _drain(bridge: EventBusBridge) -> None:
    async def drive() -> None:
        run_task = asyncio.create_task(bridge.run())
        for _ in range(50):
            await asyncio.sleep(0)
        await bridge.stop()
        run_task.cancel()
        try:
            await run_task
        except (asyncio.CancelledError, Exception):  # noqa: S110 - test cleanup
            pass

    asyncio.run(drive())
