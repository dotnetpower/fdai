"""Durable incident lifecycle notification retry tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.incident import (
    DurableIncidentLifecycleNotifier,
    IncidentLifecycleNotice,
    IncidentNoticeKind,
    IncidentRegistry,
    InMemoryIncidentNotificationDeliveryStore,
)
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class RecordingNotifier:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.notices: list[IncidentLifecycleNotice] = []
        self._fail_first = fail_first

    async def notify(self, notice: IncidentLifecycleNotice) -> str:
        self.notices.append(notice)
        if self._fail_first:
            self._fail_first = False
            raise RuntimeError("injected delivery failure")
        return "sent"


def _open_notice() -> IncidentLifecycleNotice:
    return IncidentLifecycleNotice(
        kind=IncidentNoticeKind.OPENED,
        actor_oid="Heimdall",
        occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
        incident_id=UUID("00000000-0000-0000-0000-000000000001"),
        incident_state=IncidentState.OPEN,
        incident_severity=IncidentSeverity.SEV2,
    )


async def test_successful_notice_is_checkpointed_and_not_resent() -> None:
    delegate = RecordingNotifier()
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )

    first = await notifier.notify(_open_notice())
    replayed = await notifier.notify(_open_notice())

    assert first.status == "delivered"
    assert replayed.status == "already_delivered"
    assert len(delegate.notices) == 1


async def test_failed_notice_has_no_checkpoint_and_retries() -> None:
    delegate = RecordingNotifier(fail_first=True)
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )

    with pytest.raises(RuntimeError, match="injected delivery failure"):
        await notifier.notify(_open_notice())
    retried = await notifier.notify(_open_notice())

    assert retried.status == "delivered"
    assert len(delegate.notices) == 2


async def test_two_replicas_dispatch_identical_notice_once() -> None:
    class SlowNotifier(RecordingNotifier):
        async def notify(self, notice: IncidentLifecycleNotice) -> str:
            self.notices.append(notice)
            await asyncio.sleep(0)
            return "sent"

    delivery_store = InMemoryIncidentNotificationDeliveryStore()
    delegate = SlowNotifier()
    first = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=delivery_store,
    )
    second = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=delivery_store,
    )

    results = await asyncio.gather(
        first.notify(_open_notice()),
        second.notify(_open_notice()),
    )

    assert sorted(result.status for result in results) == ["delivered", "in_progress"]
    assert len(delegate.notices) == 1


async def test_replay_delivers_missing_open_and_transition_once() -> None:
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)
    incident = await registry.open(
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
        opened_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    delegate = RecordingNotifier()
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )
    entries = await state_store.read_incident_transitions()

    first = await notifier.replay(entries)
    second = await notifier.replay(entries)

    assert first == 2
    assert second == 0
    assert [notice.kind for notice in delegate.notices] == [
        IncidentNoticeKind.OPENED,
        IncidentNoticeKind.STATE_CHANGED,
    ]


async def test_replay_carries_severity_into_legacy_transition() -> None:
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)
    incident = await registry.open(
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    await registry.transition(
        incident_id=incident.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
    )
    entries = [dict(entry) for entry in await state_store.read_incident_transitions()]
    entries[-1].pop("severity")
    entries[-1].pop("from_severity")
    delegate = RecordingNotifier()
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )

    await notifier.replay(entries)

    assert delegate.notices[-1].incident_severity is IncidentSeverity.SEV2


async def test_replay_delivers_missed_assignment_once() -> None:
    state_store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=state_store)
    incident = await registry.open(
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    await registry.assign(
        incident_id=incident.incident_id,
        assignee_oid="operator-oid",
        actor_oid="dispatcher-oid",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    delegate = RecordingNotifier()
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )

    first = await notifier.replay(await state_store.read_incident_transitions())
    second = await notifier.replay(await state_store.read_incident_transitions())

    assert first == 2
    assert second == 0
    assert delegate.notices[-1].kind is IncidentNoticeKind.ASSIGNED


def test_replay_rejects_malformed_lifecycle_audit() -> None:
    from fdai.core.incident import notice_from_lifecycle_entry

    with pytest.raises(ValueError, match="invalid incident notification audit"):
        notice_from_lifecycle_entry(
            {
                "kind": "incident.transition",
                "incident_id": "not-a-uuid",
                "severity": "sev2",
                "actor_oid": "Heimdall",
            }
        )