"""Consume Core background-task projections into Operator-owned tables."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.background_task_projection import (
    BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP,
    BACKGROUND_TASK_PROJECTION_TOPIC,
    BackgroundTaskProjectionEnvelope,
)

from fdai_operator_service.contract_codecs import BACKGROUND_TASK_PROJECTION_CONSUMER_V1
from fdai_operator_service.postgres_background_task_projection import (
    BackgroundTaskProjectionConflictError,
    StoredBackgroundTaskProjectionRecord,
)

_LOGGER = logging.getLogger(__name__)
_PROJECTION_ID_PATTERN = re.compile(r"^background-task-(snapshot|progress)-[a-f0-9]{32}$")


class BackgroundTaskProjectionStore(Protocol):
    """Persist authoritative background-task records without execution authority."""

    async def project_background_task_projection(
        self,
        record: BackgroundTaskProjectionEnvelope,
    ) -> StoredBackgroundTaskProjectionRecord: ...

    async def purge_expired_background_task_projections(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> int: ...


class BackgroundTaskProjectionSource(Protocol):
    """Open the projection stream with commit-after-processing semantics."""

    async def probe_readiness(self) -> bool: ...

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]: ...


class BackgroundTaskProjectionPublisher(Protocol):
    """Publish bounded DLQ references for poison projection records."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class BackgroundTaskProjectionConsumer:
    """Validate one projection record and persist it exactly once."""

    store: BackgroundTaskProjectionStore

    async def consume(self, payload: Mapping[str, object]) -> StoredBackgroundTaskProjectionRecord:
        """Reject malformed wire data before touching durable Operator state."""

        decoded = BACKGROUND_TASK_PROJECTION_CONSUMER_V1.decode_mapping(payload)
        record = BackgroundTaskProjectionEnvelope.model_validate(decoded)
        return await self.store.project_background_task_projection(record)


class BackgroundTaskProjectionBridge:
    """Own the supervised background-task projection consumer lifecycle."""

    def __init__(
        self,
        *,
        store: BackgroundTaskProjectionStore,
        source: BackgroundTaskProjectionSource,
        publisher: BackgroundTaskProjectionPublisher,
        topic: str = BACKGROUND_TASK_PROJECTION_TOPIC,
        group_id: str = BACKGROUND_TASK_PROJECTION_CONSUMER_GROUP,
        retry_seconds: float = 1.0,
        retention_interval_seconds: float = 60.0,
        retention_batch_size: int = 200,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not topic.strip() or not group_id.strip():
            raise ValueError(
                "background task projection topic and consumer group MUST be non-empty"
            )
        if retry_seconds <= 0:
            raise ValueError("background task projection retry_seconds MUST be positive")
        if retention_interval_seconds <= 0:
            raise ValueError("background task projection retention interval MUST be positive")
        if not 1 <= retention_batch_size <= 500:
            raise ValueError(
                "background task projection retention batch size MUST be between 1 and 500"
            )
        self._store = store
        self._source = source
        self._publisher = publisher
        self._consumer = BackgroundTaskProjectionConsumer(store)
        self._topic = topic
        self._group_id = group_id
        self._retry_seconds = retry_seconds
        self._retention_interval_seconds = retention_interval_seconds
        self._retention_batch_size = retention_batch_size
        self._clock = clock or _utc_now
        self._consumer_task: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._consumer_healthy = False
        self._retention_healthy = False

    def workers_ready(self) -> bool:
        """Report whether ingest and retention workers remain active."""

        return (
            self._consumer_task is not None
            and not self._consumer_task.done()
            and self._consumer_healthy
            and self._retention_task is not None
            and not self._retention_task.done()
            and self._retention_healthy
        )

    async def start(self) -> None:
        """Start the projection ingest and retention workers once."""

        if self._consumer_task is None:
            self._consumer_task = asyncio.create_task(
                self._run(),
                name="operator-background-task-projection-consumer",
            )
        if self._retention_task is None:
            self._retention_task = asyncio.create_task(
                self._run_retention(),
                name="operator-background-task-projection-retention",
            )

    async def aclose(self) -> None:
        """Cancel and join the projection ingest and retention workers."""

        tasks = tuple(
            task for task in (self._consumer_task, self._retention_task) if task is not None
        )
        self._consumer_task = None
        self._retention_task = None
        self._consumer_healthy = False
        self._retention_healthy = False
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                if not await self._source.probe_readiness():
                    raise RuntimeError("background task projection source is unavailable")
                self._consumer_healthy = True
                async for payload in self._source.subscribe(self._topic, self._group_id):
                    try:
                        await self._consumer.consume(payload)
                    except ValueError:
                        await self._quarantine(payload, reason="invalid_background_task_projection")
                    except BackgroundTaskProjectionConflictError:
                        await self._quarantine(
                            payload,
                            reason="conflicting_background_task_projection",
                        )
                    self._consumer_healthy = True
            except Exception:  # noqa: BLE001 - keep the source offset uncommitted for retry
                self._consumer_healthy = False
                _LOGGER.warning("background_task_projection_consumer_retrying", exc_info=True)
            await asyncio.sleep(self._retry_seconds)

    async def _run_retention(self) -> None:
        while True:
            try:
                deleted = await self._store.purge_expired_background_task_projections(
                    now=self._clock(),
                    limit=self._retention_batch_size,
                )
            except Exception:  # noqa: BLE001 - retries without blocking ingest
                self._retention_healthy = False
                _LOGGER.warning("background_task_projection_retention_retrying", exc_info=True)
                deleted = 0
            else:
                self._retention_healthy = True
            await asyncio.sleep(
                0 if deleted >= self._retention_batch_size else self._retention_interval_seconds
            )

    async def _quarantine(self, payload: Mapping[str, object], *, reason: str) -> None:
        key = _quarantine_key(payload)
        await self._publisher.publish(
            f"{self._topic}.dlq",
            key,
            {
                "original_topic": self._topic,
                "projection_ref": key,
                "reason": reason,
            },
        )


def _quarantine_key(payload: Mapping[str, object]) -> str:
    projection_id = payload.get("projection_id")
    if isinstance(projection_id, str) and _PROJECTION_ID_PATTERN.fullmatch(projection_id):
        return projection_id
    encoded = json.dumps(
        dict(payload),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"invalid-background-task-{hashlib.sha256(encoded).hexdigest()[:32]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "BackgroundTaskProjectionBridge",
    "BackgroundTaskProjectionConsumer",
    "BackgroundTaskProjectionPublisher",
    "BackgroundTaskProjectionSource",
    "BackgroundTaskProjectionStore",
]
