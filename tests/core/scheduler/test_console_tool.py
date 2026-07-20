"""RBAC-scoped scheduler console tools (P2-6)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from fdai.core.conversation.session import Principal, Role
from fdai.core.scheduler.console_tool import (
    CancelScheduleTool,
    CreateScheduleTool,
    ListSchedulesTool,
    RunScheduleNowTool,
    SetScheduleEnabledTool,
    UpdateScheduleTool,
)
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.service import SchedulerService
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.shared.providers.event_bus import PublishReceipt

_CONTRIB = Principal(id="oid-c", role=Role.CONTRIBUTOR, display_name="Dev")
_READER = Principal(id="oid-r", role=Role.READER, display_name="Viewer")


def _ids() -> Sequence[str]:
    return ("t-1", "t-2", "t-3")


class _SeqIds:
    def __init__(self) -> None:
        self._i = 0

    def __call__(self) -> str:
        self._i += 1
        return f"t-{self._i}"


@pytest.mark.asyncio
async def test_create_schedule_ok_for_contributor() -> None:
    store = InMemoryScheduleStore()
    tool = CreateScheduleTool(store=store, id_factory=_SeqIds())

    result = await tool.call(
        arguments={
            "name": "nightly cost check",
            "interval_seconds": 3600,
            "event_type": "synthetic.cost.probe",
            "resource_ref": "rg/sub-a",
        },
        principal=_CONTRIB,
    )

    assert result.status == "ok"
    assert result.data["task"]["task_id"] == "t-1"
    assert result.data["task"]["created_by"] == "oid-c"
    stored = await store.list_all()
    assert len(stored) == 1
    assert stored[0].created_by == "oid-c"


@pytest.mark.asyncio
async def test_create_schedule_denied_below_floor() -> None:
    store = InMemoryScheduleStore()
    tool = CreateScheduleTool(store=store, id_factory=_SeqIds())

    result = await tool.call(
        arguments={
            "name": "x",
            "interval_seconds": 3600,
            "event_type": "synthetic.x",
        },
        principal=_READER,
    )

    assert result.status == "error"
    assert "role >= contributor" in result.preview
    assert await store.list_all() == ()  # store never touched


@pytest.mark.asyncio
async def test_create_schedule_rejects_short_interval() -> None:
    store = InMemoryScheduleStore()
    tool = CreateScheduleTool(store=store, id_factory=_SeqIds())

    result = await tool.call(
        arguments={"name": "x", "interval_seconds": 5, "event_type": "e"},
        principal=_CONTRIB,
    )

    assert result.status == "error"
    assert "60" in result.preview
    assert await store.list_all() == ()


@pytest.mark.asyncio
async def test_create_schedule_requires_name_and_event_type() -> None:
    store = InMemoryScheduleStore()
    tool = CreateScheduleTool(store=store, id_factory=_SeqIds())

    result = await tool.call(
        arguments={"interval_seconds": 3600},
        principal=_CONTRIB,
    )
    assert result.status == "error"


@pytest.mark.asyncio
async def test_list_schedules_reader_ok() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        ScheduledTask(
            task_id="t-1",
            name="a",
            interval_seconds=3600,
            event_type="e",
            created_by="oid-c",
        )
    )
    tool = ListSchedulesTool(store=store)

    result = await tool.call(arguments={}, principal=_READER)

    assert result.status == "ok"
    assert len(result.data["tasks"]) == 1


@pytest.mark.asyncio
async def test_cancel_schedule_ok_and_not_found() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        ScheduledTask(
            task_id="t-1",
            name="a",
            interval_seconds=3600,
            event_type="e",
            created_by="oid-c",
        )
    )
    tool = CancelScheduleTool(store=store)

    ok = await tool.call(arguments={"task_id": "t-1"}, principal=_CONTRIB)
    assert ok.status == "ok"
    assert await store.list_all() == ()

    missing = await tool.call(arguments={"task_id": "nope"}, principal=_CONTRIB)
    assert missing.status == "error"


@pytest.mark.asyncio
async def test_cancel_schedule_denied_below_floor() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        ScheduledTask(
            task_id="t-1",
            name="a",
            interval_seconds=3600,
            event_type="e",
            created_by="oid-c",
        )
    )
    tool = CancelScheduleTool(store=store)

    result = await tool.call(arguments={"task_id": "t-1"}, principal=_READER)

    assert result.status == "error"
    assert len(await store.list_all()) == 1  # not cancelled


def test_tool_rbac_floors_and_side_effects() -> None:
    store = InMemoryScheduleStore()
    assert CreateScheduleTool(store=store).side_effect_class == "execute"
    assert CreateScheduleTool(store=store).rbac_floor is Role.CONTRIBUTOR
    assert ListSchedulesTool(store=store).side_effect_class == "read"
    assert ListSchedulesTool(store=store).rbac_floor is Role.READER
    assert CancelScheduleTool(store=store).rbac_floor is Role.CONTRIBUTOR


class _Bus:
    def __init__(self) -> None:
        self.count = 0

    async def publish(self, topic, key, payload):
        self.count += 1
        return PublishReceipt(topic=topic, partition=0, offset=self.count)

    def subscribe(self, topic, group_id):  # pragma: no cover - unused
        raise NotImplementedError

    async def dead_letter(self, topic, key, payload, reason):  # pragma: no cover
        raise NotImplementedError


async def test_pause_resume_edit_and_run_now() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        ScheduledTask(
            task_id="t-1",
            name="daily check",
            interval_seconds=3600,
            event_type="probe.health",
            created_by="oid-c",
        )
    )
    paused = await SetScheduleEnabledTool(store=store, enabled=False).call(
        arguments={"task_id": "t-1"}, principal=_CONTRIB
    )
    assert paused.data["task"]["enabled"] is False
    resumed = await SetScheduleEnabledTool(store=store, enabled=True).call(
        arguments={"task_id": "t-1"}, principal=_CONTRIB
    )
    assert resumed.data["task"]["enabled"] is True
    edited = await UpdateScheduleTool(store=store).call(
        arguments={"task_id": "t-1", "name": "hourly health", "interval_seconds": 1800},
        principal=_CONTRIB,
    )
    assert edited.data["task"]["name"] == "hourly health"
    bus = _Bus()
    ran = await RunScheduleNowTool(scheduler=SchedulerService(store=store, event_bus=bus)).call(
        arguments={"task_id": "t-1", "idempotency_key": "request-1"},
        principal=_CONTRIB,
    )
    assert ran.status == "ok"
    assert ran.data["fired"] == 1
