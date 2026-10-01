"""Heimdall publications above the tombstone cap stay replayable until published."""

from __future__ import annotations

import pytest
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.heimdall import Heimdall
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_TOPIC = "object.recovery-effect-observation"


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon(), handler_timeout=None)


def _payload(key: str, *, filler_bytes: int) -> dict[str, object]:
    return {
        "producer_principal": "Heimdall",
        "kind": "recovery_effect_observation",
        "correlation_id": f"large-{key}",
        "idempotency_key": f"large:{key}",
        "observation_note": "x" * filler_bytes,
    }


async def _rows(store: InMemoryStateStore) -> tuple[dict[str, object], ...]:
    return tuple(await store.read_states("pantheon/heimdall/publications/", limit=10))


async def test_large_publication_publishes_first_time_and_tombstones_digest_only() -> None:
    store = InMemoryStateStore()
    heimdall = Heimdall(state_store=store)
    bus = _bus()
    heimdall.bind_bus(bus)

    assert await heimdall._publish_once(_TOPIC, _payload("first", filler_bytes=9_000))  # noqa: SLF001

    assert len(bus.messages_on(_TOPIC)) == 1
    (row,) = await _rows(store)
    assert row["state"] == "published"
    assert "payload" not in row
    assert str(row["payload_digest"]).startswith("sha256:")


async def test_large_pending_publication_is_recovered_once_after_restart() -> None:
    store = InMemoryStateStore()
    checkpoint = Heimdall(state_store=store)
    payload = _payload("restart", filler_bytes=9_000)
    assert not await checkpoint._publish_once(_TOPIC, payload)  # noqa: SLF001
    (pending,) = await _rows(store)
    assert pending["state"] == "pending"
    assert pending["payload"] == payload

    restarted = Heimdall(state_store=store)
    bus = _bus()
    restarted.bind_bus(bus)

    assert await restarted.recover_publications() == 1
    assert await restarted.recover_publications() == 0
    messages = bus.messages_on(_TOPIC)
    assert len(messages) == 1
    assert messages[0].payload["idempotency_key"] == "large:restart"
    assert "publication:recovery_invalid_row" not in restarted.behavior_snapshot()


async def test_oversized_publication_is_rejected_before_checkpoint() -> None:
    store = InMemoryStateStore()
    heimdall = Heimdall(state_store=store)
    heimdall.bind_bus(_bus())

    with pytest.raises(ValueError, match="bounded outbox size"):
        await heimdall._publish_once(_TOPIC, _payload("huge", filler_bytes=600_000))  # noqa: SLF001

    assert len(await _rows(store)) == 0
    assert heimdall.behavior_snapshot()["publication:payload_too_large"] == 1
