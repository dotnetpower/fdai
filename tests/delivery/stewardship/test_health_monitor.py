from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.stewardship import load_stewardship_from_yaml
from fdai.delivery.stewardship import StewardshipHealthMonitor
from fdai.shared.providers.testing import InMemoryStateStore

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agent-stewardship.yaml"


class ToggleDirectory:
    def __init__(self, *, active: bool) -> None:
        self.active = active

    async def is_active(self, oid: str) -> bool:
        return self.active


async def test_monitor_audits_only_health_transitions() -> None:
    directory = ToggleDirectory(active=False)
    store = InMemoryStateStore()
    observed_at = iter(
        (
            datetime(2026, 8, 5, 0, 0, tzinfo=UTC),
            datetime(2026, 8, 5, 1, 0, tzinfo=UTC),
            datetime(2026, 8, 5, 2, 0, tzinfo=UTC),
        )
    )
    monitor = StewardshipHealthMonitor(
        stewardship_map=load_stewardship_from_yaml(_CONFIG),
        directory=directory,
        state_store=store,
        clock=lambda: next(observed_at),
    )

    assert await monitor.run_once() is True
    first_transition = await store.read_state("stewardship_health:current")
    first_freshness = await store.read_state("stewardship_health:last_success")
    assert await monitor.run_once() is False
    unchanged_transition = await store.read_state("stewardship_health:current")
    refreshed_freshness = await store.read_state("stewardship_health:last_success")
    assert first_transition == unchanged_transition
    assert first_freshness is not None
    assert refreshed_freshness is not None
    assert first_freshness["checked_at"] == "2026-08-05T00:00:00+00:00"
    assert refreshed_freshness["checked_at"] == "2026-08-05T01:00:00+00:00"
    assert refreshed_freshness["revision"] == 1
    assert len(store.audit_entries) == 1

    directory.active = True
    assert await monitor.run_once() is True
    transitioned_freshness = await store.read_state("stewardship_health:last_success")
    assert transitioned_freshness is not None
    assert transitioned_freshness["checked_at"] == "2026-08-05T02:00:00+00:00"
    assert transitioned_freshness["revision"] == 2
    entries = store.audit_entries
    assert len(entries) == 2
    assert entries[-1]["entry"]["decision"] == "clean"


async def test_monitor_rejects_sub_minute_interval() -> None:
    store = InMemoryStateStore()
    try:
        StewardshipHealthMonitor(
            stewardship_map=load_stewardship_from_yaml(_CONFIG),
            directory=ToggleDirectory(active=True),
            state_store=store,
            interval_seconds=59,
        )
    except ValueError as exc:
        assert "at least 60 seconds" in str(exc)
    else:
        raise AssertionError("sub-minute interval was accepted")


async def test_monitor_start_does_not_wait_for_initial_directory_sweep() -> None:
    class BlockingDirectory:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def is_active(self, oid: str) -> bool:
            self.entered.set()
            await self.release.wait()
            return True

    directory = BlockingDirectory()
    monitor = StewardshipHealthMonitor(
        stewardship_map=load_stewardship_from_yaml(_CONFIG),
        directory=directory,
        state_store=InMemoryStateStore(),
    )

    await monitor.start()
    await asyncio.wait_for(directory.entered.wait(), timeout=1)
    directory.release.set()
    await monitor.stop()
