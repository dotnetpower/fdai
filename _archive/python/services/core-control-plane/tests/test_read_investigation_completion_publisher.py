"""Focused interactive completion outbox publisher checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fdai_core_service.read_investigation_completion import (
    InteractiveReadInvestigationCompletionPublisher,
)
from fdai_service_contracts.read_investigation import (
    ReadInvestigationCompletionUsage,
    ReadInvestigationOrigin,
    build_read_investigation_completion,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _payload() -> object:
    return build_read_investigation_completion(
        task_id="background-one",
        attempt_id="interactive-1",
        attempt_number=1,
        owner_principal_id="principal-one",
        request_idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        origin=ReadInvestigationOrigin(
            conversation_id="conversation-one",
            channel_kind="web",
            channel_id="principal-one",
        ),
        status="succeeded",
        terminal_reason="matched",
        summary="completed",
        evidence_refs=(),
        usage=ReadInvestigationCompletionUsage(),
        started_at=NOW,
        finished_at=NOW,
        completed_at=NOW,
        retention_until=NOW + timedelta(days=1),
    )


class _Store:
    def __init__(self) -> None:
        self.record = SimpleNamespace(
            completion_id="completion-one",
            task_id="background-one",
            payload=_payload(),
            delivery_attempt_count=1,
        )
        self.delivered: list[str] = []
        self.failed: list[tuple[str, int]] = []
        self.reconciled = 0

    async def reconcile(self, *, now: datetime) -> int:
        assert now == NOW
        self.reconciled += 1
        return 0

    async def claim_due(self, **_kwargs: object) -> tuple[object, ...]:
        return (self.record,)

    async def mark_delivered(
        self,
        *,
        completion_id: str,
        lease_token: str,
        now: datetime,
    ) -> object:
        assert lease_token.startswith("completion-")
        assert now == NOW
        self.delivered.append(completion_id)
        return self.record

    async def mark_failed(
        self,
        *,
        completion_id: str,
        lease_token: str,
        now: datetime,
        retry_seconds: int,
    ) -> object:
        assert lease_token.startswith("completion-")
        assert now == NOW
        self.failed.append((completion_id, retry_seconds))
        return self.record


class _Bus:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, object]] = []

    async def publish(self, topic: str, key: str, payload: object) -> None:
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))


async def test_publisher_closes_only_after_broker_acceptance() -> None:
    store = _Store()
    bus = _Bus()
    publisher = InteractiveReadInvestigationCompletionPublisher(
        store=store,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    delivered = await publisher.run_once(bus=bus)  # type: ignore[arg-type]

    assert delivered == 1
    assert len(bus.published) == 1
    assert bus.published[0][0] == "core.read-investigation.completions"
    assert bus.published[0][1] == "background-one"
    assert store.delivered == ["completion-one"]
    assert store.failed == []


async def test_publisher_retries_outbox_without_reexecuting_provider() -> None:
    store = _Store()
    publisher = InteractiveReadInvestigationCompletionPublisher(
        store=store,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )

    delivered = await publisher.run_once(bus=_Bus(fail=True))  # type: ignore[arg-type]

    assert delivered == 0
    assert store.delivered == []
    assert store.failed == [("completion-one", 1)]
