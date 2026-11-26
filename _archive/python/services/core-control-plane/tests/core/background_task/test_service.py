"""Background-task service attribution tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.background_task import (
    BACKGROUND_TASK_ACCOUNTABLE_AGENT,
    BackgroundTaskOrigin,
    BackgroundTaskService,
    InMemoryBackgroundTaskStore,
)

NOW = datetime(2026, 8, 23, 8, 0, tzinfo=UTC)


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _FailOnceAudit(_Audit):
    async def append(self, event: dict[str, object]) -> None:
        if not self.events:
            self.events.append(event)
            raise RuntimeError("audit unavailable")
        self.events.append(event)


async def test_service_records_heimdall_as_accountable_agent() -> None:
    audit = _Audit()
    service = BackgroundTaskService(
        store=InMemoryBackgroundTaskStore(clock=lambda: NOW),
        audit=audit,
    )

    attempt, created = await service.create(
        owner_principal_id="principal-one",
        origin=BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        prompt="Investigate the latency regression.",
        context_digest="context-one",
        correlation_id="correlation-one",
        idempotency_key="idempotency-one",
        now=NOW,
    )

    assert created is True
    assert attempt.task.accountable_agent == BACKGROUND_TASK_ACCOUNTABLE_AGENT
    assert audit.events[0]["accountable_agent"] == BACKGROUND_TASK_ACCOUNTABLE_AGENT


async def test_service_reuses_exact_owner_idempotency_redelivery() -> None:
    audit = _Audit()
    service = BackgroundTaskService(
        store=InMemoryBackgroundTaskStore(clock=lambda: NOW),
        audit=audit,
    )
    request = {
        "owner_principal_id": "principal-one",
        "origin": BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        "prompt": "Investigate the latency regression.",
        "context_digest": "context-one",
        "correlation_id": "correlation-one",
        "idempotency_key": "idempotency-one",
        "now": NOW,
    }

    first, first_created = await service.create(**request)
    replay, replay_created = await service.create(**request)

    assert first_created is True
    assert replay_created is False
    assert replay == first
    assert len(audit.events) == 1


async def test_audit_failure_keeps_task_unclaimable_until_redelivery() -> None:
    store = InMemoryBackgroundTaskStore(clock=lambda: NOW)
    audit = _FailOnceAudit()
    service = BackgroundTaskService(store=store, audit=audit, clock=lambda: NOW)
    request = {
        "owner_principal_id": "principal-one",
        "origin": BackgroundTaskOrigin("conversation-one", "web", "channel-one"),
        "prompt": "Investigate the latency regression.",
        "context_digest": "context-one",
        "correlation_id": "correlation-one",
        "idempotency_key": "idempotency-one",
        "now": NOW,
    }

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.create(**request)

    assert (
        await store.claim_next(
            coordinator="coordinator-one",
            lease_token="lease-one",
            now=NOW,
            lease_seconds=30,
        )
        is None
    )

    replay, created = await service.create(**request)

    assert created is False
    assert await store.creation_audited(replay.task.task_id) is True
    assert (
        await store.claim_next(
            coordinator="coordinator-one",
            lease_token="lease-two",
            now=NOW,
            lease_seconds=30,
        )
        is not None
    )
