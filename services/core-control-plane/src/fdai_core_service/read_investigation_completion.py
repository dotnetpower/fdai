"""Drain durable interactive read completions to the Operator transport."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fdai.delivery.persistence.postgres_read_investigation_completion import (
    PostgresReadInvestigationCompletionStore,
)
from fdai.shared.providers.event_bus import EventBus
from fdai_service_contracts.read_investigation import READ_INVESTIGATION_COMPLETION_TOPIC

Clock = Callable[[], datetime]


@dataclass(slots=True)
class InteractiveCompletionWakeSink:
    """Wake the outbox drainer after an atomic terminal transition commits."""

    event: asyncio.Event = field(default_factory=asyncio.Event)

    async def publish(self, _record: object) -> None:
        """Signal durable work without publishing the terminal record directly."""

        self.event.set()


class InteractiveReadInvestigationCompletionPublisher:
    """Publish claimed outbox records and close them after broker acceptance."""

    def __init__(
        self,
        *,
        store: PostgresReadInvestigationCompletionStore,
        topic: str = READ_INVESTIGATION_COMPLETION_TOPIC,
        clock: Clock | None = None,
    ) -> None:
        self._store = store
        self._topic = topic
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run_once(self, *, bus: EventBus) -> int:
        """Publish one bounded claim batch without rerunning an investigation."""

        now = self._clock()
        await self._store.reconcile(now=now)
        lease_token = f"completion-{secrets.token_hex(16)}"
        records = await self._store.claim_due(
            lease_token=lease_token,
            now=now,
            lease_seconds=30,
        )
        delivered = 0
        for record in records:
            try:
                await bus.publish(
                    self._topic,
                    record.task_id,
                    record.payload.model_dump(mode="json"),
                )
            except Exception:  # noqa: BLE001 - provider details never enter durable state
                await self._store.mark_failed(
                    completion_id=record.completion_id,
                    lease_token=lease_token,
                    now=self._clock(),
                    retry_seconds=_retry_seconds(record.delivery_attempt_count),
                )
            else:
                await self._store.mark_delivered(
                    completion_id=record.completion_id,
                    lease_token=lease_token,
                    now=self._clock(),
                )
                delivered += 1
        return delivered


def _retry_seconds(attempt_count: int) -> int:
    delay = 1 << max(0, attempt_count - 1)
    return min(300, delay)


__all__ = [
    "InteractiveCompletionWakeSink",
    "InteractiveReadInvestigationCompletionPublisher",
]
