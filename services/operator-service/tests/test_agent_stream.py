"""Focused contracts for authoritative Agent stream projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_operator_service.streaming.agent_frames import AgentActivityProjector
from fdai_service_contracts import AgentOperationalActivity


def test_runtime_state_projects_to_agent_state() -> None:
    timestamp = datetime.now(UTC).isoformat()
    events = AgentActivityProjector().project(
        {
            "type": "agent.runtime-state",
            "agent": "Huginn",
            "state": "watching",
            "ts": timestamp,
            "correlation_id": None,
            "detail": "Runtime agent initialized",
            "source": "runtime-observed",
        }
    )

    assert len(events) == 1
    assert events[0].event_type == "message"
    assert events[0].payload == {
        "type": "agent.state",
        "agent": "Huginn",
        "state": "watching",
        "ts": timestamp,
        "correlation_id": None,
        "detail": "Runtime agent initialized",
        "source": "runtime-observed",
    }


def test_stage_projection_emits_real_agent_handoff_without_fabricated_ticket() -> None:
    projector = AgentActivityProjector()
    timestamp = datetime.now(UTC).isoformat()
    base = {
        "event_id": "event-1",
        "correlation_id": "correlation-1",
        "phase": "done",
        "source": "runtime-observed",
        "ts": timestamp,
    }

    first = projector.project({**base, "stage": "ingest"})
    second = projector.project({**base, "stage": "route"})

    assert [event.payload["type"] for event in first] == ["agent.state"]
    assert [event.payload["type"] for event in second] == [
        "conversation.turn",
        "agent.state",
    ]
    assert second[0].payload["from_agent"] == "Huginn"
    assert second[0].payload["to_agent"] == "Heimdall"


def test_stage_projection_emits_ticket_only_for_observed_incident_identity() -> None:
    timestamp = datetime.now(UTC).isoformat()
    events = AgentActivityProjector().project(
        {
            "event_id": "event-1",
            "correlation_id": "correlation-1",
            "stage": "verify",
            "phase": "done",
            "source": "runtime-observed",
            "ts": timestamp,
            "detail": {"incident_id": "INC-1", "severity": "high"},
        }
    )

    assert [event.payload["type"] for event in events] == [
        "incident.ticket",
        "agent.state",
    ]
    assert events[0].payload["ticket_id"] == "INC-1"
    assert events[0].payload["involved_agents"] == ["Forseti"]


def test_agent_projection_rejects_unknown_and_future_runtime_records() -> None:
    projector = AgentActivityProjector()
    valid = {
        "type": "agent.runtime-state",
        "agent": "Huginn",
        "state": "watching",
        "ts": datetime.now(UTC).isoformat(),
        "correlation_id": None,
        "detail": None,
        "source": "runtime-observed",
    }

    assert projector.project({**valid, "agent": "Invented"}) == ()
    assert projector.project({**valid, "state": "invented"}) == ()
    assert (
        projector.project({**valid, "ts": (datetime.now(UTC) + timedelta(hours=1)).isoformat()})
        == ()
    )


def test_operational_activity_projects_without_changing_authority() -> None:
    activity = AgentOperationalActivity(
        activity_id="inventory.scan:attempt-1:completed",
        idempotency_key="inventory.scan:attempt-1:completed",
        kind="inventory.scan",
        status="completed",
        owner_agent="Huginn",
        producer="inventory-sync-job",
        observed_at=datetime.now(UTC),
        source="azure-resource-graph",
        freshness="fresh",
        evidence_count=12,
        correlation_id="attempt-1",
    )

    events = AgentActivityProjector().project(activity.model_dump(mode="json"))

    assert len(events) == 1
    assert events[0].payload["type"] == "agent.operational-activity"
    assert events[0].payload["execution_authority"] is False


def test_operational_activity_rejects_future_or_authority_bearing_frames() -> None:
    base = {
        "type": "agent.operational-activity",
        "schema_version": "1.0.0",
        "activity_id": "current-state.read:read-1:completed",
        "idempotency_key": "current-state.read:read-1:completed",
        "kind": "current-state.read",
        "status": "completed",
        "owner_agent": "Heimdall",
        "producer": "core-control-plane",
        "observed_at": datetime.now(UTC).isoformat(),
        "source": "read-investigation",
        "freshness": "fresh",
        "evidence_count": 1,
        "duration_ms": 5,
        "correlation_id": "read-1",
        "reason_codes": [],
        "execution_authority": False,
    }

    assert AgentActivityProjector().project({**base, "execution_authority": True}) == ()
    assert (
        AgentActivityProjector().project(
            {**base, "observed_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
        )
        == ()
    )
