"""Process snapshot and transition journal invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRevisionConflictError,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.testing import InMemoryProcessRuntimeStore

_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
        process_id="process-1",
        workflow_ref="architecture-review",
        workflow_version="1.0.0",
        status=ProcessStatus.PENDING,
        current_step="",
        target_resource_id="scope-1",
        started_at=_NOW,
        updated_at=_NOW,
        correlation_id="corr-1",
    )


def _event(
    kind: ProcessEventKind,
    key: str,
    *,
    at: datetime = _NOW,
    step_id: str | None = None,
) -> ProcessEvent:
    return ProcessEvent(
        event_id=f"event-{key}",
        process_id="process-1",
        kind=kind,
        idempotency_key=key,
        recorded_at=at,
        correlation_id="corr-1",
        step_id=step_id,
    )


async def test_create_is_idempotent() -> None:
    store = InMemoryProcessRuntimeStore()
    created, first = await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    replayed, second = await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    assert first is True
    assert second is False
    assert created == replayed
    assert created.revision == 1
    assert len(await store.events("process-1")) == 1


async def test_transition_is_atomic_and_idempotent() -> None:
    store = InMemoryProcessRuntimeStore()
    current, _ = await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    event = _event(
        ProcessEventKind.STEP_STARTED,
        "step:start",
        at=_NOW + timedelta(seconds=1),
        step_id="collect-evidence",
    )
    running = await store.transition(
        process_id="process-1",
        expected_revision=current.revision,
        status=ProcessStatus.RUNNING,
        current_step="collect-evidence",
        event=event,
    )
    replayed = await store.transition(
        process_id="process-1",
        expected_revision=current.revision,
        status=ProcessStatus.RUNNING,
        current_step="collect-evidence",
        event=event,
    )
    assert running == replayed
    assert running.revision == 2
    assert [item.kind for item in await store.events("process-1")] == [
        ProcessEventKind.PROCESS_CREATED,
        ProcessEventKind.STEP_STARTED,
    ]


async def test_revision_conflict_fails_closed() -> None:
    store = InMemoryProcessRuntimeStore()
    await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    with pytest.raises(ProcessRevisionConflictError, match="revision mismatch"):
        await store.transition(
            process_id="process-1",
            expected_revision=0,
            status=ProcessStatus.RUNNING,
            current_step="collect-evidence",
            event=_event(ProcessEventKind.STEP_STARTED, "step:start"),
        )


def test_terminal_status_vocabulary() -> None:
    assert ProcessStatus.SUCCEEDED.terminal is True
    assert ProcessStatus.COMPENSATED.terminal is True
    assert ProcessStatus.WAITING.terminal is False


async def test_list_filters_and_orders_snapshots() -> None:
    store = InMemoryProcessRuntimeStore()
    first, _ = await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    await store.transition(
        process_id=first.process_id,
        expected_revision=first.revision,
        status=ProcessStatus.WAITING,
        current_step="evidence",
        event=_event(
            ProcessEventKind.STEP_WAITING,
            "wait",
            at=_NOW + timedelta(seconds=1),
        ),
    )
    selected = await store.list(
        workflow_ref="architecture-review",
        status=ProcessStatus.WAITING,
    )
    assert [item.process_id for item in selected] == ["process-1"]


async def test_append_event_is_idempotent_without_advancing_snapshot() -> None:
    store = InMemoryProcessRuntimeStore()
    snapshot, _ = await store.create(
        snapshot=_snapshot(),
        event=_event(ProcessEventKind.PROCESS_CREATED, "create"),
    )
    child = ProcessEvent(
        event_id="branch-started",
        process_id=snapshot.process_id,
        kind=ProcessEventKind.PARALLEL_BRANCH_STARTED,
        idempotency_key="branch:security:started",
        recorded_at=_NOW,
        correlation_id=snapshot.correlation_id,
        step_id="domain_reviews",
        payload={"branch": "security"},
    )

    assert await store.append_event(child) is True
    assert await store.append_event(child) is False
    assert await store.get(snapshot.process_id) == snapshot
    assert (await store.events(snapshot.process_id))[-1].kind is (
        ProcessEventKind.PARALLEL_BRANCH_STARTED
    )
