"""Durable audit-first activity delivery owned by the worker."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import psycopg
from fdai_service_contracts import (
    DocumentLifecycleEvent,
    EventBus,
)
from psycopg.rows import dict_row

_LOGGER = logging.getLogger(__name__)


class PostgresDocumentActivitySink:
    """Drain committed worker lifecycle facts without owning Saga audit rows."""

    def __init__(self, *, dsn: str, event_bus: EventBus, event_topic: str) -> None:
        self._dsn = dsn
        self._event_bus = event_bus
        self._event_topic = event_topic

    async def drain(self, *, limit: int = 100) -> int:
        """Publish claimed outbox rows and preserve failed rows for retry."""
        if limit < 1 or limit > 1000:
            raise ValueError("outbox drain limit MUST be in [1, 1000]")
        rows = await self._claim(limit)
        published = 0
        for row in rows:
            event = DocumentLifecycleEvent.model_validate(_payload(row["payload"]))
            try:
                await self._event_bus.publish(event.topic, event.key, event.payload)
            except Exception as exc:  # noqa: BLE001 - durable row remains for retry
                _LOGGER.warning(
                    "document_worker_outbox_publish_failed",
                    extra={"event_id": str(event.event_id), "exception_type": type(exc).__name__},
                )
                continue
            await self._mark_published(event.event_id)
            published += 1
        return published

    async def _claim(self, limit: int) -> list[dict[str, Any]]:
        async with (
            await psycopg.AsyncConnection.connect(self._dsn, row_factory=dict_row) as connection,
            connection.transaction(),
        ):
            rows = await (
                await connection.execute(
                    "SELECT event_id, payload FROM document_worker_outbox "
                    "WHERE published_at IS NULL AND next_attempt_at <= clock_timestamp() "
                    "ORDER BY created_at, event_id FOR UPDATE SKIP LOCKED LIMIT %s",
                    (limit,),
                )
            ).fetchall()
            if rows:
                await connection.execute(
                    "UPDATE document_worker_outbox SET attempt_count = attempt_count + 1, "
                    "next_attempt_at = clock_timestamp() + INTERVAL '5 seconds' "
                    "WHERE event_id = ANY(%s)",
                    ([row["event_id"] for row in rows],),
                )
            return rows

    async def _mark_published(self, event_id: UUID) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as connection:
            await connection.execute(
                "UPDATE document_worker_outbox SET published_at = clock_timestamp() "
                "WHERE event_id = %s AND published_at IS NULL",
                (event_id,),
            )


def _payload(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise RuntimeError("document worker outbox payload is not a JSON object")
