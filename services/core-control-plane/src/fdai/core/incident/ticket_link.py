"""Link successful external-ticket tool receipts to an incident."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.tool import ToolCallOutcome, ToolCallReceipt, ToolCallRequest

from .registry import IncidentRegistry, IncidentTicketLink

_LINKABLE_OUTCOMES = frozenset({ToolCallOutcome.SUCCEEDED, ToolCallOutcome.ALREADY_APPLIED})


async def link_ticket_receipt(
    *,
    registry: IncidentRegistry,
    request: ToolCallRequest,
    receipt: ToolCallReceipt,
    actor_oid: str,
    at: datetime | None = None,
) -> IncidentTicketLink:
    """Validate a successful ticket receipt and append its incident link."""
    if request.mode is not Mode.ENFORCE:
        raise ValueError("only enforce-mode ticket receipts can be linked")
    if receipt.outcome not in _LINKABLE_OUTCOMES:
        raise ValueError(f"cannot link ticket receipt with outcome {receipt.outcome.value}")
    if not receipt.receipt_ref.strip():
        raise ValueError("ticket receipt_ref MUST be non-empty")
    incident_id_value = request.metadata.get("incident_id") or request.arguments.get(
        "incident_id", ""
    )
    provider = request.metadata.get("ticket_provider") or request.arguments.get(
        "ticket_provider", ""
    )
    ticket_url = request.metadata.get("ticket_url") or request.arguments.get("ticket_url")
    if not isinstance(incident_id_value, str):
        raise ValueError("ticket request incident_id MUST be a string")
    if not isinstance(provider, str):
        raise ValueError("ticket request ticket_provider MUST be a string")
    if ticket_url is not None and not isinstance(ticket_url, str):
        raise ValueError("ticket request ticket_url MUST be a string")
    try:
        incident_id = UUID(incident_id_value)
    except ValueError as exc:
        raise ValueError("ticket request metadata.incident_id MUST be a UUID") from exc
    if not provider.strip():
        raise ValueError("ticket request metadata.ticket_provider MUST be non-empty")
    return await registry.link_ticket(
        incident_id=incident_id,
        provider=provider,
        ticket_id=receipt.receipt_ref,
        ticket_url=ticket_url,
        actor_oid=actor_oid,
        at=at,
    )


__all__ = ["link_ticket_receipt"]
