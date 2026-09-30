"""Var document-ingestion HIL ticket admission."""

from __future__ import annotations

from typing import Any, Protocol

from fdai.agents._framework.var_pending_durability import checkpoint_pending_ticket
from fdai.agents._framework.var_ticket_identity import PendingHilTicket, evict_oldest_ticket
from fdai.shared.providers.state_store import StateStore


class DocumentHilHost(Protocol):
    _MAX_PENDING: int
    _pending: dict[str, PendingHilTicket]
    _state_store: StateStore | None

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


async def ingest_document_hil(host: DocumentHilHost, payload: dict[str, Any]) -> None:
    if (
        payload.get("producer_principal") != "Saga"
        or payload.get("kind") != "document_ingestion"
        or payload.get("audited_topic") != "object.verdict"
        or payload.get("stage") != "protection_check"
        or payload.get("decision") != "hil"
    ):
        return
    correlation = str(payload.get("correlation_id") or "")
    document_id = str(payload.get("document_id") or "")
    upload_id = str(payload.get("upload_id") or "")
    if correlation in host._pending:
        host.record_behavior("document_ticket_duplicate")
        return
    if not correlation or not document_id or not upload_id:
        host.record_behavior("document_ticket_invalid")
        return
    ticket = PendingHilTicket(
        correlation_id=correlation,
        action_type="document.promote-authoritative",
        resource_id=document_id,
        quorum_required=1,
        initiator_principal=str(payload.get("initiator_principal") or "") or None,
        kind="document_ingestion",
        document_id=document_id,
        upload_id=upload_id,
        stage="protection_check",
        idempotency_key=str(payload.get("idempotency_key") or ""),
    )
    await checkpoint_pending_ticket(host._state_store, ticket)
    host._pending[correlation] = ticket
    host.record_behavior("document_ticket_pending")
    if host._state_store is None:
        evict_oldest_ticket(host._pending, host._MAX_PENDING, keep=correlation)


__all__ = ["ingest_document_hil"]
