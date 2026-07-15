"""Tests for the chat-based creation commands (slides 15-16)."""

from __future__ import annotations

import pytest

from fdai.core.conversation.creation import (
    CreateIncidentCommand,
    CreateScheduledTaskCommand,
    CreationForbiddenError,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.incident.registry import IncidentRegistry
from fdai.core.incident.workflow import IncidentConfirmationError
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _contributor() -> Principal:
    return Principal(id="op@example.com", role=Role.CONTRIBUTOR)


def _reader() -> Principal:
    return Principal(id="viewer@example.com", role=Role.READER)


@pytest.mark.asyncio
async def test_create_incident_opens_record() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    command = CreateIncidentCommand(registry=registry)

    incident = await command.create(
        principal=_contributor(),
        correlation_keys=("aoai-1:rate_limit",),
        severity=IncidentSeverity.SEV2,
        confirmed=True,
    )

    assert incident.state is IncidentState.OPEN
    assert incident.severity is IncidentSeverity.SEV2


@pytest.mark.asyncio
async def test_create_incident_is_idempotent_by_correlation() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    command = CreateIncidentCommand(registry=registry)
    keys = ("mysql-1:db_cpu",)

    first = await command.create(
        principal=_contributor(),
        correlation_keys=keys,
        severity=IncidentSeverity.SEV3,
        confirmed=True,
    )
    second = await command.create(
        principal=_contributor(),
        correlation_keys=keys,
        severity=IncidentSeverity.SEV3,
        confirmed=True,
    )

    assert first.incident_id == second.incident_id


@pytest.mark.asyncio
async def test_create_incident_requires_contributor() -> None:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    command = CreateIncidentCommand(registry=registry)

    with pytest.raises(CreationForbiddenError):
        await command.create(
            principal=_reader(),
            correlation_keys=("k",),
            severity=IncidentSeverity.SEV3,
            confirmed=True,
        )


@pytest.mark.asyncio
async def test_create_incident_requires_explicit_confirmation() -> None:
    command = CreateIncidentCommand(
        registry=IncidentRegistry(state_store=InMemoryStateStore())
    )

    with pytest.raises(
        IncidentConfirmationError,
        match="explicit incident creation confirmation",
    ):
        await command.create(
            principal=_contributor(),
            correlation_keys=("resource:example-1",),
            severity=IncidentSeverity.SEV3,
        )


@pytest.mark.asyncio
async def test_create_scheduled_task_persists_to_shared_store() -> None:
    store = InMemoryScheduleStore()
    command = CreateScheduledTaskCommand(store=store)

    task = await command.create(
        principal=_contributor(),
        name="hourly appgw health",
        interval_seconds=3600.0,
        event_type="synthetic.monitor.appgw",
        resource_ref="appgw-1",
    )

    stored = await store.list_all()
    assert [t.task_id for t in stored] == [task.task_id]
    assert task.created_by == "op@example.com"
    assert task.enabled is True


@pytest.mark.asyncio
async def test_create_scheduled_task_requires_contributor() -> None:
    command = CreateScheduledTaskCommand(store=InMemoryScheduleStore())

    with pytest.raises(CreationForbiddenError):
        await command.create(
            principal=_reader(),
            name="x",
            interval_seconds=60.0,
            event_type="synthetic.monitor.x",
        )
