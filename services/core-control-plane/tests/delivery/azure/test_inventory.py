"""AzureResourceGraphInventory - structural + safety invariants (P1 W-2).

Assertions the stub must satisfy so downstream code can be wired against
a real interface:

- Full-scan streams end with an atomic-promote fence (``final=True``).
- Concurrent shard queries respect ``max_concurrent_queries``.
- On query failure, no ``final=True`` batch is emitted - a caller MUST
  retain the previous graph (fail-closed).
- Duplicate resources / links inside one shard are collapsed
  (idempotent-upsert precondition).
- The delta stream also ends with ``final=True``.
- The adapter satisfies the runtime-checkable ``Inventory`` Protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from fdai.delivery.azure.inventory import (
    AzureInventoryConfig,
    AzureResourceGraphInventory,
    ResourceQueryFn,
)
from fdai.shared.providers import (
    Inventory,
    InventoryBatch,
    LinkRecord,
    ResourceRecord,
)


def _rr(resource_id: str, rtype: str = "compute.vm") -> ResourceRecord:
    return ResourceRecord(resource_id=resource_id, type=rtype)


def _lr(from_id: str, to_id: str, link_type: str = "contains") -> LinkRecord:
    return LinkRecord(
        from_id=from_id,
        from_type="compute.vm",
        link_type=link_type,
        to_id=to_id,
        to_type="resource-group",
    )


def _adapter(
    query: ResourceQueryFn,
    *,
    types: tuple[str, ...] = ("compute.vm", "object-storage"),
    concurrency: int = 4,
) -> AzureResourceGraphInventory:
    return AzureResourceGraphInventory(
        config=AzureInventoryConfig(resource_types=types, max_concurrent_queries=concurrency),
        query=query,
    )


def test_config_rejects_zero_or_negative_concurrency() -> None:
    async def _noop(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    with pytest.raises(ValueError):
        AzureResourceGraphInventory(
            config=AzureInventoryConfig(resource_types=(), max_concurrent_queries=0),
            query=_noop,
        )


def test_adapter_satisfies_inventory_protocol() -> None:
    async def _noop(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    assert isinstance(_adapter(_noop), Inventory)


@pytest.mark.asyncio
async def test_full_snapshot_ends_with_final_true() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (_rr(f"{rt}/1"),), ()

    adapter = _adapter(_q)
    seen: list[InventoryBatch] = []
    async for batch in adapter.full_snapshot():
        seen.append(batch)

    assert seen  # at least the fence
    assert seen[-1].final is True
    assert seen[-1].resources == ()
    assert seen[-1].links == ()
    # Every prior batch had payload; the fence never carries data.
    for batch in seen[:-1]:
        assert batch.final is False
        assert batch.resources or batch.links


@pytest.mark.asyncio
async def test_full_snapshot_dedupes_resources_and_links_per_shard() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        # Same resource id repeated three times; same link twice.
        return (
            [_rr("dup", rtype=rt)] * 3,
            [_lr("child", "parent")] * 2,
        )

    adapter = _adapter(_q, types=("compute.vm",))
    resources: list[ResourceRecord] = []
    links: list[LinkRecord] = []
    async for batch in adapter.full_snapshot():
        resources.extend(batch.resources)
        links.extend(batch.links)

    assert len(resources) == 1
    assert resources[0].resource_id == "dup"
    assert len(links) == 1


@pytest.mark.asyncio
async def test_full_snapshot_respects_concurrency_semaphore() -> None:
    max_conc = 2
    live = 0
    peak = 0
    lock = asyncio.Lock()

    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        nonlocal live, peak
        async with lock:
            live += 1
            peak = max(peak, live)
        try:
            # Give the scheduler room to overlap.
            await asyncio.sleep(0.01)
            return (_rr(f"{rt}/1"),), ()
        finally:
            async with lock:
                live -= 1

    adapter = _adapter(
        _q,
        types=tuple(f"rt-{i}" for i in range(10)),
        concurrency=max_conc,
    )
    async for _ in adapter.full_snapshot():
        pass

    assert peak <= max_conc, f"concurrency limit breached: peak={peak}"


@pytest.mark.asyncio
async def test_full_snapshot_fails_closed_on_query_error() -> None:
    async def _q(rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        if rt == "boom":
            raise RuntimeError("ARG unavailable")
        return (_rr(f"{rt}/1"),), ()

    adapter = _adapter(_q, types=("compute.vm", "boom", "object-storage"))
    seen: list[InventoryBatch] = []
    with pytest.raises(RuntimeError, match="ARG unavailable"):
        async for batch in adapter.full_snapshot():
            seen.append(batch)

    # Critical: no fence batch ever appeared, so the caller retains the
    # previous graph (docs/roadmap/architecture/csp-neutrality.md § 5).
    assert not any(batch.final for batch in seen)


@pytest.mark.asyncio
async def test_delta_stub_emits_final_true_empty_batch() -> None:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    adapter = _adapter(_q)
    seen: list[InventoryBatch] = []
    async for batch in adapter.delta(cursor="cur-1"):
        seen.append(batch)

    assert len(seen) == 1
    assert seen[0].final is True
    assert seen[0].resources == ()
    assert seen[0].links == ()


@pytest.mark.asyncio
async def test_full_snapshot_with_no_resource_types_still_yields_fence() -> None:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        raise AssertionError("should not be called")  # pragma: no cover

    adapter = _adapter(_q, types=())
    seen: list[InventoryBatch] = []
    async for batch in adapter.full_snapshot():
        seen.append(batch)
    assert len(seen) == 1
    assert seen[0].final is True


# ---------------------------------------------------------------------------
# Delta stream with a bound ActivityLogFetchFn (P0-2)
# ---------------------------------------------------------------------------


def _delta_adapter(delta_fetch, *, max_delta_pages: int = 64) -> AzureResourceGraphInventory:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    return AzureResourceGraphInventory(
        config=AzureInventoryConfig(
            resource_types=("compute.vm",),
            max_delta_pages=max_delta_pages,
        ),
        query=_q,
        delta_fetch=delta_fetch,
    )


@pytest.mark.asyncio
async def test_delta_streams_change_batches_with_advancing_cursor() -> None:
    from fdai.delivery.azure.inventory import ActivityLogPage

    async def _fetch(cursor: str) -> ActivityLogPage:
        if "\x1f" not in cursor:
            # fresh resume cursor -> first page
            return ActivityLogPage(
                resources=(_rr("resource-group/rg-a/vm-a"),),
                cursor="\x1fhttps://next/page2",
                has_more=True,
            )
        # continuation -> last page
        return ActivityLogPage(
            resources=(_rr("resource-group/rg-a/vm-b"),),
            cursor="2026-07-10T06:00:00+00:00",
            has_more=False,
        )

    adapter = _delta_adapter(_fetch)
    seen: list[InventoryBatch] = []
    async for batch in adapter.delta(cursor="2026-07-10T05:00:00+00:00"):
        seen.append(batch)

    assert [b.final for b in seen] == [False, False, True]
    assert seen[0].resources[0].resource_id == "resource-group/rg-a/vm-a"
    assert seen[1].resources[0].resource_id == "resource-group/rg-a/vm-b"
    assert seen[2].cursor == "2026-07-10T06:00:00+00:00"


@pytest.mark.asyncio
async def test_delta_fails_closed_without_final_on_fetch_error() -> None:
    from fdai.delivery.azure.inventory import ActivityLogPage

    async def _fetch(cursor: str) -> ActivityLogPage:
        raise RuntimeError("activity log unreachable")

    adapter = _delta_adapter(_fetch)
    seen: list[InventoryBatch] = []
    with pytest.raises(RuntimeError):
        async for batch in adapter.delta(cursor="cur-1"):
            seen.append(batch)

    assert all(not b.final for b in seen)


@pytest.mark.asyncio
async def test_delta_page_cap_stops_and_returns_fence() -> None:
    from fdai.delivery.azure.inventory import ActivityLogPage

    async def _fetch(cursor: str) -> ActivityLogPage:
        page = int(cursor.rsplit("-", maxsplit=1)[-1]) if cursor.startswith("page-") else 0
        return ActivityLogPage(
            resources=(_rr("resource-group/rg-a/vm-x"),),
            cursor=f"page-{page + 1}",
            has_more=True,
        )

    adapter = _delta_adapter(_fetch, max_delta_pages=3)
    seen: list[InventoryBatch] = []
    async for batch in adapter.delta(cursor="cur-1"):
        seen.append(batch)

    assert len([b for b in seen if not b.final]) == 3
    assert seen[-1].final is True
    assert seen[-1].cursor == "page-3"


@pytest.mark.parametrize("next_cursor", [None, "cur-1"])
@pytest.mark.asyncio
async def test_delta_rejects_non_advancing_continuation_cursor(
    next_cursor: str | None,
) -> None:
    from fdai.delivery.azure.inventory import ActivityLogPage

    async def _fetch(cursor: str) -> ActivityLogPage:
        return ActivityLogPage(
            resources=(_rr("resource-group/rg-a/vm-x"),),
            cursor=next_cursor,
            has_more=True,
        )

    adapter = _delta_adapter(_fetch)
    seen: list[InventoryBatch] = []
    with pytest.raises(RuntimeError, match="cursor did not advance"):
        async for batch in adapter.delta(cursor="cur-1"):
            seen.append(batch)

    assert seen == []


@pytest.mark.asyncio
async def test_delta_dedupes_within_a_page() -> None:
    from fdai.delivery.azure.inventory import ActivityLogPage

    async def _fetch(cursor: str) -> ActivityLogPage:
        return ActivityLogPage(
            resources=(
                _rr("resource-group/rg-a/vm-a"),
                _rr("resource-group/rg-a/vm-a"),
            ),
            cursor="2026-07-10T06:00:00+00:00",
            has_more=False,
        )

    adapter = _delta_adapter(_fetch)
    seen: list[InventoryBatch] = []
    async for batch in adapter.delta(cursor="cur-1"):
        seen.append(batch)

    change = [b for b in seen if not b.final]
    assert len(change) == 1
    assert len(change[0].resources) == 1


@pytest.mark.asyncio
async def test_config_rejects_zero_max_delta_pages() -> None:
    async def _q(_rt: str) -> tuple[Sequence[ResourceRecord], Sequence[LinkRecord]]:
        return (), ()

    with pytest.raises(ValueError):
        AzureResourceGraphInventory(
            config=AzureInventoryConfig(resource_types=(), max_delta_pages=0),
            query=_q,
        )
