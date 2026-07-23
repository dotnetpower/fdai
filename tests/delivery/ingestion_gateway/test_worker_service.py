"""Tests for Kafka-driven document processing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

from fdai.delivery.ingestion_gateway.worker_service import DocumentIngestionEventConsumer
from fdai.shared.providers.testing.document_ingestion import InMemoryDocumentMetadataStore
from fdai.shared.providers.testing.event_bus import InMemoryEventBus


class _Worker:
    def __init__(self) -> None:
        self.inspected: list[UUID] = []
        self.indexed: list[UUID] = []
        self.decisions: list[tuple[UUID, str, str]] = []
        self.republished_received: list[UUID] = []
        self.republished_inspection: list[UUID] = []

    async def inspect(self, upload_id: UUID) -> None:
        self.inspected.append(upload_id)

    async def index(self, upload_id: UUID) -> None:
        self.indexed.append(upload_id)

    async def apply_safety_decision(self, upload_id: UUID, *, decision: str, reason: str) -> None:
        self.decisions.append((upload_id, decision, reason))

    async def republish_received(self, upload_id: UUID) -> None:
        self.republished_received.append(upload_id)

    async def republish_inspection(self, upload_id: UUID) -> None:
        self.republished_inspection.append(upload_id)


class _FlakyWorker(_Worker):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.completed = asyncio.Event()

    async def inspect(self, upload_id: UUID) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient worker failure")
        self.inspected.append(upload_id)
        self.completed.set()


class _Metadata:
    def __init__(self, upload_id: UUID) -> None:
        self._upload_id = upload_id
        self.calls = 0
        self.states: list[str] = []
        self._returned_quarantined = False

    async def list_uploads_by_state(self, state: str, *, limit: int):
        self.calls += 1
        self.states.append(state)
        assert limit == 100
        if state == "quarantined" and not self._returned_quarantined:
            self._returned_quarantined = True
            return (SimpleNamespace(upload_id=self._upload_id),)
        return ()


class _PersistentMetadata(_Metadata):
    async def list_uploads_by_state(self, state: str, *, limit: int):
        self.calls += 1
        self.states.append(state)
        assert limit == 100
        if state == "quarantined":
            return (SimpleNamespace(upload_id=self._upload_id),)
        return ()


async def test_worker_processes_forseti_admit_and_ignores_other_verdicts() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000401")
    await bus.publish("object.verdict", "doc", {"kind": "document_ingestion", "decision": "admit"})
    await bus.publish(
        "object.audit-entry",
        "doc",
        {
            "producer_principal": "Saga",
            "kind": "document_ingestion",
            "audited_topic": "object.verdict",
            "stage": "received",
            "decision": "admit",
            "upload_id": str(upload_id),
        },
    )
    await bus.publish(
        "object.audit-entry",
        "doc",
        {
            "producer_principal": "Saga",
            "kind": "document_ingestion",
            "audited_topic": "object.verdict",
            "stage": "protection_check",
            "decision": "hold",
            "reason": "rights_managed_access_denied",
            "upload_id": str(upload_id),
        },
    )
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        metadata=InMemoryDocumentMetadataStore(),
        topic="object.audit-entry",
        retry_seconds=0.01,
    )

    task = asyncio.create_task(consumer.run())
    for _ in range(20):
        if worker.inspected and worker.decisions:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.inspected == [upload_id]
    assert worker.decisions == [(upload_id, "hold", "rights_managed_access_denied")]


async def test_worker_indexes_only_after_muninn_command() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000404")
    await bus.publish(
        "object.audit-entry",
        "doc",
        {
            "producer_principal": "Saga",
            "kind": "document_ingestion",
            "audited_topic": "object.verdict",
            "stage": "protection_check",
            "decision": "admit",
            "upload_id": str(upload_id),
        },
    )
    await bus.publish(
        "object.context-index",
        "doc",
        {
            "producer_principal": "Muninn",
            "kind": "document_ingestion",
            "stage": "indexing",
            "command": "index",
            "upload_id": str(upload_id),
        },
    )
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        metadata=InMemoryDocumentMetadataStore(),
        topic="object.audit-entry",
        retry_seconds=0.01,
    )

    audit_task = asyncio.create_task(consumer.run())
    index_task = asyncio.create_task(consumer.run_index_commands())
    for _ in range(20):
        if worker.decisions:
            break
        await asyncio.sleep(0)
    audit_task.cancel()
    index_task.cancel()
    for task in (audit_task, index_task):
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert worker.decisions == [(upload_id, "admit", "safety_checks_passed")]


async def test_worker_holds_after_saga_sealed_document_rejection() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000405")
    await bus.publish(
        "object.audit-entry",
        "doc",
        {
            "producer_principal": "Saga",
            "kind": "document_ingestion",
            "audited_topic": "object.approval",
            "stage": "protection_check",
            "decision": "rejected",
            "reason": "human_approval",
            "upload_id": str(upload_id),
        },
    )
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        metadata=InMemoryDocumentMetadataStore(),
        topic="object.audit-entry",
        retry_seconds=0.01,
    )

    task = asyncio.create_task(consumer.run())
    for _ in range(20):
        if worker.decisions:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.decisions == [(upload_id, "rejected", "human_approval")]


async def test_reconcile_processes_only_post_admission_uploads() -> None:
    upload_id = UUID("00000000-0000-0000-0000-000000000402")
    worker = _Worker()
    metadata = _Metadata(upload_id)
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=worker,  # type: ignore[arg-type]
        metadata=metadata,  # type: ignore[arg-type]
        topic="object.audit-entry",
        reconcile_interval_seconds=0.01,
    )

    task = asyncio.create_task(consumer.reconcile())
    for _ in range(20):
        if worker.inspected:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.inspected == [upload_id]
    assert "received" in metadata.states
    assert "protection_check" in metadata.states


async def test_reconcile_retries_after_worker_runtime_error() -> None:
    upload_id = UUID("00000000-0000-0000-0000-000000000403")
    worker = _FlakyWorker()
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=worker,  # type: ignore[arg-type]
        metadata=_PersistentMetadata(upload_id),  # type: ignore[arg-type]
        topic="object.audit-entry",
        reconcile_interval_seconds=0.01,
    )

    task = asyncio.create_task(consumer.reconcile())
    await asyncio.wait_for(worker.completed.wait(), timeout=0.5)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.calls == 2
    assert worker.inspected == [upload_id]
