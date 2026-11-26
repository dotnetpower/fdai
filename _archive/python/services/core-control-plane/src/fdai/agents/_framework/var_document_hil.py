"""Var document-ingestion HIL ticket admission."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from fdai_service_contracts.cloud_knowledge_application import CloudApplicationAuthorizationSource

from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.var_pending_durability import checkpoint_pending_ticket
from fdai.agents._framework.var_ticket_identity import PendingHilTicket, evict_oldest_ticket
from fdai.shared.providers.state_store import StateStore


class DocumentHilHost(Protocol):
    _MAX_PENDING: int
    _pending: dict[str, PendingHilTicket]
    _state_store: StateStore | None
    _cloud_application_source: CloudApplicationAuthorizationSource | None
    bus: PantheonBus | None

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
    if payload.get("reason") == "cloud_application_policy_requested":
        approved = None
        try:
            if host._cloud_application_source is None:
                raise ValueError("application authority source is unavailable")
            async with asyncio.timeout(5):
                approved = await host._cloud_application_source.authorize(
                    document_id=document_id,
                    upload_id=upload_id,
                    requester_id=str(payload.get("initiator_principal") or ""),
                )
            if approved is None:
                raise ValueError("application policy request is missing")
        except (ValueError, TimeoutError):
            host.record_behavior("document_policy:held")
        if host.bus is not None:
            request = approved.request if approved is not None else None
            await host.bus.publish(
                "Var",
                "object.approval",
                {
                    "producer_principal": "Var",
                    "kind": "document_ingestion",
                    "stage": "protection_check",
                    "correlation_id": correlation,
                    "resource_id": document_id,
                    "document_id": document_id,
                    "upload_id": upload_id,
                    "state": "approved" if approved else "rejected",
                    "idempotency_key": f"cloud-policy:{upload_id}",
                    "approvers": [approved.approved_by] if approved else [],
                    "reason": (
                        f"standing_cloud_policy:{request.policy_digest}:{request.nonce}"
                        if request
                        else "cloud_application_authority_unavailable"
                    ),
                },
            )
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
