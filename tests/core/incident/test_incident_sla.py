"""Incident SLA policy, evaluator, and monitor tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.incident import (
    DurableIncidentLifecycleNotifier,
    IncidentLifecycleNotice,
    IncidentRegistry,
    InMemoryIncidentNotificationDeliveryStore,
)
from fdai.core.incident.sla import IncidentSlaMonitor, IncidentSlaPolicy, evaluate_incident_sla
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _policy(seconds: int = 300) -> IncidentSlaPolicy:
    values = {severity: seconds for severity in IncidentSeverity}
    return IncidentSlaPolicy(acknowledge_seconds=values, resolve_seconds=values)


class RecordingNotifier:
    def __init__(self) -> None:
        self.notices: list[IncidentLifecycleNotice] = []

    async def notify(self, notice: IncidentLifecycleNotice) -> None:
        self.notices.append(notice)


async def _opened_store() -> tuple[InMemoryStateStore, IncidentRegistry, UUID]:
    store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=store)
    incident = await registry.open(
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV1,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
        opened_at=NOW,
    )
    return store, registry, incident.incident_id


async def test_open_incident_breaches_acknowledgement_deadline() -> None:
    store, _, incident_id = await _opened_store()

    notices = evaluate_incident_sla(
        await store.read_incident_transitions(),
        policy=_policy(),
        now=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )

    assert len(notices) == 1
    assert notices[0].incident_id == incident_id
    assert notices[0].reason == "acknowledgement_deadline_exceeded"
    assert notices[0].occurred_at == datetime(2026, 7, 15, 0, 5, tzinfo=UTC)


async def test_triaging_uses_transition_time_and_resolved_is_suppressed() -> None:
    store, registry, incident_id = await _opened_store()
    await registry.transition(
        incident_id=incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        at=datetime(2026, 7, 15, 0, 4, tzinfo=UTC),
    )

    before_deadline = evaluate_incident_sla(
        await store.read_incident_transitions(),
        policy=_policy(),
        now=datetime(2026, 7, 15, 0, 8, 59, tzinfo=UTC),
    )
    at_deadline = evaluate_incident_sla(
        await store.read_incident_transitions(),
        policy=_policy(),
        now=datetime(2026, 7, 15, 0, 9, tzinfo=UTC),
    )
    assert before_deadline == ()
    assert at_deadline[0].reason == "resolution_deadline_exceeded"

    await registry.transition(
        incident_id=incident_id,
        to_state=IncidentState.RESOLVED,
        actor_oid="operator@example.com",
        at=datetime(2026, 7, 15, 0, 10, tzinfo=UTC),
    )
    resolved = evaluate_incident_sla(
        await store.read_incident_transitions(),
        policy=_policy(),
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert resolved == ()


async def test_monitor_repeated_scan_is_deduped_by_durable_notifier() -> None:
    store, _, _ = await _opened_store()
    delegate = RecordingNotifier()
    notifier = DurableIncidentLifecycleNotifier(
        delegate=delegate,
        delivery_store=InMemoryIncidentNotificationDeliveryStore(),
    )
    monitor = IncidentSlaMonitor(
        source=store,
        notifier=notifier,
        policy=_policy(),
        interval_seconds=60,
        clock=lambda: datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )

    assert await monitor.scan_once() == 1
    assert await monitor.scan_once() == 1
    assert len(delegate.notices) == 1


async def test_sla_projection_deduplicates_rows_and_rejects_state_mismatch() -> None:
    store, registry, incident_id = await _opened_store()
    await registry.transition(
        incident_id=incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator@example.com",
        at=datetime(2026, 7, 15, 0, 4, tzinfo=UTC),
    )
    entries = [dict(entry) for entry in await store.read_incident_transitions()]
    duplicated = (*entries, dict(entries[-1]))

    notices = evaluate_incident_sla(
        duplicated,
        policy=_policy(),
        now=datetime(2026, 7, 15, 0, 9, tzinfo=UTC),
    )
    assert len(notices) == 1

    entries[-1]["from_state"] = "resolved"
    with pytest.raises(ValueError, match="state mismatch"):
        evaluate_incident_sla(
            entries,
            policy=_policy(),
            now=datetime(2026, 7, 15, 0, 9, tzinfo=UTC),
        )


def test_policy_from_mapping_is_strict() -> None:
    values = {severity.value: 300 for severity in IncidentSeverity}
    policy = IncidentSlaPolicy.from_mapping(
        {"acknowledge_seconds": values, "resolve_seconds": values}
    )
    assert policy.acknowledge_seconds[IncidentSeverity.SEV1] == 300

    with pytest.raises(ValueError, match="sev5"):
        IncidentSlaPolicy.from_mapping(
            {
                "acknowledge_seconds": {
                    key: value for key, value in values.items() if key != "sev5"
                },
                "resolve_seconds": values,
            }
        )


def test_sla_evaluation_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_incident_sla((), policy=_policy(), now=datetime(2026, 7, 15))
