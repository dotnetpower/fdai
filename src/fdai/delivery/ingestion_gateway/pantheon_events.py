"""Publish document-ingestion ingress on Huginn's owned ``object.event`` topic.

Document ingestion enters the same agent-driven control loop as any other event.
The upload gateway is a mechanical relay; the document *entering* the system is a
Huginn-owned ``Event`` that Forseti (admissibility) and Heimdall (safety) already
subscribe to. This delivery intake claims the Huginn principal exactly as the
post-turn review intake claims Bragi for ``object.turn`` - the single-writer
registry authorizes the principal, and the gateway never holds Thor's executor
identity. See
``docs/roadmap/interfaces/document-ingestion-agent-ownership.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fdai.shared.providers.event_bus import EventBus


class EventBusDocumentIngestionIntake:
    """Publishes a document ingress as Huginn's owned ``object.event``."""

    def __init__(self, *, bus: EventBus, topic: str = "object.event") -> None:
        if topic != "object.event":
            raise ValueError("document ingestion intake MUST publish object.event")
        self._bus: Final = bus
        self._topic: Final = topic

    async def submit(self, *, action: str, document_id: str, record: Mapping[str, object]) -> None:
        await self._bus.publish(
            self._topic,
            document_id,
            {
                "producer_principal": "Huginn",
                "kind": "document_ingestion",
                "action": action,
                "document_id": document_id,
                "record": dict(record),
            },
        )


__all__ = ["EventBusDocumentIngestionIntake"]
