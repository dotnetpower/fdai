"""Non-finite schedule intervals cannot enter the store or poison a due-task cycle."""

from typing import Any

import pytest
from fdai.core.conversation.creation import CreateScheduledTaskCommand
from fdai.core.scheduler.console_tool import (
    CreateScheduleTool,
    RunScheduleNowTool,
    SetScheduleEnabledTool,
    UpdateScheduleTool,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile, ScheduledTask, ScheduleKind
from fdai.core.scheduler.service import SchedulerService
from fdai.core.scheduler.store import InMemoryScheduleStore

from tests.core.scheduler.test_console_tool import _CONTRIB, _READER
from tests.core.scheduler.test_scheduler import _NOW, _RecordingBus


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, False, 10**400],
    ids=["nan", "infinity", "negative-infinity", "true", "false", "overflow"],
)
def test_schedule_model_rejects_non_real_or_non_finite_intervals(value: Any) -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        ScheduledTask(
            task_id="finite-interval",
            name="health check",
            interval_seconds=value,
            event_type="probe.health",
            created_by="operator",
        )


@pytest.mark.parametrize("value", [None, "60"], ids=["missing", "string"])
def test_raw_model_requires_a_numeric_interval(value: Any) -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        ScheduledTask(
            task_id="invalid-model",
            name="health",
            interval_seconds=value,
            event_type="probe.health",
            created_by="operator",
        )


@pytest.mark.parametrize(
    "values",
    [
        {"profile_id": ""},
        {"max_session_seconds": 0},
        {"max_context_chars": 0},
        {"max_tool_calls": -1},
        {"allowed_tool_ids": frozenset({"not-admitted"})},
        {"max_tool_calls": 1},
    ],
)
def test_invalid_isolation_cannot_accompany_an_accepted_interval(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="scheduled isolation"):
        ScheduledRunIsolationProfile(**values)


@pytest.mark.parametrize(
    "values",
    [
        {"schedule_kind": ScheduleKind.CRON},
        {"schedule_kind": ScheduleKind.INTERVAL, "cron_expression": "0 * * * *"},
        {"schedule_kind": ScheduleKind.ONE_SHOT},
        {"schedule_kind": ScheduleKind.EVENT_EXIT},
    ],
)
def test_invalid_schedule_kind_fields_are_not_hidden_by_a_valid_interval(
    values: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        ScheduledTask(
            task_id="invalid-kind",
            name="health",
            interval_seconds=3600,
            event_type="probe.health",
            created_by="operator",
            **values,
        )


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, 10**400],
    ids=["nan", "infinity", "negative-infinity", "boolean", "overflow"],
)
async def test_production_creation_command_does_not_persist_an_invalid_interval(value: Any) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    with pytest.raises(ValueError, match="interval_seconds"):
        await command.create(
            principal=_CONTRIB,
            name="health",
            interval_seconds=value,
            event_type="probe.health",
        )
    assert await store.list_all() == ()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "value",
    ["nan", "inf", "-Infinity", float("nan"), float("inf"), 10**400],
    ids=["nan-string", "infinity-string", "negative-infinity", "nan", "infinity", "overflow"],
)
async def test_console_rejects_invalid_interval_without_creating_or_replacing_a_task(
    operation: str, value: Any
) -> None:
    store = InMemoryScheduleStore()
    original = ScheduledTask(
        task_id="finite-interval",
        name="health check",
        interval_seconds=3600,
        event_type="probe.health",
        created_by=_CONTRIB.id,
    )
    tool: CreateScheduleTool | UpdateScheduleTool
    arguments: dict[str, Any]
    if operation == "update":
        await store.create(original)
        tool = UpdateScheduleTool(store=store)
        arguments = {"task_id": original.task_id, "interval_seconds": value}
    else:
        tool = CreateScheduleTool(store=store, id_factory=lambda: original.task_id)
        arguments = {
            "name": original.name,
            "event_type": original.event_type,
            "interval_seconds": value,
        }
    result = await tool.call(arguments=arguments, principal=_CONTRIB)
    assert result.status == "error"
    assert await store.list_all() == ((original,) if operation == "update" else ())


@pytest.mark.parametrize("kind", ["update", "pause", "run"])
@pytest.mark.parametrize("failure", ["role", "missing-id", "missing-task"])
async def test_schedule_lifecycle_errors_keep_the_store_unchanged(kind: str, failure: str) -> None:
    store = InMemoryScheduleStore()
    tool: UpdateScheduleTool | SetScheduleEnabledTool | RunScheduleNowTool
    if kind == "update":
        tool = UpdateScheduleTool(store=store)
    elif kind == "pause":
        tool = SetScheduleEnabledTool(store=store, enabled=False)
    else:
        tool = RunScheduleNowTool(
            scheduler=SchedulerService(store=store, event_bus=_RecordingBus())
        )
    result = await tool.call(
        arguments=(
            {}
            if failure == "missing-id"
            else {"task_id": "missing-task", "idempotency_key": "invalid-target"}
        ),
        principal=_READER if failure == "role" else _CONTRIB,
    )
    assert result.status == "error"
    assert await store.list_all() == ()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize(
    "value,accepted",
    [(59.999999, False), (60, True), (60.000001, True), ("300", True)],
)
async def test_console_preserves_exact_minimum_and_supported_numeric_conversion(
    operation: str, value: Any, accepted: bool
) -> None:
    store = InMemoryScheduleStore()
    tool: CreateScheduleTool | UpdateScheduleTool
    if operation == "update":
        await store.create(ScheduledTask("boundary", "health", 3600, "probe.health", _CONTRIB.id))
        tool = UpdateScheduleTool(store=store)
        arguments = {"task_id": "boundary", "interval_seconds": value}
    else:
        tool = CreateScheduleTool(store=store, id_factory=lambda: "boundary")
        arguments = {"name": "health", "event_type": "probe.health", "interval_seconds": value}
    result = await tool.call(arguments=arguments, principal=_CONTRIB)
    assert (result.status == "ok") is accepted
    if accepted:
        assert (await store.get("boundary")).interval_seconds == float(value)
    elif operation == "update":
        assert (await store.get("boundary")).interval_seconds == 3600
    else:
        assert await store.list_all() == ()


async def test_invalid_update_cannot_poison_the_next_real_scheduler_pass() -> None:
    store = InMemoryScheduleStore()
    await store.create(ScheduledTask("healthy-task", "health", 3600, "probe.health", _CONTRIB.id))
    result = await UpdateScheduleTool(store=store).call(
        arguments={"task_id": "healthy-task", "interval_seconds": "nan"},
        principal=_CONTRIB,
    )
    bus = _RecordingBus()
    report = await SchedulerService(store=store, event_bus=bus).run_once(now=_NOW)
    assert result.status == "error"
    assert report.fired == 1 and report.publish_errors == ()
    assert len(bus.published) == 1
