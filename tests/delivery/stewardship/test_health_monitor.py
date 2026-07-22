from __future__ import annotations

import asyncio
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
    monitor = StewardshipHealthMonitor(
        stewardship_map=load_stewardship_from_yaml(_CONFIG),
        directory=directory,
        state_store=store,
    )

    assert await monitor.run_once() is True
    assert await monitor.run_once() is False
    assert len(store.audit_entries) == 1

    directory.active = True
    assert await monitor.run_once() is True
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
