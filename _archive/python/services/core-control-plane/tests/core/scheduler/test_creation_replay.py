"""Creation replay preserves execution state and exact declared JSON intent."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fdai.core.conversation.creation import CreateScheduledTaskCommand, CreationForbiddenError
from fdai.core.conversation.session import Principal, Role
from fdai.core.scheduler.models import ScheduledRunIsolationProfile, ScheduledTask, ScheduleKind
from fdai.core.scheduler.store import (
    InMemoryScheduleStore,
    ScheduleAlreadyExistsError,
    ScheduleNotFoundError,
)

_NOW = datetime(2026, 10, 19, tzinfo=UTC)
_ACTOR = Principal(id="operator-1", role=Role.CONTRIBUTOR)


async def _create(
    command: CreateScheduledTaskCommand,
    *,
    payload: dict[str, object] | None = None,
    principal: Principal = _ACTOR,
):
    return await command.create(
        principal=principal,
        name="Daily bounded observation",
        interval_seconds=86400,
        event_type="monitoring.sample",
        task_id="daily-observation",
        event_payload=payload,
    )


@pytest.mark.parametrize("ran,normalized_kind", [(True, False), (False, True), (True, True)])
async def test_replay_preserves_run_state_and_accepts_effective_kind(
    ran: bool, normalized_kind: bool
) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command)
    if normalized_kind:
        task = await store.update(replace(task, schedule_kind=ScheduleKind.INTERVAL))
    if ran:
        task = await store.mark_run(task.task_id, _NOW)

    replayed = await _create(command)

    assert replayed == task
    assert replayed.last_run == (_NOW if ran else None)
    assert len(await store.list_all()) == 1


@pytest.mark.parametrize("first,second", [(True, 1), (1, True), (False, 0), (0, False)])
async def test_replay_does_not_equate_json_boolean_and_number(
    first: object, second: object
) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command, payload={"nested": [{"value": first}]})

    with pytest.raises(ValueError, match="different content"):
        await _create(command, payload={"nested": [{"value": second}]})

    assert await store.get(task.task_id) == task


async def test_payload_snapshot_is_detached_from_the_creation_caller() -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    nested = [{"value": 1}]
    task = await _create(command, payload={"nested": nested})
    nested[0]["value"] = 2

    assert task.event_payload == {"nested": [{"value": 1}]}
    assert (await store.get(task.task_id)).event_payload == {"nested": [{"value": 1}]}


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), b"not-json", {1, 2}])
async def test_invalid_payload_never_enters_schedule_state(invalid: object) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)

    with pytest.raises(ValueError):
        await _create(command, payload={"value": invalid})

    assert await store.list_all() == ()


async def test_replay_never_resumes_a_paused_task_or_changes_its_creator() -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command)
    paused = await store.update(replace(task, enabled=False))
    with pytest.raises(ValueError, match="different content"):
        await _create(command)
    with pytest.raises(ValueError, match="different content"):
        await _create(command, principal=Principal(id="operator-2", role=Role.CONTRIBUTOR))
    assert await store.get(task.task_id) == paused


async def test_reader_cannot_replay_an_existing_creation() -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command)
    with pytest.raises(CreationForbiddenError):
        await _create(command, principal=Principal(id=_ACTOR.id, role=Role.READER))
    assert await store.get(task.task_id) == task


@pytest.mark.parametrize("conflict", [False, True])
async def test_concurrent_creation_converges_or_rejects_definition_drift(conflict: bool) -> None:
    class BarrierStore(InMemoryScheduleStore):
        def __init__(self) -> None:
            super().__init__()
            self.misses = 0
            self.ready = asyncio.Event()

        async def get(self, task_id: str):
            try:
                return await super().get(task_id)
            except ScheduleNotFoundError:
                if self.misses < 2:
                    self.misses += 1
                    if self.misses == 2:
                        self.ready.set()
                    await self.ready.wait()
                raise

    store = BarrierStore()
    command = CreateScheduledTaskCommand(store=store)
    first, second = await asyncio.gather(
        _create(command, payload={"value": True}),
        _create(command, payload={"value": 1 if conflict else True}),
        return_exceptions=True,
    )
    if conflict:
        errors = [item for item in (first, second) if isinstance(item, ValueError)]
        assert len(errors) == 1 and "different content" in str(errors[0])
        assert sum(isinstance(item, ScheduledTask) for item in (first, second)) == 1
    else:
        assert isinstance(first, ScheduledTask) and first == second
    assert len(await store.list_all()) == 1


@pytest.mark.parametrize(
    "first,second", [(1, 1.0), (-0.0, 0.0), ({"b": 2, "a": 1}, {"a": 1, "b": 2})]
)
async def test_replay_accepts_equivalent_stored_json_numbers_and_key_order(
    first: object, second: object
) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command, payload={"value": first})
    assert await _create(command, payload={"value": second}) == task


async def test_unrelated_backend_value_error_is_not_a_successful_replay() -> None:
    class RejectedStore(InMemoryScheduleStore):
        async def create(self, task):
            raise ValueError("backend validation rejected creation")

    store = RejectedStore()
    with pytest.raises(ValueError, match="backend validation rejected"):
        await _create(CreateScheduledTaskCommand(store=store))
    assert await store.list_all() == ()


async def test_explicit_empty_id_does_not_create_an_unrequested_random_task() -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    with pytest.raises(ValueError, match="task_id MUST be non-empty"):
        await command.create(
            principal=_ACTOR,
            task_id="",
            name="daily",
            interval_seconds=86400,
            event_type="monitoring.sample",
        )
    assert await store.list_all() == ()


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Different observation"},
        {"interval_seconds": 3600},
        {"event_type": "monitoring.different"},
        {"resource_ref": "resource-other"},
        {"cron_expression": "0 3 * * *"},
        {"timezone": "Asia/Seoul"},
        {"isolation_profile": ScheduledRunIsolationProfile(profile_id="different-profile")},
    ],
)
async def test_replay_never_overwrites_a_changed_declared_definition(
    change: dict[str, object],
) -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    task = await _create(command)
    arguments = {
        "principal": _ACTOR,
        "task_id": task.task_id,
        "name": task.name,
        "interval_seconds": task.interval_seconds,
        "event_type": task.event_type,
        **change,
    }
    with pytest.raises(ValueError, match="different content"):
        await command.create(**arguments)
    assert await store.get(task.task_id) == task


async def test_generated_id_collision_never_reuses_an_unrequested_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "fdai.core.conversation.creation.uuid4", lambda: SimpleNamespace(hex="same-generated-id")
    )
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)
    arguments = {
        "principal": _ACTOR,
        "name": "new observation",
        "interval_seconds": 86400,
        "event_type": "monitoring.sample",
    }
    await command.create(**arguments)
    with pytest.raises(ScheduleAlreadyExistsError):
        await command.create(**arguments)
    assert len(await store.list_all()) == 1
