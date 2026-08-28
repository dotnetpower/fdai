"""Durably publish normalized Azure Monitor webhook Events to Core ingress."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts.azure_monitor import AzureMonitorEvent

from fdai_operator_service.postgres_family_store import PostgresFamilyStore

_LOGGER = logging.getLogger(__name__)


class AzureMonitorEventPublisher(Protocol):
    """Publish one normalized Event through the configured Kafka transport."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AzureMonitorWebhookOutboxDrainer:
    """Lease, validate, publish, and close one normalized webhook proposal."""

    store: PostgresFamilyStore
    publisher: AzureMonitorEventPublisher
    topic: str
    worker_id: str = "operator-azure-monitor-webhook"
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("Azure Monitor event topic MUST be non-empty")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("lease_seconds MUST be in [1, 300]")

    async def run_once(self) -> bool:
        """Publish at most one durable proposal with retry-safe closure."""

        claim = await self.store.claim_webhook_proposal(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return False
        try:
            raw_events = claim.payload.get("events")
            if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= 32:
                raise ValueError("Azure Monitor webhook event batch is malformed")
            events = tuple(AzureMonitorEvent.model_validate(item) for item in raw_events)
            for event in events:
                await self.publisher.publish(
                    self.topic,
                    event.resource_ref,
                    event.model_dump(mode="json"),
                )
        except ValueError:
            await self.store.mark_proposal_rejected(
                key=claim.key,
                claim_id=claim.claim_id,
                reason_code="invalid_azure_monitor_event",
            )
            return False
        except Exception:  # noqa: BLE001 - broker failures retain the durable claim for retry
            await self.store.release_proposal_claim(
                key=claim.key,
                claim_id=claim.claim_id,
            )
            return False
        return await self.store.mark_proposal_published(
            key=claim.key,
            claim_id=claim.claim_id,
        )


class AzureMonitorWebhookBridge:
    """Run the Azure Monitor outbox drainer with application lifecycle ownership."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        publisher: AzureMonitorEventPublisher,
        topic: str,
        retry_seconds: float = 1.0,
    ) -> None:
        if retry_seconds <= 0:
            raise ValueError("Azure Monitor webhook retry_seconds MUST be positive")
        self._drainer = AzureMonitorWebhookOutboxDrainer(store, publisher, topic)
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None

    def workers_ready(self) -> bool:
        """Report whether the configured outbox worker remains active."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start one durable webhook outbox worker."""

        if self._task is None:
            self._task = asyncio.create_task(
                self._run(),
                name="operator-azure-monitor-outbox",
            )

    async def aclose(self) -> None:
        """Cancel and join the webhook outbox worker."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                published = await self._drainer.run_once()
            except Exception:  # noqa: BLE001 - transient store failures retry in-process
                _LOGGER.warning("azure_monitor_webhook_drainer_retrying", exc_info=True)
                published = False
            await asyncio.sleep(0 if published else self._retry_seconds)


__all__ = [
    "AzureMonitorEventPublisher",
    "AzureMonitorWebhookBridge",
    "AzureMonitorWebhookOutboxDrainer",
]
