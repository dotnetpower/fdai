"""At-least-once worker consumer with durable revision-fenced claims."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from functools import partial
from typing import Final, Protocol, runtime_checkable
from uuid import UUID, uuid4

from fdai_service_contracts import (
    ContractValidationError,
    DocumentDeletionRequest,
    DocumentOutboxDrainer,
    DocumentState,
    DocumentWorkerAuditEvent,
    DocumentWorkerClaim,
    DocumentWorkerClaimConflictError,
    DocumentWorkerIndexCommand,
    DocumentWorkerStage,
    EventBus,
    EventEnvelope,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
    UploadSession,
)
from pydantic import ValidationError

from fdai_document_worker_service.effects import WorkerEffectKind, WorkerMetadataStore
from fdai_document_worker_service.processing import DocumentIngestionWorker

_LOGGER = logging.getLogger(__name__)
_ClaimReader = Callable[[], DocumentWorkerClaim]
_ClaimedOperation = Callable[[UUID, _ClaimReader], Awaitable[object]]
_AUDIT_LOOP = "audit"
_INDEX_LOOP = "index"
_DELETION_LOOP = "deletion"
_OUTBOX_LOOP = "outbox"
_RECONCILE_LOOP = "reconcile"


@runtime_checkable
class _ConsumerGroupReadiness(Protocol):
    def consumer_group_ready(
        self,
        topic: str,
        group_id: str,
        *,
        freshness_seconds: float,
    ) -> bool: ...


class DocumentIngestionEventConsumer:
    """Execute audited stages exactly once under renewable durable claims."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        worker: DocumentIngestionWorker,
        metadata: WorkerMetadataStore,
        activity: DocumentOutboxDrainer,
        topic: str,
        group_id: str = "fdai-document-audit-gated-worker",
        retry_seconds: float = 2.0,
        reconcile_interval_seconds: float = 30.0,
        reconcile_batch_size: int = 100,
        worker_owner: str | None = None,
        lease_seconds: int = 120,
        readiness_freshness_seconds: float = 15.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            topic != "object.audit-entry"
            or not group_id
            or retry_seconds <= 0
            or reconcile_interval_seconds <= 0
            or reconcile_batch_size < 1
            or lease_seconds < 3
            or lease_seconds > 3600
            or readiness_freshness_seconds <= 0
        ):
            raise ValueError("document worker MUST consume object.audit-entry with valid limits")
        resolved_owner = worker_owner or f"{socket.gethostname()}:{uuid4().hex}"
        if not resolved_owner or len(resolved_owner) > 256:
            raise ValueError("document worker owner MUST be in [1, 256] characters")
        self._event_bus: Final = event_bus
        self._worker: Final = worker
        self._metadata: Final = metadata
        self._activity: Final = activity
        self._topic: Final = topic
        self._group_id: Final = group_id
        self._retry_seconds: Final = retry_seconds
        self._reconcile_interval_seconds: Final = reconcile_interval_seconds
        self._reconcile_batch_size: Final = reconcile_batch_size
        self._worker_owner: Final = resolved_owner
        self._lease_seconds: Final = lease_seconds
        self._readiness_freshness_seconds: Final = readiness_freshness_seconds
        self._monotonic: Final = monotonic
        self._reconcile_cursors: dict[DocumentState, UUID | None] = {}
        self._loop_failures: dict[str, str] = {}
        self._loop_successes: dict[str, float] = {}
        self._contract_validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    def readiness(self) -> bool:
        """Report whether all required worker loops remain operational."""
        if not isinstance(self._event_bus, _ConsumerGroupReadiness):
            return False
        consumer_groups = (
            (_AUDIT_LOOP, self._topic, self._group_id),
            (_INDEX_LOOP, "object.context-index", "fdai-document-index-worker"),
            (_DELETION_LOOP, "object.event", "fdai-document-deletion-worker"),
        )
        if any(
            loop_name in self._loop_failures
            or not self._event_bus.consumer_group_ready(
                topic,
                group_id,
                freshness_seconds=self._readiness_freshness_seconds,
            )
            for loop_name, topic, group_id in consumer_groups
        ):
            return False
        now = self._monotonic()
        return all(
            loop_name not in self._loop_failures
            and (last_success := self._loop_successes.get(loop_name)) is not None
            and now - last_success <= self._readiness_freshness_seconds
            for loop_name in (_OUTBOX_LOOP, _RECONCILE_LOOP)
        )

    async def run(self) -> None:
        while True:
            try:
                async for event in self._event_bus.subscribe(self._topic, self._group_id):
                    if not _is_document_candidate(
                        event.payload, required_shape=("upload_id", "stage", "decision")
                    ):
                        continue
                    try:
                        command = DocumentWorkerAuditEvent.model_validate(event.payload)
                    except ValidationError:
                        await self._dead_letter_invalid(
                            event, reason="invalid_document_worker_audit_event"
                        )
                        continue
                    if command.stage == "received" and command.decision == "admit":
                        await self._run_once(
                            command.upload_id,
                            DocumentWorkerStage.INSPECTION,
                            self._worker.inspect,
                        )
                    elif command.stage == "protection_check" and command.decision in {
                        "hold",
                        "deny",
                        "rejected",
                    }:
                        await self._run_once(
                            command.upload_id,
                            DocumentWorkerStage.SAFETY_DECISION,
                            partial(
                                self._worker.apply_safety_decision,
                                decision=command.decision,
                                reason=command.reason or "safety_hold",
                            ),
                        )
                    self._loop_succeeded(_AUDIT_LOOP)
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._loop_failed(_AUDIT_LOOP, exc)
                _LOGGER.error(
                    "document_ingestion_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def run_index_commands(self) -> None:
        while True:
            try:
                async for event in self._event_bus.subscribe(
                    "object.context-index", "fdai-document-index-worker"
                ):
                    if not _is_document_candidate(
                        event.payload, required_shape=("upload_id", "stage", "command")
                    ):
                        continue
                    try:
                        command = DocumentWorkerIndexCommand.model_validate(event.payload)
                    except ValidationError:
                        await self._dead_letter_invalid(
                            event, reason="invalid_document_worker_index_command"
                        )
                        continue
                    await self._run_once(
                        command.upload_id,
                        DocumentWorkerStage.INDEXING,
                        self._worker.index,
                    )
                    self._loop_succeeded(_INDEX_LOOP)
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._loop_failed(_INDEX_LOOP, exc)
                _LOGGER.error(
                    "document_index_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def run_deletion_requests(self) -> None:
        """Consume exact revision-fenced deletion requests from Huginn ingress."""
        while True:
            try:
                async for event in self._event_bus.subscribe(
                    "object.event", "fdai-document-deletion-worker"
                ):
                    if not _is_document_candidate(
                        event.payload, required_shape=("deletion_request",)
                    ):
                        continue
                    if (
                        event.payload.get("producer_principal") != "Huginn"
                        or event.payload.get("kind") != "document_ingestion"
                        or event.payload.get("action") != "document.deletion_requested"
                    ):
                        await self._dead_letter_invalid(
                            event, reason="invalid_document_deletion_request"
                        )
                        continue
                    raw_request = event.payload.get("deletion_request")
                    try:
                        if not isinstance(raw_request, dict):
                            raise ValueError("deletion request must be an object")
                        self._contract_validator.validate(
                            "document-deletion-request",
                            raw_request,
                            version="1.0.0",
                        )
                        request = DocumentDeletionRequest.model_validate(raw_request)
                    except (ContractValidationError, ValidationError, ValueError):
                        await self._dead_letter_invalid(
                            event, reason="invalid_document_deletion_request"
                        )
                        continue

                    async def apply(
                        _upload_id: UUID,
                        claim: _ClaimReader,
                        deletion_request: DocumentDeletionRequest = request,
                    ) -> object:
                        return await self._worker.apply_deletion_request(deletion_request, claim)

                    await self._run_once(
                        request.upload_id,
                        DocumentWorkerStage.DELETION,
                        apply,
                    )
                    self._loop_succeeded(_DELETION_LOOP)
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._loop_failed(_DELETION_LOOP, exc)
                _LOGGER.error(
                    "document_deletion_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def drain_outbox(self) -> None:
        """Retry committed worker publications until process shutdown."""
        while True:
            try:
                published = await self._activity.drain()
                self._loop_succeeded(_OUTBOX_LOOP)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._loop_failed(_OUTBOX_LOOP, exc)
                _LOGGER.error(
                    "document_worker_outbox_drain_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                published = 0
            await asyncio.sleep(0.1 if published else self._retry_seconds)

    async def reconcile(self) -> None:
        while True:
            try:
                healthy = await self._reconcile_cycle()
                if healthy:
                    self._loop_succeeded(_RECONCILE_LOOP)
                else:
                    self._loop_failed(
                        _RECONCILE_LOOP,
                        RuntimeError("document reconciliation cycle had failures"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._loop_failed(_RECONCILE_LOOP, exc)
                _LOGGER.error(
                    "document_ingestion_reconcile_cycle_failed",
                    extra={"exception_type": type(exc).__name__},
                )
            await asyncio.sleep(self._reconcile_interval_seconds)

    def _loop_succeeded(self, loop_name: str) -> None:
        self._loop_failures.pop(loop_name, None)
        self._loop_successes[loop_name] = self._monotonic()

    def _loop_failed(self, loop_name: str, exc: Exception) -> None:
        self._loop_failures[loop_name] = type(exc).__name__

    async def _reconcile_cycle(self) -> bool:
        healthy = True
        for effect in await self._metadata.claim_pending_worker_effects(
            limit=self._reconcile_batch_size
        ):
            try:
                if effect.kind is WorkerEffectKind.DELETION_CLEANUP:
                    await self._run_reconcile(
                        effect.upload_id,
                        DocumentWorkerStage.DELETION,
                        partial(self._worker.reconcile_deletion_effect, effect=effect),
                    )
                else:
                    await self._worker.reconcile_effect(effect)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                healthy = False
                _LOGGER.error(
                    "document_worker_effect_reconcile_failed",
                    extra={
                        "effect_id": str(effect.effect_id),
                        "effect_kind": effect.kind.value,
                        "exception_type": type(exc).__name__,
                    },
                )
        replay = (
            (
                DocumentState.RECEIVED,
                DocumentWorkerStage.RECEIVED_REPLAY,
                self._worker.republish_received,
            ),
            (
                DocumentState.PROTECTION_CHECK,
                DocumentWorkerStage.PROTECTION_REPLAY,
                self._worker.republish_inspection,
            ),
        )
        for state, stage, operation in replay:
            for session in await self._next_reconcile_batch(state):
                healthy = await self._run_replay(session.upload_id, stage, operation) and healthy
        for state in (DocumentState.QUARANTINED, DocumentState.SCANNING):
            for session in await self._next_reconcile_batch(state):
                healthy = (
                    await self._run_reconcile(
                        session.upload_id,
                        DocumentWorkerStage.INSPECTION,
                        self._worker.inspect,
                    )
                    and healthy
                )
        for state in (DocumentState.EXTRACTING, DocumentState.INDEXING):
            for session in await self._next_reconcile_batch(state):
                healthy = (
                    await self._run_reconcile(
                        session.upload_id,
                        DocumentWorkerStage.INDEXING,
                        self._worker.index,
                    )
                    and healthy
                )
        return healthy

    async def _next_reconcile_batch(self, state: DocumentState) -> tuple[UploadSession, ...]:
        cursor = self._reconcile_cursors.get(state)
        sessions = await self._metadata.list_uploads_by_state_after(
            state.value,
            after_upload_id=cursor,
            limit=self._reconcile_batch_size,
        )
        if not sessions and cursor is not None:
            cursor = None
            sessions = await self._metadata.list_uploads_by_state_after(
                state.value,
                after_upload_id=None,
                limit=self._reconcile_batch_size,
            )
        self._reconcile_cursors[state] = sessions[-1].upload_id if sessions else cursor
        return sessions

    async def _run_reconcile(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        operation: _ClaimedOperation,
    ) -> bool:
        try:
            await self._run_once(upload_id, stage, operation)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.error(
                "document_ingestion_reconcile_upload_failed",
                extra={
                    "upload_id": str(upload_id),
                    "stage": stage.value,
                    "exception_type": type(exc).__name__,
                },
            )
            return False
        return True

    async def _run_replay(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        operation: Callable[[UUID], Awaitable[object]],
    ) -> bool:
        async def replay(current_upload_id: UUID, _claim: _ClaimReader) -> object:
            return await operation(current_upload_id)

        return await self._run_reconcile(upload_id, stage, replay)

    async def _run_once(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        operation: _ClaimedOperation,
    ) -> None:
        attempt_id = uuid4()
        claim = await self._metadata.claim_worker_stage(
            upload_id,
            stage,
            owner=self._worker_owner,
            attempt_id=attempt_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return
        current_claim = [claim]
        renewal_stop = asyncio.Event()
        operation_task = asyncio.ensure_future(operation(upload_id, lambda: current_claim[0]))
        renewal_task = asyncio.create_task(
            self._renew_claim(upload_id, stage, attempt_id, current_claim, renewal_stop)
        )
        try:
            done, _ = await asyncio.wait(
                {operation_task, renewal_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if renewal_task in done:
                await renewal_task
                raise RuntimeError("document worker claim renewal stopped unexpectedly")
            await operation_task
            renewal_stop.set()
            await renewal_task
            await self._metadata.complete_worker_stage(
                upload_id,
                stage,
                owner=self._worker_owner,
                attempt_id=attempt_id,
                expected_revision=current_claim[0].revision,
            )
        except asyncio.CancelledError:
            renewal_stop.set()
            await self._cancel_operation(operation_task)
            await asyncio.gather(renewal_task, return_exceptions=True)
            await self._release_claim_safely(
                upload_id, stage, attempt_id, current_claim[0].revision
            )
            raise
        except Exception:
            renewal_stop.set()
            await self._cancel_operation(operation_task)
            await asyncio.gather(renewal_task, return_exceptions=True)
            await self._release_claim_safely(
                upload_id, stage, attempt_id, current_claim[0].revision
            )
            raise

    async def _renew_claim(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        attempt_id: UUID,
        current_claim: list[DocumentWorkerClaim],
        stop: asyncio.Event,
    ) -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._lease_seconds / 3)
                return
            except TimeoutError:
                pass
            current_claim[0] = await self._metadata.renew_worker_stage(
                upload_id,
                stage,
                owner=self._worker_owner,
                attempt_id=attempt_id,
                expected_revision=current_claim[0].revision,
                lease_seconds=self._lease_seconds,
            )

    async def _release_claim(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        attempt_id: UUID,
        expected_revision: int,
    ) -> None:
        try:
            await self._metadata.release_worker_stage(
                upload_id,
                stage,
                owner=self._worker_owner,
                attempt_id=attempt_id,
                expected_revision=expected_revision,
            )
        except DocumentWorkerClaimConflictError:
            _LOGGER.warning(
                "document_worker_claim_release_conflict",
                extra={"upload_id": str(upload_id), "stage": stage.value},
            )

    async def _dead_letter_invalid(self, event: EventEnvelope, *, reason: str) -> None:
        await self._event_bus.dead_letter(event.topic, event.key, event.payload, reason)
        _LOGGER.warning(
            "document_worker_message_dead_lettered",
            extra={
                "topic": event.topic,
                "key": event.key,
                "offset": event.offset,
                "reason": reason,
            },
        )

    async def _release_claim_safely(
        self,
        upload_id: UUID,
        stage: DocumentWorkerStage,
        attempt_id: UUID,
        expected_revision: int,
    ) -> None:
        release_task = asyncio.create_task(
            self._release_claim(upload_id, stage, attempt_id, expected_revision)
        )
        try:
            await asyncio.shield(release_task)
        except asyncio.CancelledError:
            await release_task
            raise

    @staticmethod
    async def _cancel_operation(
        *tasks: asyncio.Future[object] | asyncio.Task[None],
    ) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _is_document_candidate(
    payload: Mapping[str, object], *, required_shape: tuple[str, ...]
) -> bool:
    """Treat document-shaped records as candidates before strict discriminator validation."""
    return payload.get("kind") == "document_ingestion" or all(
        field in payload for field in required_shape
    )
