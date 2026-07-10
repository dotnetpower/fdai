"""Tests for the scheduled-task scheduler."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.service import SchedulerService, compute_due
from fdai.core.scheduler.store import (
    InMemoryScheduleStore,
    ScheduleNotFoundError,
)
from fdai.shared.providers.event_bus import PublishReceipt

_NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


class _RecordingBus:
    """Minimal recording EventBus for assertions; optionally fails a key."""

    def __init__(self, fail_keys: set[str] | None = None) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []
        self._fail_keys = fail_keys or set()

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        if key in self._fail_keys:
            raise RuntimeError("broker down")
        self.published.append((topic, key, dict(payload)))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))

    def subscribe(self, topic: str, group_id: str):  # pragma: no cover - unused
        raise NotImplementedError

    async def dead_letter(self, topic, key, payload, reason) -> None:  # pragma: no cover
        raise NotImplementedError


def _task(**overrides: object) -> ScheduledTask:
    base: dict[str, object] = dict(
        task_id="t1",
        name="disk check",
        interval_seconds=300,
        event_type="probe.disk",
        created_by="00000000-0000-0000-0000-000000000009",
    )
    base.update(overrides)
    return ScheduledTask(**base)  # type: ignore[arg-type]


# --- compute_due (pure) -----------------------------------------------------


def test_never_run_task_is_due() -> None:
    assert compute_due([_task()], now=_NOW) == [_task()]


def test_disabled_task_not_due() -> None:
    assert compute_due([_task(enabled=False)], now=_NOW) == []


def test_start_at_in_future_not_due() -> None:
    task = _task(start_at=_NOW + timedelta(minutes=1))
    assert compute_due([task], now=_NOW) == []


def test_recently_run_task_not_due_until_interval_elapses() -> None:
    task = _task(last_run=_NOW - timedelta(seconds=100))  # interval 300
    assert compute_due([task], now=_NOW) == []
    ready = _task(last_run=_NOW - timedelta(seconds=300))
    assert compute_due([ready], now=_NOW) == [ready]


def test_model_rejects_bad_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        _task(interval_seconds=0)


def test_model_rejects_empty_task_id_and_creator() -> None:
    # A task is never anonymous and never id-less (audit + RBAC scoping).
    with pytest.raises(ValueError, match="task_id"):
        _task(task_id="")
    with pytest.raises(ValueError, match="created_by"):
        _task(created_by="")


# --- store ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_crud_and_mark_run() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task())
    assert len(await store.list_all()) == 1
    with pytest.raises(ValueError, match="duplicate"):
        await store.create(_task())
    updated = await store.mark_run("t1", _NOW)
    assert updated.last_run == _NOW
    await store.cancel("t1")
    with pytest.raises(ScheduleNotFoundError):
        await store.get("t1")


# --- service ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_fires_due_task_and_marks_run() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(resource_ref="vm-a"))
    bus = _RecordingBus()
    svc = SchedulerService(store=store, event_bus=bus)

    report = await svc.run_once(now=_NOW)
    assert report.fired == 1
    topic, key, payload = bus.published[0]
    assert key == "vm-a"
    assert payload["event_type"] == "probe.disk"
    assert payload["payload"]["scheduled_task"]["task_id"] == "t1"

    # Second tick in the same interval bucket: task already ran -> not due.
    report2 = await svc.run_once(now=_NOW + timedelta(seconds=1))
    assert report2.fired == 0


@pytest.mark.asyncio
async def test_run_once_publish_error_does_not_mark_run() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(task_id="t1", resource_ref="vm-a"))
    bus = _RecordingBus(fail_keys={"vm-a"})
    svc = SchedulerService(store=store, event_bus=bus)

    report = await svc.run_once(now=_NOW)
    assert report.fired == 0
    assert report.publish_errors and report.publish_errors[0][0] == "t1"
    # last_run stayed None so the task retries next tick.
    assert (await store.get("t1")).last_run is None


@pytest.mark.asyncio
async def test_run_once_idempotency_key_is_stable_per_bucket() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(interval_seconds=300))
    bus = _RecordingBus()
    svc = SchedulerService(store=store, event_bus=bus)
    await svc.run_once(now=_NOW)
    key = bus.published[0][2]["idempotency_key"]
    bucket = int(_NOW.timestamp() // 300)
    assert key == f"schedule:t1:{bucket}"
