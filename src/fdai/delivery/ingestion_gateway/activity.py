"""Durable audit and event delivery for document-ingestion lifecycle records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fdai.delivery.ingestion_gateway.pantheon_events import EventBusDocumentIngestionIntake
from fdai.shared.providers.document_ingestion import DocumentActivitySink
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


class DurableDocumentActivitySink:
    def __init__(self, *, state_store: StateStore, event_bus: EventBus, event_topic: str) -> None:
        if not event_topic:
            raise ValueError("document event_topic MUST NOT be empty")
        self._state_store: Final = state_store
        self._event_bus: Final = event_bus
        self._event_topic: Final = event_topic

    async def audit(self, record: Mapping[str, object]) -> None:
        await self._state_store.append_audit_entry(record)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> None:
        event = dict(payload)
        event["event_type"] = topic
        try:
            await self._event_bus.publish(self._event_topic, key, event)
        except Exception:
            # Audit and metadata are durable. The worker's received-state
            # reconciler republishes or processes the item after broker recovery.
            return


class PantheonDocumentActivitySink:
    """Wrap a base sink and promote the ingress onto the agent control loop.

    The inner sink keeps the durable audit trail and the worker-reconciliation
    topic. This wrapper additionally publishes the *ingress* transition as
    Huginn's owned ``object.event`` so an uploaded document genuinely enters the
    pantheon control loop rather than being a standalone gateway side effect.
    Only the ingress action is promoted; later stage transitions stay on the
    durable trail until their owning agents drive them.
    """

    _AGENT_EVENT_ACTIONS: Final = frozenset({"document.received", "document.inspected"})

    def __init__(
        self,
        *,
        inner: DocumentActivitySink,
        ingress: EventBusDocumentIngestionIntake,
    ) -> None:
        self._inner: Final = inner
        self._ingress: Final = ingress

    async def audit(self, record: Mapping[str, object]) -> None:
        await self._inner.audit(record)

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> None:
        await self._inner.publish(topic, key, payload)
        if topic in self._AGENT_EVENT_ACTIONS:
            await self._ingress.submit(action=topic, document_id=key, record=payload)


__all__ = ["DurableDocumentActivitySink", "PantheonDocumentActivitySink"]
