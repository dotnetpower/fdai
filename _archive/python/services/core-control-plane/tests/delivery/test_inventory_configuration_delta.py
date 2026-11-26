from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.inventory_configuration_delta import (
    DEFAULT_FULL_REDELIVERY_SECONDS,
    FULL_REDELIVERY_ENV,
    LEDGER_PREFIX,
    StateBackedConfigurationDeltaPolicy,
    full_redelivery_seconds,
)
from fdai.delivery.inventory_configuration_events import (
    complete_configuration_delivery,
    prepare_configuration_delivery,
    publish_promoted_resource_events,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
SCOPE = "scope-example"


class _Comparison:
    def __init__(self, previous: str | None, unchanged: set[str]) -> None:
        self.previous = previous
        self.unchanged = frozenset(unchanged)

    async def unchanged_since_previous(self, generation: str) -> tuple[str | None, frozenset[str]]:
        del generation
        return self.previous, self.unchanged


def _observation(generation: str, count: int = 3) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation=generation,
        resources=tuple(
            ResourceRecord(resource_id=f"resource-{index}", type="compute.vm", props={"n": index})
            for index in range(count)
        ),
        links=(),
        complete=True,
        recorded_at=NOW,
    )


async def _deliver_previous(store: InMemoryStateStore, generation: str, *, complete: bool) -> None:
    previous = _observation(generation)
    await prepare_configuration_delivery(store, previous)
    if complete:
        await complete_configuration_delivery(store, previous)


async def _keys(bus: InMemoryEventBus) -> list[str]:
    return [item.key async for item in bus.subscribe("events", "reader")]


def _policy(
    store: InMemoryStateStore,
    comparison: _Comparison,
    *,
    seconds: int = DEFAULT_FULL_REDELIVERY_SECONDS,
    now: datetime = NOW,
) -> StateBackedConfigurationDeltaPolicy:
    return StateBackedConfigurationDeltaPolicy(
        store=store,
        comparison=comparison,
        full_redelivery_seconds=seconds,
        clock=lambda: now,
    )


async def _publish(
    observation: PromotedInventoryObservation,
    policy: StateBackedConfigurationDeltaPolicy | None,
    bus: InMemoryEventBus,
) -> int:
    return await publish_promoted_resource_events(
        observation, event_bus=bus, topic="events", scope_ref=SCOPE, delta_policy=policy
    )


async def test_first_delivery_is_full_and_records_the_full_redelivery() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()

    count = await _publish(_observation("g1"), _policy(store, _Comparison(None, set())), bus)

    assert count == 3
    assert await _keys(bus) == ["resource-0", "resource-1", "resource-2"]
    assert len(await store.read_states(LEDGER_PREFIX, limit=10)) == 1


async def test_unchanged_resources_are_omitted_but_still_accounted() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    await _deliver_previous(store, "g1", complete=True)
    await _publish(_observation("g1"), _policy(store, _Comparison(None, set())), bus)
    bus = InMemoryEventBus()

    count = await _publish(
        _observation("g2"), _policy(store, _Comparison("g1", {"resource-0", "resource-2"})), bus
    )

    assert count == 3
    assert await _keys(bus) == ["resource-1"]


async def test_incomplete_previous_delivery_forces_a_full_delivery() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    await _publish(_observation("g1"), _policy(store, _Comparison(None, set())), InMemoryEventBus())
    await _deliver_previous(store, "g1", complete=False)

    await _publish(
        _observation("g2"), _policy(store, _Comparison("g1", {"resource-0", "resource-1"})), bus
    )

    assert len(await _keys(bus)) == 3


async def test_full_redelivery_is_due_after_the_interval() -> None:
    store = InMemoryStateStore()
    await _deliver_previous(store, "g1", complete=True)
    await _publish(_observation("g1"), _policy(store, _Comparison(None, set())), InMemoryEventBus())
    later = NOW + timedelta(seconds=DEFAULT_FULL_REDELIVERY_SECONDS)
    bus = InMemoryEventBus()

    await _publish(
        _observation("g2"),
        _policy(store, _Comparison("g1", {"resource-0", "resource-1", "resource-2"}), now=later),
        bus,
    )

    assert len(await _keys(bus)) == 3


async def test_zero_interval_disables_suppression() -> None:
    store, bus = InMemoryStateStore(), InMemoryEventBus()
    await _deliver_previous(store, "g1", complete=True)

    await _publish(
        _observation("g2"),
        _policy(store, _Comparison("g1", {"resource-0"}), seconds=0),
        bus,
    )

    assert len(await _keys(bus)) == 3


async def test_failed_publication_does_not_record_a_full_redelivery() -> None:
    store = InMemoryStateStore()

    class _Failing(InMemoryEventBus):
        async def publish(self, topic: str, key: str, payload: object) -> object:  # type: ignore[override]
            raise RuntimeError("broker unavailable")

    with pytest.raises(RuntimeError):
        await _publish(_observation("g1"), _policy(store, _Comparison(None, set())), _Failing())

    assert await store.read_states(LEDGER_PREFIX, limit=10) == ()


async def test_without_a_policy_every_resource_is_sent() -> None:
    bus = InMemoryEventBus()

    assert await _publish(replace(_observation("g1"), generation="g1"), None, bus) == 3
    assert len(await _keys(bus)) == 3


def test_interval_environment_is_validated() -> None:
    assert full_redelivery_seconds({}) == DEFAULT_FULL_REDELIVERY_SECONDS
    assert full_redelivery_seconds({FULL_REDELIVERY_ENV: "0"}) == 0
    for invalid in ("-1", "abc", "604801"):
        with pytest.raises(ValueError, match="MUST be an integer"):
            full_redelivery_seconds({FULL_REDELIVERY_ENV: invalid})
