"""Atomic lifecycle audit marker tests for durable background tasks."""

from __future__ import annotations

import asyncio

from fdai.delivery.persistence.background_task_lifecycle_audit import (
    StateStoreBackgroundTaskLifecycleAudit,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_concurrent_lifecycle_replay_writes_one_audit_entry() -> None:
    store = InMemoryStateStore()
    writer = StateStoreBackgroundTaskLifecycleAudit(store)
    event: dict[str, object] = {
        "action_kind": "background-task.created",
        "task_id": "background-one",
        "owner_principal_id": "principal-one",
        "correlation_id": "correlation-one",
        "idempotency_key": "idempotency-one",
        "accountable_agent": "Heimdall",
        "created_at": "2026-08-23T00:00:00+00:00",
    }

    await asyncio.gather(*(writer.append(event) for _ in range(10)))

    assert len(tuple(store.audit_entries)) == 1
    assert store.audit_entries[0]["entry"]["action_kind"] == "background-task.created"
    assert await store.verify_chain() is True
