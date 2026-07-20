"""Tests for the scheduled-task scheduler."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from fdai.core.scheduler.models import ScheduledTask, ScheduleKind
from fdai.core.scheduler.run_ledger import (
    InMemoryScheduleRunLedger,
    ScheduleDispatchRun,
    ScheduleDispatchStatus,
)
from fdai.core.scheduler.service import SchedulerService, compute_due
from fdai.core.scheduler.store import (
    InMemoryScheduleStore,
    ScheduleNotFoundError,
)
from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.telemetry import InMemoryRoutingTransitionSink

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


def test_cron_task_fires_once_in_matching_minute() -> None:
    task = _task(cron_expression="0 12 * * *")
    assert compute_due([task], now=_NOW) == [task]
    same_minute = _task(cron_expression="0 12 * * *", last_run=_NOW)
    assert compute_due([same_minute], now=_NOW + timedelta(seconds=30)) == []
    assert compute_due([task], now=_NOW + timedelta(minutes=1)) == []


def test_one_shot_fires_once_at_or_after_start() -> None:
    task = _task(
        schedule_kind=ScheduleKind.ONE_SHOT,
        start_at=_NOW,
    )
    assert compute_due([task], now=_NOW - timedelta(seconds=1)) == []
    assert compute_due([task], now=_NOW) == [task]
    assert compute_due([task.with_last_run(_NOW)], now=_NOW + timedelta(days=1)) == []


def test_cron_matches_in_declared_iana_timezone() -> None:
    # 12:00 UTC is 21:00 Asia/Seoul.
    task = _task(
        schedule_kind=ScheduleKind.CRON,
        cron_expression="0 21 * * *",
        timezone="Asia/Seoul",
    )
    assert compute_due([task], now=_NOW) == [task]


async def test_event_exit_repeats_until_matching_event_disables_it() -> None:
    store = InMemoryScheduleStore()
    task = _task(
        schedule_kind=ScheduleKind.EVENT_EXIT,
        exit_event_type="deployment.completed",
    )
    await store.create(task)
    assert compute_due([task], now=_NOW) == [task]

    assert await store.mark_exit_event("other.event", _NOW) == 0
    assert await store.mark_exit_event("deployment.completed", _NOW) == 1
    exited = await store.get(task.task_id)
    assert exited.enabled is False
    assert exited.exit_observed_at == _NOW
    assert compute_due([exited], now=_NOW + timedelta(hours=1)) == []


async def test_scheduler_observes_normalized_exit_event() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        _task(
            schedule_kind=ScheduleKind.EVENT_EXIT,
            exit_event_type="deployment.completed",
        )
    )
    service = SchedulerService(store=store, event_bus=_RecordingBus())
    event = Event(
        schema_version="1.0.0",
        event_id=UUID(int=1),
        idempotency_key="event-1",
        source="test",
        event_type="deployment.completed",
        payload={},
        detected_at=_NOW,
        ingested_at=_NOW,
        mode=Mode.SHADOW,
    )

    assert await service.observe_event(event) == 1
    assert (await store.get("t1")).enabled is False


def test_model_rejects_invalid_or_non_five_field_cron() -> None:
    with pytest.raises(ValueError, match="cron_expression"):
        _task(cron_expression="not a cron")
    with pytest.raises(ValueError, match="cron_expression"):
        _task(cron_expression="0 12 * * * *")


def test_model_rejects_bad_interval() -> None:
    with pytest.raises(ValueError, match="interval_seconds"):
        _task(interval_seconds=0)


def test_model_rejects_invalid_schedule_specific_fields() -> None:
    with pytest.raises(ValueError, match="one-shot"):
        _task(schedule_kind=ScheduleKind.ONE_SHOT)
    with pytest.raises(ValueError, match="exit_event_type"):
        _task(schedule_kind=ScheduleKind.EVENT_EXIT)
    with pytest.raises(ValueError, match="IANA"):
        _task(timezone="Not/AZone")


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
    assert payload["incident_correlation"] == "none"
    assert payload["payload"]["scheduled_task"]["task_id"] == "t1"
    isolation = payload["payload"]["scheduled_task"]["isolation"]
    assert isolation["profile_id"] == "scheduled.default-deny"
    assert isolation["allowed_tool_ids"] == []

    # Second tick in the same interval bucket: task already ran -> not due.
    report2 = await svc.run_once(now=_NOW + timedelta(seconds=1))
    assert report2.fired == 0


async def test_scheduler_emits_stable_dispatch_transition() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task())
    transitions = InMemoryRoutingTransitionSink()
    service = SchedulerService(
        store=store,
        event_bus=_RecordingBus(),
        transition_sink=transitions,
    )

    await service.run_once(now=_NOW)

    assert transitions.transitions[0].domain == "scheduler"
    assert transitions.transitions[0].attributes["schedule_kind"] == "interval"


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
async def test_published_ledger_suppresses_redelivery_when_mark_run_was_lost() -> None:
    class _MarkRunFails(InMemoryScheduleStore):
        async def mark_run(self, task_id: str, at: datetime) -> ScheduledTask:
            raise RuntimeError("state update unavailable")

    store = _MarkRunFails()
    await store.create(_task(resource_ref="vm-a"))
    bus = _RecordingBus()
    ledger = InMemoryScheduleRunLedger()
    service = SchedulerService(store=store, event_bus=bus, run_ledger=ledger)

    with pytest.raises(RuntimeError, match="state update"):
        await service.run_once(now=_NOW)
    second = await service.run_once(now=_NOW)

    assert len(bus.published) == 1
    assert second.duplicates_suppressed == 1
    runs = await ledger.list_for_task("t1")
    assert runs[0].status is ScheduleDispatchStatus.PUBLISHED


@pytest.mark.asyncio
async def test_failed_and_lost_dispatches_can_be_reclaimed() -> None:
    ledger = InMemoryScheduleRunLedger()
    run = ScheduleDispatchRun(
        run_id="schedule:t1:1",
        task_id="t1",
        scheduled_for=_NOW,
        claimed_at=_NOW,
    )
    assert await ledger.claim(run) is True
    await ledger.complete(
        run.run_id,
        status=ScheduleDispatchStatus.FAILED,
        at=_NOW,
        error_kind="RuntimeError",
    )
    assert await ledger.claim(run) is True
    reconciled = await ledger.reconcile_stale(
        before=_NOW,
        at=_NOW + timedelta(minutes=10),
    )
    assert reconciled[0].status is ScheduleDispatchStatus.LOST
    assert await ledger.claim(run) is True
    assert (await ledger.list_for_task("t1"))[0].attempt == 3


@pytest.mark.asyncio
async def test_run_once_idempotency_key_is_stable_per_bucket() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(interval_seconds=300))
    bus = _RecordingBus()
    svc = SchedulerService(store=store, event_bus=bus)
    await svc.run_once(now=_NOW)
    key = bus.published[0][2]["idempotency_key"]
    bucket = int(_NOW.timestamp() // 300)
    assert key == f"schedule:t1:interval:{bucket}"


@pytest.mark.asyncio
async def test_cron_run_uses_minute_idempotency_bucket() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(cron_expression="0 12 * * *"))
    bus = _RecordingBus()
    await SchedulerService(store=store, event_bus=bus).run_once(now=_NOW)

    assert bus.published[0][2]["idempotency_key"] == (
        f"schedule:t1:cron:{int(_NOW.timestamp() // 60)}"
    )


async def test_one_shot_idempotency_uses_scheduled_timestamp() -> None:
    store = InMemoryScheduleStore()
    await store.create(_task(schedule_kind=ScheduleKind.ONE_SHOT, start_at=_NOW))
    bus = _RecordingBus()
    await SchedulerService(store=store, event_bus=bus).run_once(now=_NOW + timedelta(seconds=5))

    assert bus.published[0][2]["idempotency_key"] == (f"schedule:t1:at:{int(_NOW.timestamp())}")


@pytest.mark.asyncio
async def test_scheduled_action_proposal_enters_typed_operator_pipeline() -> None:
    store = InMemoryScheduleStore()
    task = _task(
        cron_expression="0 12 * * *",
        resource_ref="resource:compute/vm/gpu-worker",
        event_type="workflow.schedule.scheduled-gpu-python-task",
        event_payload={
            "action_proposal": {
                "initiator_principal": "operator-1",
                "action_type": "tool.run-python-on-vm",
                "params": {
                    "artifact_ref": "python-task:gpu.health@1.0.0#" + "a" * 64,
                    "target_resource_ref": "resource:compute/vm/gpu-worker",
                    "reason": "Scheduled GPU health task invocation.",
                },
            }
        },
    )
    await store.create(task)
    bus = _RecordingBus()

    await SchedulerService(store=store, event_bus=bus).run_once(now=_NOW)

    payload = bus.published[0][2]
    assert payload["event_type"] == "operator_request"
    assert payload["operator_initiated"] is True
    assert payload["action_type"] == "tool.run-python-on-vm"
    assert payload["params"]["artifact_ref"].startswith("python-task:gpu.health")
