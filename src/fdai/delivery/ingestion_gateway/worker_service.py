"""Forseti-gated document worker service for at-least-once processing."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final
from uuid import UUID

from fdai.core.document_ingestion import DocumentIngestionWorker
from fdai.shared.contracts import DocumentState
from fdai.shared.providers.document_ingestion import DocumentMetadataStore
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)


class DocumentIngestionEventConsumer:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        worker: DocumentIngestionWorker,
        metadata: DocumentMetadataStore,
        topic: str,
        group_id: str = "fdai-document-audit-gated-worker",
        retry_seconds: float = 2.0,
        reconcile_interval_seconds: float = 30.0,
        reconcile_batch_size: int = 100,
    ) -> None:
        if (
            topic != "object.audit-entry"
            or not group_id
            or retry_seconds <= 0
            or reconcile_interval_seconds <= 0
            or reconcile_batch_size < 1
        ):
            raise ValueError("document worker MUST consume object.audit-entry with valid limits")
        self._event_bus: Final = event_bus
        self._worker: Final = worker
        self._metadata: Final = metadata
        self._topic: Final = topic
        self._group_id: Final = group_id
        self._retry_seconds: Final = retry_seconds
        self._reconcile_interval_seconds: Final = reconcile_interval_seconds
        self._reconcile_batch_size: Final = reconcile_batch_size
        self._active: set[UUID] = set()
        self._active_lock = asyncio.Lock()

    async def run(self) -> None:
        while True:
            try:
                async for event in self._event_bus.subscribe(self._topic, self._group_id):
                    if event.payload.get("kind") != "document_ingestion" or event.payload.get(
                        "audited_topic"
                    ) not in {"object.verdict", "object.approval"}:
                        continue
                    upload_id = event.payload.get("upload_id")
                    if not isinstance(upload_id, str):
                        raise ValueError("audited document admission is missing upload_id")
                    stage = str(event.payload.get("stage") or "")
                    decision = str(event.payload.get("decision") or "hold")
                    if stage == "received" and decision == "admit":
                        await self._run_once(UUID(upload_id), self._worker.inspect)
                    elif stage == "protection_check" and decision in {
                        "hold",
                        "deny",
                        "rejected",
                    }:
                        reason = str(event.payload.get("reason") or "safety_hold")
                        await self._run_once(
                            UUID(upload_id),
                            partial(
                                self._worker.apply_safety_decision,
                                decision=decision,
                                reason=reason,
                            ),
                        )
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error(
                    "document_ingestion_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def run_index_commands(self) -> None:
        """Consume only Muninn-owned commands that unlock indexing."""
        while True:
            try:
                async for event in self._event_bus.subscribe(
                    "object.context-index", "fdai-document-index-worker"
                ):
                    if (
                        event.payload.get("producer_principal") != "Muninn"
                        or event.payload.get("kind") != "document_ingestion"
                        or event.payload.get("stage") != "indexing"
                        or event.payload.get("command") != "index"
                    ):
                        continue
                    upload_id = event.payload.get("upload_id")
                    if not isinstance(upload_id, str):
                        raise ValueError("document index command is missing upload_id")
                    await self._run_once(
                        UUID(upload_id),
                        partial(
                            self._worker.apply_safety_decision,
                            decision="admit",
                            reason="safety_checks_passed",
                        ),
                    )
                await asyncio.sleep(self._retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error(
                    "document_index_event_consumer_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                await asyncio.sleep(self._retry_seconds)

    async def reconcile(self) -> None:
        while True:
            try:
                replay_operations = (
                    (DocumentState.RECEIVED, self._worker.republish_received),
                    (DocumentState.PROTECTION_CHECK, self._worker.republish_inspection),
                )
                for state, operation in replay_operations:
                    sessions = await self._metadata.list_uploads_by_state(
                        state.value,
                        limit=self._reconcile_batch_size,
                    )
                    for session in sessions:
                        try:
                            await self._run_once(session.upload_id, operation)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _LOGGER.error(
                                "document_ingestion_reconcile_republish_failed",
                                extra={
                                    "upload_id": str(session.upload_id),
                                    "state": state.value,
                                    "exception_type": type(exc).__name__,
                                },
                            )
                for state in (
                    DocumentState.QUARANTINED,
                    DocumentState.SCANNING,
                ):
                    sessions = await self._metadata.list_uploads_by_state(
                        state.value,
                        limit=self._reconcile_batch_size,
                    )
                    for session in sessions:
                        try:
                            await self._run_once(session.upload_id, self._worker.inspect)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _LOGGER.error(
                                "document_ingestion_reconcile_upload_failed",
                                extra={
                                    "upload_id": str(session.upload_id),
                                    "exception_type": type(exc).__name__,
                                },
                            )
                for state in (DocumentState.EXTRACTING, DocumentState.INDEXING):
                    sessions = await self._metadata.list_uploads_by_state(
                        state.value,
                        limit=self._reconcile_batch_size,
                    )
                    for session in sessions:
                        try:
                            await self._run_once(session.upload_id, self._worker.index)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _LOGGER.error(
                                "document_ingestion_reconcile_upload_failed",
                                extra={
                                    "upload_id": str(session.upload_id),
                                    "exception_type": type(exc).__name__,
                                },
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _LOGGER.error(
                    "document_ingestion_reconcile_cycle_failed",
                    extra={"exception_type": type(exc).__name__},
                )
            await asyncio.sleep(self._reconcile_interval_seconds)

    async def _run_once(
        self,
        upload_id: UUID,
        operation: Callable[[UUID], Awaitable[object]],
    ) -> None:
        async with self._active_lock:
            if upload_id in self._active:
                return
            self._active.add(upload_id)
        try:
            await operation(upload_id)
        finally:
            async with self._active_lock:
                self._active.discard(upload_id)


__all__ = ["DocumentIngestionEventConsumer"]
