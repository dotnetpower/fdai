"""Publish durable background-task projections to the Operator transport."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from fdai.shared.providers.event_bus import EventBus
from fdai_service_contracts.background_task_projection import (
    BACKGROUND_TASK_PROJECTION_TOPIC,
    BackgroundTaskProjectionEnvelope,
)

from fdai_core_service.contract_codecs import BACKGROUND_TASK_PROJECTION_PRODUCER_V1

_LOGGER = logging.getLogger(__name__)


def _lease_token() -> str:
    return f"background-task-projection:{uuid.uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ClaimedBackgroundTaskProjection:
    """One durable outbox record claimed for publication."""

    outbox_sequence: int
    projection_id: str
    task_id: str
    attempt_id: str
    record: BackgroundTaskProjectionEnvelope


class BackgroundTaskProjectionOutbox(Protocol):
    """Lease durable projection rows until the broker accepts them."""

    async def verify_schema(self) -> None: ...

    async def claim_batch(
        self,
        *,
        worker_id: str,
        lease_token: str,
        now: datetime,
        lease_seconds: int,
        limit: int,
    ) -> tuple[ClaimedBackgroundTaskProjection, ...]: ...

    async def acknowledge(
        self,
        projection_id: str,
        *,
        lease_token: str,
        published_at: datetime,
    ) -> bool: ...

    async def release(
        self,
        projection_id: str,
        *,
        lease_token: str,
        released_at: datetime,
        error_code: str,
    ) -> bool: ...


@dataclass(slots=True)
class BackgroundTaskProjectionPublisher:
    """Publish leased projection rows and acknowledge them after broker acceptance."""

    outbox: BackgroundTaskProjectionOutbox
    topic: str = BACKGROUND_TASK_PROJECTION_TOPIC
    worker_id: str = "background-task-projection-publisher"
    batch_size: int = 100
    lease_seconds: int = 120
    idle_seconds: float = 1.0
    clock: Callable[[], datetime] = field(default=_utc_now, repr=False)
    lease_token_factory: Callable[[], str] = field(default=_lease_token, repr=False)

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("background task projection topic MUST be non-empty")
        if not self.worker_id.strip():
            raise ValueError("background task projection worker_id MUST be non-empty")
        if not 1 <= self.batch_size <= 500:
            raise ValueError("background task projection batch_size MUST be in [1, 500]")
        if not 1 <= self.lease_seconds <= 300:
            raise ValueError("background task projection lease_seconds MUST be in [1, 300]")
        if self.idle_seconds <= 0:
            raise ValueError("background task projection idle_seconds MUST be positive")

    async def run(self, *, bus: EventBus, stop: asyncio.Event) -> None:
        """Publish durable projections until stopped without losing unacked work."""

        await self.outbox.verify_schema()
        while not stop.is_set():
            try:
                published = await self.run_once(bus=bus)
            except Exception:  # noqa: BLE001 - transient outbox or broker failures retry in-process
                _LOGGER.warning("background_task_projection_publish_retrying", exc_info=True)
                published = False
            if stop.is_set() or published:
                continue
            try:
                async with asyncio.timeout(self.idle_seconds):
                    await stop.wait()
            except TimeoutError:
                pass

    async def run_once(self, *, bus: EventBus) -> bool:
        """Claim one bounded batch and publish it with ack-after-broker semantics."""

        claimed_at = self.clock()
        lease_token = self.lease_token_factory()
        claims = tuple(
            sorted(
                await self.outbox.claim_batch(
                    worker_id=self.worker_id,
                    lease_token=lease_token,
                    now=claimed_at,
                    lease_seconds=self.lease_seconds,
                    limit=self.batch_size,
                ),
                key=lambda claim: claim.outbox_sequence,
            )
        )
        if not claims:
            return False
        published_any = False
        for index, claim in enumerate(claims):
            try:
                await bus.publish(self.topic, claim.task_id, _payload(claim.record))
                published_any = True
                acknowledged = await self.outbox.acknowledge(
                    claim.projection_id,
                    lease_token=lease_token,
                    published_at=self.clock(),
                )
                if acknowledged:
                    continue
                await self._release_claims(
                    claims[index:],
                    lease_token=lease_token,
                    error_code="claim_lost",
                )
                return published_any
            except Exception:  # noqa: BLE001 - release and retry the leased rows
                await self._release_claims(
                    claims[index:],
                    lease_token=lease_token,
                    error_code="publish_failed",
                )
                return published_any
        return True

    async def _release_claims(
        self,
        claims: tuple[ClaimedBackgroundTaskProjection, ...],
        *,
        lease_token: str,
        error_code: str,
    ) -> None:
        released_at = self.clock()
        for claim in claims:
            try:
                await self.outbox.release(
                    claim.projection_id,
                    lease_token=lease_token,
                    released_at=released_at,
                    error_code=error_code,
                )
            except Exception:  # noqa: BLE001 - lease expiry still makes the row replayable
                _LOGGER.warning(
                    "background_task_projection_release_retrying",
                    exc_info=True,
                )


def _payload(record: BackgroundTaskProjectionEnvelope) -> Mapping[str, object]:
    encoded = BACKGROUND_TASK_PROJECTION_PRODUCER_V1.encode(record.model_dump(mode="json"))
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):  # pragma: no cover - codec object contract
        raise RuntimeError("background task projection payload is malformed")
    return decoded


__all__ = [
    "BackgroundTaskProjectionOutbox",
    "BackgroundTaskProjectionPublisher",
    "ClaimedBackgroundTaskProjection",
]
