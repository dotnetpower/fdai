"""Core ingress from content-free document-ready facts into governed intent review."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fdai.core.conversation.session import Principal, Role
from fdai.runtime.document_intent import DocumentIntentRuntime
from fdai.shared.providers.event_bus import EventBus, EventEnvelope, subscription

_TOPIC = "object.event"
_GROUP = "fdai-document-intent-ready"


@dataclass(frozen=True, slots=True)
class DocumentIntentIngress:
    """Re-read private envelope bytes and current authority before proposing an exact diff."""

    intent: DocumentIntentRuntime
    pantheon_bus: Any

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        async with subscription(bus, _TOPIC, _GROUP) as stream:
            async for envelope in stream:
                if stop.is_set():
                    return
                await self.handle(bus=bus, envelope=envelope)

    async def handle(self, *, bus: EventBus, envelope: EventEnvelope) -> bool:
        payload = envelope.payload
        record = payload.get("record")
        purposes = record.get("purposes") if isinstance(record, dict) else None
        if (
            envelope.topic != _TOPIC
            or payload.get("kind") != "document_ingestion"
            or payload.get("event_type") not in {"document.ready", "document.deleted"}
            or payload.get("producer_principal") != "Huginn"
            or not isinstance(record, dict)
            or not isinstance(purposes, list)
            or any(not isinstance(purpose, str) for purpose in purposes)
            or "manual_distillation" not in purposes
        ):
            return True
        try:
            document_id = UUID(str(record["document_id"]))
            version_id = UUID(str(record["version_id"]))
            if payload["event_type"] == "document.deleted":
                if (
                    envelope.key != str(document_id)
                    or record.get("state") != "deleted"
                    or record.get("retention_state") != "deleted"
                ):
                    raise PermissionError("document intent deletion fact is malformed")
                await self.intent.withdraw_current(
                    self.pantheon_bus,
                    document_id=document_id,
                    version_id=version_id,
                    correlation_id=str(payload.get("idempotency_key") or "document.deleted"),
                )
                return True
            staged = await self.intent.repository.staged_envelope(document_id, version_id)
            if staged is None:
                return True
            if (
                envelope.key != str(document_id)
                or staged.document_id != document_id
                or staged.version_id != version_id
                or staged.source_sha256 != record.get("source_sha256")
                or record.get("state") not in {"ready", "ready_with_warnings"}
                or record.get("index_state") != "active"
                or record.get("retention_state") != "live"
                or record.get("protection_state") != "none"
            ):
                raise PermissionError("document intent ready fact does not match the staged source")
            await self.intent.submit_current(
                self.pantheon_bus,
                staged,
                principal=Principal(id=str(record["uploader_id"]), role=Role.READER),
            )
            return True
        except (KeyError, PermissionError, ValueError):
            await bus.dead_letter(
                _TOPIC,
                envelope.key,
                {"reason": "document_intent_source_rejected", "execution_authority": False},
                "document_intent_source_rejected",
            )
            return False


__all__ = ["DocumentIntentIngress"]
