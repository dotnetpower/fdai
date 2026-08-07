"""Durable audit-first activity delivery owned by the worker."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

import psycopg
from fdai_service_contracts import (
    AUDIT_APPEND_LOCK_KEY,
    AUDIT_GENESIS_HASH,
    EventBus,
    canonical_audit_entry,
    next_audit_hash,
)


class PostgresDocumentActivitySink:
    """Append lifecycle audit records before publishing processing facts."""

    def __init__(self, *, dsn: str, event_bus: EventBus, event_topic: str) -> None:
        self._dsn = dsn
        self._event_bus = event_bus
        self._event_topic = event_topic

    async def audit(self, record: Mapping[str, object]) -> None:
        payload = dict(record)
        canonical = canonical_audit_entry(payload)
        async with (
            await psycopg.AsyncConnection.connect(self._dsn) as connection,
            connection.transaction(),
        ):
            await connection.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_APPEND_LOCK_KEY,))
            row = await (
                await connection.execute(
                    "SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
                )
            ).fetchone()
            previous = str(row[0]) if row is not None else AUDIT_GENESIS_HASH
            entry_hash = next_audit_hash(previous, payload)
            identity = str(payload.get("idempotency_key") or canonical)
            await connection.execute(
                "INSERT INTO audit_log (event_id, correlation_id, actor, action_kind, mode, "
                "entry, previous_hash, entry_hash) VALUES "
                "(%s::uuid, %s, %s, %s, 'shadow', %s::jsonb, %s, %s)",
                (
                    str(uuid5(NAMESPACE_URL, f"fdai.audit://{identity}")),
                    payload.get("correlation_id"),
                    str(payload.get("actor_id") or "ingestion-worker"),
                    str(payload.get("action") or "document.activity"),
                    canonical,
                    previous,
                    entry_hash,
                ),
            )

    async def publish(self, topic: str, key: str, payload: Mapping[str, object]) -> None:
        event = dict(payload)
        event["event_type"] = topic
        try:
            await self._event_bus.publish(self._event_topic, key, event)
        except Exception:
            return
        if topic in {"document.received", "document.inspected"}:
            correlation_id = str(payload.get("upload_id") or key)
            version_id = str(payload.get("version_id") or "")
            await self._event_bus.publish(
                "object.event",
                key,
                {
                    "producer_principal": "Huginn",
                    "kind": "document_ingestion",
                    "action": topic,
                    "event_type": topic,
                    "correlation_id": correlation_id,
                    "idempotency_key": f"{topic}:{version_id or correlation_id}",
                    "resource_id": key,
                    "resource_type": "document",
                    "document_id": key,
                    "record": dict(payload),
                },
            )
