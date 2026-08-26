"""Focused tests for Operator completion validation and lifecycle handling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta

import fdai_operator_service.read_investigation_completion_runtime as completion_runtime
import pytest
from fdai_operator_service.postgres_read_investigation_completion import (
    ReadInvestigationCompletionConflictError,
    StoredReadInvestigationCompletion,
)
from fdai_operator_service.read_investigation_completion_runtime import (
    ReadInvestigationCompletionBridge,
    ReadInvestigationCompletionConsumer,
)
from fdai_service_contracts.read_investigation import (
    ReadInvestigationCompletion,
    ReadInvestigationCompletionUsage,
    ReadInvestigationOrigin,
    build_read_investigation_completion,
    read_investigation_task_id,
)


def _completion() -> ReadInvestigationCompletion:
    started_at = datetime(2026, 8, 24, tzinfo=UTC)
    return build_read_investigation_completion(
        task_id=read_investigation_task_id("principal-one", "idempotency-one"),
        attempt_id="attempt-one",
        attempt_number=1,
        owner_principal_id="principal-one",
        request_idempotency_key="idempotency-one",
        correlation_id="correlation-one",
        origin=ReadInvestigationOrigin(
            conversation_id="operator-request-one",
            channel_kind="web",
            channel_id="principal-one",
        ),
        status="succeeded",
        terminal_reason="completed",
        summary="Resource is healthy.",
        evidence_refs=("evidence-one",),
        usage=ReadInvestigationCompletionUsage(tool_calls=1),
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=2),
        completed_at=started_at + timedelta(seconds=3),
        retention_until=started_at + timedelta(days=30),
    )


class _Store:
    def __init__(self) -> None:
        self.completions: list[ReadInvestigationCompletion] = []

    async def project_read_investigation_completion(
        self,
        completion: ReadInvestigationCompletion,
    ) -> StoredReadInvestigationCompletion:
        self.completions.append(completion)
        return StoredReadInvestigationCompletion(
            completion_id=completion.completion_id,
            task_id=completion.task_id,
            principal_id=completion.owner_principal_id,
            sequence=len(self.completions),
            event="investigation.completed",
            data=completion.model_dump(mode="json"),
            duplicate=len(self.completions) > 1,
        )


async def test_consumer_validates_then_projects_without_execution_dependency() -> None:
    store = _Store()
    consumer = ReadInvestigationCompletionConsumer(store)
    payload = _completion().model_dump(mode="json")

    first = await consumer.consume(payload)
    second = await consumer.consume(payload)

    assert first.duplicate is False
    assert second.duplicate is True
    assert [item.completion_id for item in store.completions] == [
        payload["completion_id"],
        payload["completion_id"],
    ]


async def test_consumer_rejects_tampered_digest_before_store() -> None:
    store = _Store()
    payload = _completion().model_dump(mode="json")
    payload["summary"] = "tampered"

    with pytest.raises(ValueError, match="digest"):
        await ReadInvestigationCompletionConsumer(store).consume(payload)

    assert store.completions == []


class _Source:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = 0

    async def _stream(self) -> AsyncIterator[Mapping[str, object]]:
        self.started.set()
        try:
            await asyncio.Event().wait()
            if False:
                yield {}
        finally:
            self.closed += 1

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        assert topic == "core.read-investigation.completions"
        assert group_id == "operator-read-investigation-completion-v1"
        return self._stream()


class _Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, Mapping[str, object]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, object],
    ) -> object:
        self.published.append((topic, key, payload))
        return object()


async def test_bridge_supervises_and_joins_one_consumer() -> None:
    source = _Source()
    bridge = ReadInvestigationCompletionBridge(
        store=_Store(),
        source=source,
        publisher=_Publisher(),
    )

    await bridge.start()
    await asyncio.wait_for(source.started.wait(), timeout=1)
    assert bridge.workers_ready() is True

    await bridge.aclose()

    assert bridge.workers_ready() is False
    assert source.closed == 1


class _PayloadSource:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = payload
        self.subscriptions = 0

    async def _stream(self) -> AsyncIterator[Mapping[str, object]]:
        yield self.payload

    def subscribe(
        self,
        topic: str,
        group_id: str,
    ) -> AsyncIterator[Mapping[str, object]]:
        del topic, group_id
        self.subscriptions += 1
        return self._stream()


async def test_bridge_quarantines_invalid_contract_with_opaque_key() -> None:
    source = _PayloadSource({"completion_id": "unsafe\nkey", "summary": "not a contract"})
    publisher = _Publisher()
    bridge = ReadInvestigationCompletionBridge(
        store=_Store(),
        source=source,
        publisher=publisher,
        retry_seconds=0.001,
    )

    await bridge.start()
    for _ in range(100):
        if publisher.published:
            break
        await asyncio.sleep(0.001)
    await bridge.aclose()

    assert len(publisher.published) >= 1
    topic, key, payload = publisher.published[0]
    assert topic == "core.read-investigation.completions.dlq"
    assert key.startswith("invalid-completion-")
    assert "unsafe" not in key
    assert payload["reason"] == "invalid_completion"


class _ConflictingStore(_Store):
    async def project_read_investigation_completion(
        self,
        completion: ReadInvestigationCompletion,
    ) -> StoredReadInvestigationCompletion:
        del completion
        raise ReadInvestigationCompletionConflictError("request not committed")


async def test_bridge_bounds_unmatched_request_retries_before_dlq() -> None:
    source = _PayloadSource(_completion().model_dump(mode="json"))
    publisher = _Publisher()
    bridge = ReadInvestigationCompletionBridge(
        store=_ConflictingStore(),
        source=source,
        publisher=publisher,
        retry_seconds=0.001,
    )

    await bridge.start()
    for _ in range(200):
        if publisher.published:
            break
        await asyncio.sleep(0.001)
    await bridge.aclose()

    assert source.subscriptions == 5
    assert len(publisher.published) == 1
    assert publisher.published[0][2]["reason"] == "unmatched_or_conflicting"


async def test_bridge_does_not_repeat_store_conflicts_while_dlq_is_unavailable() -> None:
    source = _PayloadSource(_completion().model_dump(mode="json"))

    class _CountingStore(_ConflictingStore):
        def __init__(self) -> None:
            self.calls = 0

        async def project_read_investigation_completion(
            self,
            completion: ReadInvestigationCompletion,
        ) -> StoredReadInvestigationCompletion:
            self.calls += 1
            return await super().project_read_investigation_completion(completion)

    class _RecoveringPublisher(_Publisher):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def publish(
            self,
            topic: str,
            key: str,
            payload: Mapping[str, object],
        ) -> object:
            self.attempts += 1
            if self.attempts < 3:
                raise ConnectionError("DLQ unavailable")
            return await super().publish(topic, key, payload)

    store = _CountingStore()
    publisher = _RecoveringPublisher()
    bridge = ReadInvestigationCompletionBridge(
        store=store,
        source=source,
        publisher=publisher,
        retry_seconds=0.001,
    )

    await bridge.start()
    for _ in range(300):
        if publisher.published:
            break
        await asyncio.sleep(0.001)
    await bridge.aclose()

    assert store.calls == 5
    assert publisher.attempts == 3
    assert publisher.published[0][2]["reason"] == "unmatched_or_conflicting"


async def test_bridge_keeps_existing_conflict_bounds_when_tracking_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(completion_runtime, "_MAX_TRACKED_CONFLICTS", 1)
    first = _completion()
    second = build_read_investigation_completion(
        task_id=read_investigation_task_id("principal-two", "idempotency-two"),
        attempt_id="attempt-two",
        attempt_number=1,
        owner_principal_id="principal-two",
        request_idempotency_key="idempotency-two",
        correlation_id="correlation-two",
        origin=ReadInvestigationOrigin(
            conversation_id="operator-request-two",
            channel_kind="web",
            channel_id="principal-two",
        ),
        status="succeeded",
        terminal_reason="completed",
        summary="Resource is healthy.",
        evidence_refs=("evidence-two",),
        usage=ReadInvestigationCompletionUsage(tool_calls=1),
        started_at=first.started_at,
        finished_at=first.finished_at,
        completed_at=first.completed_at,
        retention_until=first.retention_until,
    )

    class _RotatingSource:
        def __init__(self) -> None:
            self.subscriptions = 0

        def subscribe(
            self,
            topic: str,
            group_id: str,
        ) -> AsyncIterator[Mapping[str, object]]:
            del topic, group_id
            self.subscriptions += 1

            async def stream() -> AsyncIterator[Mapping[str, object]]:
                selected = first if self.subscriptions == 1 else second
                yield selected.model_dump(mode="json")

            return stream()

    source = _RotatingSource()
    publisher = _Publisher()
    bridge = ReadInvestigationCompletionBridge(
        store=_ConflictingStore(),
        source=source,
        publisher=publisher,
        retry_seconds=0.001,
    )

    await bridge.start()
    for _ in range(200):
        if publisher.published:
            break
        await asyncio.sleep(0.001)
    await bridge.aclose()

    assert publisher.published[0][2]["reason"] == "conflict_tracking_capacity"
