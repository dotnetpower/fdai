"""Local incident store projection tests."""

from __future__ import annotations

from fdai.core.conversation.session import Principal, Role
from fdai.core.incident import IncidentLifecycleWorkflow, IncidentRegistry
from fdai.delivery.read_api.dev.incident_store import ProjectingIncidentStateStore
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel


async def test_confirmed_chat_incident_is_visible_in_local_roster_once() -> None:
    read_model = InMemoryConsoleReadModel()
    workflow = IncidentLifecycleWorkflow(
        registry=IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model))
    )
    principal = Principal(id="operator@example.com", role=Role.CONTRIBUTOR)
    turn = workflow.prepare_chat(
        text="Open a SEV2 incident for target prod-api-01",
        principal=principal,
    )
    assert turn.proposal is not None

    first = await workflow.confirm_chat(
        proposal=turn.proposal,
        principal=principal,
        confirmation="confirm",
    )
    replayed = await workflow.confirm_chat(
        proposal=turn.proposal,
        principal=principal,
        confirmation="confirm",
    )
    page = await read_model.list_incidents(status="active")

    assert first.created is True
    assert replayed.created is False
    assert len(page.items) == 1
    assert page.items[0].incident_id == str(first.incident.incident_id)
    assert page.items[0].status == "open"
    assert page.items[0].severity == "high"


async def test_external_ticket_link_is_visible_in_incident_roster() -> None:
    read_model = InMemoryConsoleReadModel()
    registry = IncidentRegistry(state_store=ProjectingIncidentStateStore(read_model=read_model))
    workflow = IncidentLifecycleWorkflow(registry=registry)
    principal = Principal(id="operator@example.com", role=Role.CONTRIBUTOR)
    turn = workflow.prepare_chat(
        text="Open a SEV2 incident for target prod-api-01",
        principal=principal,
    )
    assert turn.proposal is not None
    opened = await workflow.confirm_chat(
        proposal=turn.proposal,
        principal=principal,
        confirmation="confirm",
    )

    await registry.link_ticket(
        incident_id=opened.incident.incident_id,
        provider="github",
        ticket_id="ISSUE-42",
        ticket_url="https://example.com/issues/42",
        actor_oid="Saga",
    )
    page = await read_model.list_incidents(status="active")

    assert page.items[0].ticket_id == "ISSUE-42"


async def test_legacy_incident_without_top_level_correlation_stays_visible() -> None:
    read_model = InMemoryConsoleReadModel()
    read_model.record_audit_entry(
        {
            "kind": "incident.open",
            "incident_id": "00000000-0000-0000-0000-000000000042",
            "state": "open",
            "severity": "sev2",
            "opened_at": "2026-07-15T00:00:00+00:00",
            "correlation_keys": ["resource:legacy"],
        },
        action_kind="incident.open",
    )

    page = await read_model.list_incidents(status="active")

    assert len(page.items) == 1
    assert page.items[0].correlation_id == "00000000-0000-0000-0000-000000000042"
    assert page.items[0].severity == "high"
