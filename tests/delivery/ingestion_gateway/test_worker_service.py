"""Tests for Kafka-driven document processing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from fdai.delivery.ingestion_gateway.worker_service import DocumentIngestionEventConsumer
from fdai.shared.contracts import DocumentWorkerClaimStatus, DocumentWorkerStage
from fdai.shared.providers.document_ingestion import DocumentWorkerClaimConflictError
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


class _Metadata(InMemoryDocumentMetadataStore):
    def __init__(self, upload_id: UUID) -> None:
        super().__init__()
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


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 6, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


async def test_durable_worker_claim_has_exactly_one_concurrent_owner() -> None:
    metadata = InMemoryDocumentMetadataStore()
    upload_id = UUID("00000000-0000-0000-0000-000000000406")

    claims = await asyncio.gather(
        metadata.claim_worker_stage(
            upload_id,
            DocumentWorkerStage.INSPECTION,
            owner="worker-a",
            attempt_id=uuid4(),
            lease_seconds=30,
        ),
        metadata.claim_worker_stage(
            upload_id,
            DocumentWorkerStage.INSPECTION,
            owner="worker-b",
            attempt_id=uuid4(),
            lease_seconds=30,
        ),
    )

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert winners[0].revision == 1


async def test_expired_claim_requires_new_attempt_and_fences_crashed_owner() -> None:
    clock = _Clock()
    metadata = InMemoryDocumentMetadataStore(clock=clock)
    upload_id = UUID("00000000-0000-0000-0000-000000000407")
    first_attempt = uuid4()
    second_attempt = uuid4()
    first = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.INDEXING,
        owner="worker-a",
        attempt_id=first_attempt,
        lease_seconds=10,
    )
    assert first is not None
    assert (
        await metadata.claim_worker_stage(
            upload_id,
            DocumentWorkerStage.INDEXING,
            owner="worker-b",
            attempt_id=second_attempt,
            lease_seconds=10,
        )
        is None
    )

    clock.advance(10)
    recovered = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.INDEXING,
        owner="worker-b",
        attempt_id=second_attempt,
        lease_seconds=10,
    )
    assert recovered is not None
    assert recovered.revision == first.revision + 1
    with pytest.raises(DocumentWorkerClaimConflictError):
        await metadata.complete_worker_stage(
            upload_id,
            DocumentWorkerStage.INDEXING,
            owner="worker-a",
            attempt_id=first_attempt,
            expected_revision=first.revision,
        )
    completed = await metadata.complete_worker_stage(
        upload_id,
        DocumentWorkerStage.INDEXING,
        owner="worker-b",
        attempt_id=second_attempt,
        expected_revision=recovered.revision,
    )
    replayed = await metadata.complete_worker_stage(
        upload_id,
        DocumentWorkerStage.INDEXING,
        owner="worker-b",
        attempt_id=second_attempt,
        expected_revision=recovered.revision,
    )

    assert completed.status is DocumentWorkerClaimStatus.COMPLETED
    assert replayed == completed


async def test_release_requires_owner_revision_and_new_attempt_to_reclaim() -> None:
    metadata = InMemoryDocumentMetadataStore()
    upload_id = UUID("00000000-0000-0000-0000-000000000408")
    first_attempt = uuid4()
    claim = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.INSPECTION,
        owner="worker-a",
        attempt_id=first_attempt,
        lease_seconds=30,
    )
    assert claim is not None
    with pytest.raises(DocumentWorkerClaimConflictError):
        await metadata.release_worker_stage(
            upload_id,
            DocumentWorkerStage.INSPECTION,
            owner="worker-b",
            attempt_id=first_attempt,
            expected_revision=claim.revision,
        )
    released = await metadata.release_worker_stage(
        upload_id,
        DocumentWorkerStage.INSPECTION,
        owner="worker-a",
        attempt_id=first_attempt,
        expected_revision=claim.revision,
    )
    assert released.status is DocumentWorkerClaimStatus.RELEASED
    assert (
        await metadata.claim_worker_stage(
            upload_id,
            DocumentWorkerStage.INSPECTION,
            owner="worker-a",
            attempt_id=first_attempt,
            lease_seconds=30,
        )
        is None
    )
    recovered = await metadata.claim_worker_stage(
        upload_id,
        DocumentWorkerStage.INSPECTION,
        owner="worker-a",
        attempt_id=uuid4(),
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered.revision == released.revision + 1


async def test_duplicate_audited_delivery_runs_stage_once() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000409")
    payload = {
        "producer_principal": "Saga",
        "kind": "document_ingestion",
        "audited_topic": "object.verdict",
        "stage": "received",
        "decision": "admit",
        "upload_id": str(upload_id),
    }
    await bus.publish("object.audit-entry", "doc", payload)
    await bus.publish("object.audit-entry", "doc", payload)
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        metadata=InMemoryDocumentMetadataStore(),
        topic="object.audit-entry",
        retry_seconds=0.01,
    )

    task = asyncio.create_task(consumer.run())
    for _ in range(20):
        if worker.inspected:
            await asyncio.sleep(0)
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker.inspected == [upload_id]


async def test_duplicate_muninn_command_runs_index_once() -> None:
    bus = InMemoryEventBus()
    worker = _Worker()
    upload_id = UUID("00000000-0000-0000-0000-000000000411")
    payload = {
        "producer_principal": "Muninn",
        "kind": "document_ingestion",
        "stage": "indexing",
        "command": "index",
        "upload_id": str(upload_id),
    }
    await bus.publish("object.context-index", "doc", payload)
    await bus.publish("object.context-index", "doc", payload)
    consumer = DocumentIngestionEventConsumer(
        event_bus=bus,
        worker=worker,  # type: ignore[arg-type]
        metadata=InMemoryDocumentMetadataStore(),
        topic="object.audit-entry",
        retry_seconds=0.01,
    )

    task = asyncio.create_task(consumer.run_index_commands())
    for _ in range(20):
        if worker.indexed:
            await asyncio.sleep(0)
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker.indexed == [upload_id]


async def test_cancelled_operation_releases_durable_claim() -> None:
    metadata = InMemoryDocumentMetadataStore()
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=_Worker(),  # type: ignore[arg-type]
        metadata=metadata,
        topic="object.audit-entry",
        worker_owner="worker-cancelled",
    )
    upload_id = UUID("00000000-0000-0000-0000-000000000412")
    started = asyncio.Event()

    async def operation(_: UUID) -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        consumer._run_once(upload_id, DocumentWorkerStage.INSPECTION, operation)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    claim = metadata.worker_claims[(upload_id, DocumentWorkerStage.INSPECTION)]
    assert claim.status is DocumentWorkerClaimStatus.RELEASED


async def test_reordered_index_delivery_releases_then_recovers() -> None:
    metadata = InMemoryDocumentMetadataStore()
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=_Worker(),  # type: ignore[arg-type]
        metadata=metadata,
        topic="object.audit-entry",
        worker_owner="worker-reorder",
    )
    upload_id = UUID("00000000-0000-0000-0000-000000000413")
    calls = 0

    async def operation(_: UUID) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("index command arrived before its persisted state")

    with pytest.raises(ValueError, match="before its persisted state"):
        await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)
    released = metadata.worker_claims[(upload_id, DocumentWorkerStage.INDEXING)]
    assert released.status is DocumentWorkerClaimStatus.RELEASED

    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)

    completed = metadata.worker_claims[(upload_id, DocumentWorkerStage.INDEXING)]
    assert calls == 2
    assert completed.status is DocumentWorkerClaimStatus.COMPLETED
    assert completed.revision == released.revision + 2


async def test_long_operation_renews_claim_before_completion() -> None:
    metadata = InMemoryDocumentMetadataStore()
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=_Worker(),  # type: ignore[arg-type]
        metadata=metadata,
        topic="object.audit-entry",
        worker_owner="worker-heartbeat",
        lease_seconds=3,
    )
    upload_id = UUID("00000000-0000-0000-0000-000000000410")

    async def operation(_: UUID) -> None:
        await asyncio.sleep(1.05)

    await consumer._run_once(upload_id, DocumentWorkerStage.INDEXING, operation)

    claim = metadata.worker_claims[(upload_id, DocumentWorkerStage.INDEXING)]
    assert claim.status is DocumentWorkerClaimStatus.COMPLETED
    assert claim.revision == 3


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

    assert worker.indexed == [upload_id]
    assert worker.decisions == []


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
    metadata = _PersistentMetadata(upload_id)
    consumer = DocumentIngestionEventConsumer(
        event_bus=InMemoryEventBus(),
        worker=worker,  # type: ignore[arg-type]
        metadata=metadata,
        topic="object.audit-entry",
        reconcile_interval_seconds=0.01,
    )

    task = asyncio.create_task(consumer.reconcile())
    await asyncio.wait_for(worker.completed.wait(), timeout=0.5)
    for _ in range(20):
        claim = metadata.worker_claims.get((upload_id, DocumentWorkerStage.INSPECTION))
        if claim is not None and claim.status is DocumentWorkerClaimStatus.COMPLETED:
            break
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert worker.calls == 2
    assert worker.inspected == [upload_id]
    claim = metadata.worker_claims[(upload_id, DocumentWorkerStage.INSPECTION)]
    assert claim.status is DocumentWorkerClaimStatus.COMPLETED
    assert claim.revision == 4
