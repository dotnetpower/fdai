"""Durable environment-profile refresh and Inventory cursor fencing."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.core.deploy_preflight.environment_profile import build_profile
from fdai.delivery import inventory_change_acceleration
from fdai.delivery.deploy_preflight.environment_profile_refresh import (
    EnvironmentProfileRefreshTask,
)
from fdai.delivery.inventory_delta import forward_inventory_delta
from fdai.shared.providers.inventory import InventoryBatch, ResourceRecord
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore

SCOPE = "00000000-0000-0000-0000-000000000000"
INITIAL = datetime(2026, 7, 7, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = INITIAL

    def __call__(self) -> datetime:
        return self.now


def _task(
    state: InMemoryStateStore,
    clock: _Clock,
    builder: AsyncMock | None = None,
    *,
    max_age: int = 10,
    lease: int = 30,
) -> EnvironmentProfileRefreshTask:
    if builder is None:
        builder = AsyncMock(
            side_effect=lambda scope, now: build_profile(
                scope=scope,
                rule_ids=["rule-b", "rule-a"],
                resource_type_counts={"compute.vm": 1},
                captured_at=now.isoformat(),
            )
        )
    return EnvironmentProfileRefreshTask(
        state_store=state,
        builder=builder,
        clock=clock,
        max_age_seconds=max_age,
        lease_seconds=lease,
    )


async def test_restart_and_expiry_refresh_from_durable_state() -> None:
    state = InMemoryStateStore()
    clock = _Clock()
    builder = AsyncMock(
        side_effect=lambda scope, now: build_profile(
            scope=scope,
            rule_ids=("rule-a",),
            resource_type_counts={"vm": 2},
            captured_at=now.isoformat(),
        )
    )
    first = _task(state, clock, builder)
    result = await first.run_once(SCOPE)
    assert result is not None and result.rule_ids == ("rule-a",)
    restarted = _task(state, clock, builder)
    assert await restarted.get_fresh(SCOPE) == result
    assert await restarted.run_once(SCOPE) == result
    builder.assert_awaited_once()

    clock.now += timedelta(seconds=11)
    assert await restarted.get_fresh(SCOPE) is None
    refreshed = await restarted.run_once(SCOPE)
    assert refreshed is not None and refreshed.captured_at == clock.now.isoformat()
    assert builder.await_count == 2
    assert await _task(state, clock, builder).get_fresh(SCOPE) == refreshed


async def test_delta_invalidation_is_durable_idempotent_and_scope_isolated() -> None:
    state = InMemoryStateStore()
    clock = _Clock()
    task = _task(state, clock)
    await task.run_once(SCOPE)
    other = await task.run_once("other-scope")
    assert other is not None
    assert await task.invalidate(SCOPE, "cursor-1")
    assert await _task(state, clock).get_fresh(SCOPE) is None
    assert await _task(state, clock).get_fresh("other-scope") == other
    refreshed = await task.run_once(SCOPE)
    assert refreshed is not None
    assert not await task.invalidate(SCOPE, "cursor-1")
    assert await task.get_fresh(SCOPE) == refreshed
    assert await task.invalidate(SCOPE, "cursor-2")
    assert await task.get_fresh(SCOPE) is None


async def test_invalidation_during_probe_fences_stale_result() -> None:
    state = InMemoryStateStore()
    clock = _Clock()
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed(scope: str, now: datetime):  # type: ignore[no-untyped-def]
        started.set()
        await release.wait()
        return build_profile(
            scope=scope, rule_ids=("old",), resource_type_counts={}, captured_at=now.isoformat()
        )

    task = _task(state, clock, AsyncMock(side_effect=delayed))
    pending = asyncio.create_task(task.run_once(SCOPE))
    await started.wait()
    assert await task.invalidate(SCOPE, "new-cursor")
    release.set()
    assert await pending is None
    assert await task.get_fresh(SCOPE) is None
    new = await _task(state, clock).run_once(SCOPE)
    assert new is not None and new.rule_ids == ("rule-a", "rule-b")


async def test_crashed_worker_lease_can_be_reclaimed_on_restart() -> None:
    state = InMemoryStateStore()
    clock = _Clock()
    started, stop = asyncio.Event(), asyncio.Event()

    async def never_finishes(scope: str, now: datetime):  # type: ignore[no-untyped-def]
        started.set()
        await stop.wait()
        return build_profile(
            scope=scope, rule_ids=("stale",), resource_type_counts={}, captured_at=now.isoformat()
        )

    original = _task(state, clock, AsyncMock(side_effect=never_finishes), lease=5)
    pending = asyncio.create_task(original.run_once(SCOPE))
    await started.wait()
    restarted = _task(state, clock, lease=5)
    assert await restarted.run_once(SCOPE) is None
    clock.now += timedelta(seconds=6)
    result = await restarted.run_once(SCOPE)
    assert result is not None
    stop.set()
    assert await pending is None
    assert await restarted.get_fresh(SCOPE) == result


async def test_failed_builder_releases_lease_without_publishing() -> None:
    state, clock = InMemoryStateStore(), _Clock()
    task = _task(state, clock, AsyncMock(side_effect=RuntimeError("probe failed")))
    with pytest.raises(RuntimeError, match="probe failed"):
        await task.run_once(SCOPE)
    assert await task.get_fresh(SCOPE) is None
    assert await _task(state, clock).run_once(SCOPE) is not None


async def test_future_or_mismatched_builder_output_never_publishes() -> None:
    state, clock = InMemoryStateStore(), _Clock()
    for scope, captured in (
        (SCOPE, (INITIAL + timedelta(seconds=1)).isoformat()),
        ("different-scope", INITIAL.isoformat()),
    ):
        builder = AsyncMock(
            return_value=build_profile(
                scope=scope, rule_ids=(), resource_type_counts={}, captured_at=captured
            )
        )
        with pytest.raises(ValueError, match="stale or mismatched"):
            await _task(state, clock, builder).run_once(SCOPE)
        assert await _task(state, clock).get_fresh(SCOPE) is None


class _Delta:
    def __init__(self, *, final: bool = True, status: str = "unchanged") -> None:
        self.final = final
        self.status = status

    async def delta(self, _cursor: str):  # type: ignore[no-untyped-def]
        yield InventoryBatch(
            resources=(
                ResourceRecord(
                    resource_id="resource:example/vm",
                    type="compute.vm",
                    props={"status": self.status},
                    last_seen=INITIAL.isoformat(),
                ),
            ),
            cursor="delta-cursor",
        )
        if self.final:
            yield InventoryBatch(final=True, cursor="delta-cursor")


async def test_inventory_delta_invalidates_before_cursor_commits() -> None:
    state, clock = InMemoryStateStore(), _Clock()
    task = _task(state, clock)
    await task.run_once(SCOPE)

    async def invalidate(scope: str, cursor: str) -> bool:
        assert await state.read_state(f"inventory_delta_cursor:{SCOPE}") is None
        return await task.invalidate(scope, cursor)

    assert (
        await forward_inventory_delta(
            inventory=_Delta(),
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope=SCOPE,
            properties_complete=False,
            profile_invalidator=invalidate,
        )
        == 1
    )
    assert await task.get_fresh(SCOPE) is None
    assert (await state.read_state(f"inventory_delta_cursor:{SCOPE}")) == {"cursor": "delta-cursor"}
    await task.run_once(SCOPE)
    await forward_inventory_delta(
        inventory=_Delta(),
        state_store=state,
        event_bus=InMemoryEventBus(),
        topic="events",
        scope=SCOPE,
        properties_complete=False,
        profile_invalidator=task.invalidate,
    )
    assert await task.get_fresh(SCOPE) is not None
    await forward_inventory_delta(
        inventory=_Delta(status="modified"),
        state_store=state,
        event_bus=InMemoryEventBus(),
        topic="events",
        scope=SCOPE,
        properties_complete=False,
        profile_invalidator=task.invalidate,
    )
    assert await task.get_fresh(SCOPE) is None


async def test_cursorless_final_delta_invalidates_with_content_digest() -> None:
    class CursorlessDelta:
        async def delta(self, _cursor: str):  # type: ignore[no-untyped-def]
            yield InventoryBatch(
                resources=(
                    ResourceRecord(
                        "resource:example/vm",
                        "compute.vm",
                        last_seen=INITIAL.isoformat(),
                    ),
                ),
                final=True,
            )

    state, clock = InMemoryStateStore(), _Clock()
    task = _task(state, clock)
    await task.run_once(SCOPE)
    assert (
        await forward_inventory_delta(
            inventory=CursorlessDelta(),
            state_store=state,
            event_bus=InMemoryEventBus(),
            topic="events",
            scope=SCOPE,
            properties_complete=False,
            profile_invalidator=task.invalidate,
        )
        == 1
    )
    assert await task.get_fresh(SCOPE) is None


async def test_partial_or_failed_delta_never_advances_cursor() -> None:
    for final in (False, True):
        state = InMemoryStateStore()
        callback = AsyncMock(side_effect=RuntimeError("write failed"))
        with pytest.raises(RuntimeError, match="final fence|write failed"):
            await forward_inventory_delta(
                inventory=_Delta(final=final),
                state_store=state,
                event_bus=InMemoryEventBus(),
                topic="events",
                scope=SCOPE,
                properties_complete=False,
                profile_invalidator=callback,
            )
        assert await state.read_state(f"inventory_delta_cursor:{SCOPE}") is None
        assert callback.await_count == int(final)


async def test_recovery_job_composes_durable_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, clock = InMemoryStateStore(), _Clock()
    await _task(state, clock).run_once(SCOPE)
    state.aclose = AsyncMock()  # type: ignore[attr-defined,method-assign]

    class Factory:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def build_fetch_fn(self) -> object:
            return object()

    class Lock:
        @asynccontextmanager
        async def acquire(self, _key: str):  # type: ignore[no-untyped-def]
            yield

    monkeypatch.setattr(inventory_change_acceleration, "PostgresStateStore", lambda **_kw: state)
    monkeypatch.setattr(inventory_change_acceleration, "AzureActivityLogFactory", Factory)
    monkeypatch.setattr(
        inventory_change_acceleration,
        "AzureResourceGraphInventory",
        lambda **_kw: _Delta(),
    )
    config = SimpleNamespace(
        dsn="postgresql://example.invalid/db",
        scopes=(SCOPE,),
        management_endpoint="https://example.invalid",
        management_audience="https://example.invalid",
    )
    count = await inventory_change_acceleration.forward_recovery_deltas(
        config=config,
        identity=object(),
        vocabulary=object(),
        http_client=object(),
        event_bus=InMemoryEventBus(),
        topic="events",
        scope_lock=Lock(),
    )
    assert count == 1
    assert await _task(state, clock).get_fresh(SCOPE) is None
    assert (await state.read_state(f"inventory_delta_cursor:{SCOPE}")) == {"cursor": "delta-cursor"}
