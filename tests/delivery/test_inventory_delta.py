"""Inventory delta forwarding and cursor safety tests."""

from __future__ import annotations

import pytest

from fdai.delivery.inventory_delta import _resource_event, forward_inventory_delta
from fdai.shared.providers.inventory import InventoryBatch, LinkRecord, ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _Inventory:
    def __init__(
        self,
        *,
        final: bool = True,
        orphan_link: bool = False,
        last_seen: str | None = "2026-07-15T00:00:00Z",
    ) -> None:
        self.final = final
        self.orphan_link = orphan_link
        self.last_seen = last_seen
        self.seen_cursor = ""

    async def delta(self, cursor: str):  # type: ignore[no-untyped-def]
        self.seen_cursor = cursor
        yield InventoryBatch(
            resources=(
                ResourceRecord(
                    resource_id="resource:example/vm-1",
                    type="compute.vm",
                    props={"status": "updated"},
                    last_seen=self.last_seen,
                ),
            ),
            links=(
                LinkRecord(
                    from_id="resource:example/vm-1",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="resource:example/database-1",
                    to_type="postgresql",
                ),
            )
            if not self.orphan_link
            else (
                LinkRecord(
                    from_id="resource:example/missing-owner",
                    from_type="compute.vm",
                    link_type="depends_on",
                    to_id="resource:example/database-1",
                    to_type="postgresql",
                ),
            ),
            cursor="cursor-next",
        )
        if self.final:
            yield InventoryBatch(final=True, cursor="cursor-next")


@pytest.mark.asyncio
async def test_forward_delta_publishes_event_and_advances_cursor() -> None:
    inventory = _Inventory()
    state = InMemoryStateStore()
    bus = InMemoryEventBus()

    published = await forward_inventory_delta(
        inventory=inventory,
        state_store=state,
        event_bus=bus,
        topic="events",
        scope="subscription-1",
    )

    assert published == 1
    records = [item async for item in bus.subscribe("events", "reader")]
    assert records[0].payload["event_type"] == "inventory.resource_changed"
    assert records[0].payload["payload"]["resource"]["type"] == "compute.vm"
    assert records[0].payload["payload"]["inventory_change"]["links"] == [
        {
            "change_kind": "upsert",
            "from_id": "resource:example/vm-1",
            "from_type": "compute.vm",
            "link_type": "depends_on",
            "to_id": "resource:example/database-1",
            "to_type": "postgresql",
            "props": {},
        }
    ]
    cursor = await state.read_state("inventory_delta_cursor:subscription-1")
    assert cursor == {"cursor": "cursor-next"}


@pytest.mark.asyncio
async def test_forward_delta_preserves_cursor_without_final_fence() -> None:
    inventory = _Inventory(final=False)
    state = InMemoryStateStore()
    await state.write_state("inventory_delta_cursor:subscription-1", {"cursor": "cursor-old"})

    with pytest.raises(RuntimeError, match="final fence"):
        await forward_inventory_delta(
            inventory=inventory,
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope="subscription-1",
        )

    cursor = await state.read_state("inventory_delta_cursor:subscription-1")
    assert cursor == {"cursor": "cursor-old"}
    assert inventory.seen_cursor == "cursor-old"


@pytest.mark.asyncio
async def test_forward_delta_rejects_link_without_owner_resource() -> None:
    inventory = _Inventory(orphan_link=True)
    state = InMemoryStateStore()
    await state.write_state("inventory_delta_cursor:subscription-1", {"cursor": "cursor-old"})

    with pytest.raises(RuntimeError, match="link owner resource"):
        await forward_inventory_delta(
            inventory=inventory,
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope="subscription-1",
        )

    assert await state.read_state("inventory_delta_cursor:subscription-1") == {
        "cursor": "cursor-old"
    }


def test_delta_event_identity_includes_relationship_payload() -> None:
    resource = ResourceRecord(
        resource_id="resource:example/vm-1",
        type="compute.vm",
        last_seen="2026-07-15T00:00:00Z",
    )
    first = _resource_event(
        scope="subscription-1",
        resource=resource,
        links=(
            LinkRecord(
                from_id=resource.resource_id,
                from_type=resource.type,
                link_type="depends_on",
                to_id="resource:example/database-1",
                to_type="postgresql",
            ),
        ),
    )
    second = _resource_event(
        scope="subscription-1",
        resource=resource,
        links=(
            LinkRecord(
                from_id=resource.resource_id,
                from_type=resource.type,
                link_type="depends_on",
                to_id="resource:example/database-2",
                to_type="postgresql",
            ),
        ),
    )

    assert first.event_id != second.event_id
    assert first.idempotency_key != second.idempotency_key


@pytest.mark.parametrize("last_seen", [None, "not-a-timestamp"])
@pytest.mark.asyncio
async def test_forward_delta_rejects_missing_or_invalid_ordering_timestamp(
    last_seen: str | None,
) -> None:
    state = InMemoryStateStore()
    await state.write_state("inventory_delta_cursor:subscription-1", {"cursor": "cursor-old"})

    with pytest.raises(ValueError, match="last_seen"):
        await forward_inventory_delta(
            inventory=_Inventory(last_seen=last_seen),
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope="subscription-1",
        )

    assert await state.read_state("inventory_delta_cursor:subscription-1") == {
        "cursor": "cursor-old"
    }
