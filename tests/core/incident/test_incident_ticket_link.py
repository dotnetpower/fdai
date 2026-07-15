"""External ticket tool receipt linkage tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from fdai.core.incident import IncidentRegistry
from fdai.core.incident.ticket_link import link_ticket_receipt
from fdai.shared.contracts.models import IncidentSeverity, Mode
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt, ToolCallRequest


async def _registry() -> tuple[IncidentRegistry, InMemoryStateStore, UUID]:
    store = InMemoryStateStore()
    registry = IncidentRegistry(state_store=store)
    incident = await registry.open(
        correlation_keys=("resource:example-1",),
        severity=IncidentSeverity.SEV2,
        member_event_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        actor_oid="Heimdall",
    )
    return registry, store, incident.incident_id


def _request(incident_id: UUID) -> ToolCallRequest:
    return ToolCallRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        idempotency_key="ticket-action-1",
        action_type_name="tool.open-incident-ticket",
        rule_ids=("operator-request",),
        tool_ref="incident-ticket",
        labels=("enforce",),
        mode=Mode.ENFORCE,
        metadata={
            "incident_id": str(incident_id),
            "ticket_provider": "jira",
            "ticket_url": "https://example.com/browse/OPS-42",
        },
    )


async def test_successful_tool_receipt_links_ticket() -> None:
    registry, store, incident_id = await _registry()

    link = await link_ticket_receipt(
        registry=registry,
        request=_request(incident_id),
        receipt=ToolCallReceipt(
            outcome=ToolCallOutcome.SUCCEEDED,
            receipt_ref="OPS-42",
        ),
        actor_oid="Saga",
        at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert link.provider == "jira"
    assert link.ticket_id == "OPS-42"
    assert list(store.incident_transitions)[-1]["kind"] == "incident.ticket"


async def test_failed_tool_receipt_is_not_linked() -> None:
    registry, store, incident_id = await _registry()

    with pytest.raises(ValueError, match="outcome failed"):
        await link_ticket_receipt(
            registry=registry,
            request=_request(incident_id),
            receipt=ToolCallReceipt(
                outcome=ToolCallOutcome.FAILED,
                receipt_ref="",
            ),
            actor_oid="Saga",
        )

    assert [entry["kind"] for entry in store.incident_transitions] == ["incident.open"]


async def test_shadow_ticket_receipt_is_not_linked() -> None:
    registry, store, incident_id = await _registry()
    request = _request(incident_id)
    request = replace(request, mode=Mode.SHADOW, labels=("shadow",))

    with pytest.raises(ValueError, match="only enforce-mode"):
        await link_ticket_receipt(
            registry=registry,
            request=request,
            receipt=ToolCallReceipt(
                outcome=ToolCallOutcome.SUCCEEDED,
                receipt_ref="shadow:OPS",
            ),
            actor_oid="Saga",
        )

    assert [entry["kind"] for entry in store.incident_transitions] == ["incident.open"]
