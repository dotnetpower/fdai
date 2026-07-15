"""Incident lifecycle metric projection tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.incident import IncidentRegistry
from fdai.core.incident.metrics import project_incident_metrics
from fdai.shared.contracts.models import IncidentSeverity, IncidentState
from fdai.shared.providers.testing.state_store import InMemoryStateStore

T0 = datetime(2026, 7, 15, tzinfo=UTC)


async def test_metrics_project_creation_lifecycle_metadata_and_durations() -> None:
    store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=store)
    first = await registry.open(
        correlation_keys=("resource:first",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
        opened_at=T0,
    )
    await registry.assign(
        incident_id=first.incident_id,
        assignee_oid="operator-oid",
        actor_oid="dispatcher-oid",
        at=datetime(2026, 7, 15, 0, 0, 30, tzinfo=UTC),
    )
    await registry.link_ticket(
        incident_id=first.incident_id,
        provider="github",
        ticket_id="ISSUE-42",
        actor_oid="Saga",
        at=datetime(2026, 7, 15, 0, 0, 40, tzinfo=UTC),
    )
    await registry.transition(
        incident_id=first.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator-oid",
        at=datetime(2026, 7, 15, 0, 1, tzinfo=UTC),
    )
    await registry.transition(
        incident_id=first.incident_id,
        to_state=IncidentState.RESOLVED,
        actor_oid="operator-oid",
        at=datetime(2026, 7, 15, 0, 5, tzinfo=UTC),
    )
    await registry.transition(
        incident_id=first.incident_id,
        to_state=IncidentState.TRIAGING,
        actor_oid="operator-oid",
        severity=IncidentSeverity.SEV1,
        at=datetime(2026, 7, 15, 0, 6, 40, tzinfo=UTC),
    )

    second = await registry.open(
        correlation_keys=("resource:second",),
        severity=IncidentSeverity.SEV3,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000002"),),
        actor_oid="operator-oid",
        opened_at=T0,
    )
    await registry.transition(
        incident_id=second.incident_id,
        to_state=IncidentState.MITIGATED,
        actor_oid="operator-oid",
        at=datetime(2026, 7, 15, 0, 2, tzinfo=UTC),
    )
    await registry.transition(
        incident_id=second.incident_id,
        to_state=IncidentState.RESOLVED,
        actor_oid="operator-oid",
        at=datetime(2026, 7, 15, 0, 10, tzinfo=UTC),
    )
    entries = list(await store.read_incident_transitions())
    entries.append(dict(entries[-1]))

    metrics = project_incident_metrics(entries, agent_principals={"Heimdall"})

    assert metrics.created_total == 2
    assert metrics.agent_created_total == 1
    assert metrics.operator_created_total == 1
    assert metrics.assignments_total == 1
    assert metrics.tickets_linked_total == 1
    assert metrics.reopen_total == 1
    assert metrics.current_by_state == {"resolved": 1, "triaging": 1}
    assert metrics.current_by_severity == {"sev1": 1, "sev3": 1}
    assert metrics.mean_acknowledgement_seconds == 90.0
    assert metrics.mean_resolution_seconds == 600.0


def test_metrics_reject_transition_before_open() -> None:
    with pytest.raises(ValueError, match="precedes open"):
        project_incident_metrics(
            (
                {
                    "kind": "incident.transition",
                    "idempotency_key": "key",
                    "incident_id": "00000000-0000-0000-0000-000000000001",
                },
            )
        )
