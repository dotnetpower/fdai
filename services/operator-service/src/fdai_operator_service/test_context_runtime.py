"""Publish authenticated test-context commands from the durable Operator outbox."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from fdai_service_contracts.test_context import (
    TEST_CONTEXT_RESULT_TOPIC,
    TestContextApplication,
    TestContextCommand,
    TestContextRequest,
)

from fdai_operator_service.background_task_projection_runtime import BackgroundTaskProjectionSource
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from fdai_operator_service.postgres_test_context import PostgresTestContextOutbox
from fdai_operator_service.read_investigation_runtime import ReadInvestigationPublisher

_LOGGER = logging.getLogger(__name__)


class TestContextBridge:
    """Lease, validate, and publish exact commands; request acceptance grants no authority."""

    def __init__(
        self,
        *,
        store: PostgresFamilyStore,
        publisher: ReadInvestigationPublisher,
        topic: str,
        source: BackgroundTaskProjectionSource | None = None,
    ) -> None:
        if not topic.strip():
            raise ValueError("test context raw ingress topic is required")
        self._store, self._publisher, self._topic = store, publisher, topic
        self._task: asyncio.Task[None] | None = None
        self._source = source
        self._result_task: asyncio.Task[None] | None = None
        self._results_ready = False

    def workers_ready(self) -> bool:
        return (
            self._task is not None
            and not self._task.done()
            and (
                self._source is None
                or (
                    self._results_ready
                    and self._result_task is not None
                    and not self._result_task.done()
                )
            )
        )

    async def start(self) -> None:
        """Start workers or explicitly restart failed workers without advancing failed offsets."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="operator-test-context-outbox")
            self._task.add_done_callback(self._worker_stopped)
        if self._source is not None and (self._result_task is None or self._result_task.done()):
            self._result_task = asyncio.create_task(
                self._consume(), name="operator-test-context-results"
            )
            self._result_task.add_done_callback(self._worker_stopped)

    @staticmethod
    def _worker_stopped(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            error = task.exception()
            _LOGGER.warning(
                "test_context_worker_stopped",
                extra={
                    "worker": task.get_name(),
                    "error_type": type(error).__name__ if error else "stream_ended",
                },
            )

    async def aclose(self) -> None:
        self._results_ready = False
        if self._result_task is not None:
            self._result_task.cancel()
            await asyncio.gather(self._result_task, return_exceptions=True)
            self._result_task = None
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(1)

    async def consume(self, payload: Mapping[str, object]) -> None:
        """Validate a trusted Core projection against the original durable command."""
        result = TestContextApplication.model_validate(payload)
        async with asyncio.timeout(10):
            await PostgresTestContextOutbox(self._store).record_application(result)

    async def _consume(self) -> None:
        if self._source is None:
            return
        async with asyncio.timeout(5):
            if not await self._source.probe_readiness():
                raise RuntimeError("context result source is unavailable")
        stream = self._source.subscribe(TEST_CONTEXT_RESULT_TOPIC, "operator-test-context-results")
        try:
            self._results_ready = True
            async for payload in stream:
                await self.consume(payload)
        finally:
            self._results_ready = False
            close = getattr(stream, "aclose", None)
            if close is not None:
                async with asyncio.timeout(5):
                    await close()

    async def run_once(self) -> bool:
        """Publish one leased command with bounded I/O and durable retry/failure status."""
        async with asyncio.timeout(15):
            claim_id = str(uuid4())
            rows = await PostgresTestContextOutbox(self._store).claim(claim_id)
            if not rows:
                return False
            key = rows[0]["key"]
            record = rows[0]["value"]
            try:
                command = command_from_record(record)
                if record["attempt"] > 8:
                    raise ValueError("test context delivery retry budget exhausted")
            except (ValueError, TypeError, KeyError):
                await self._store.mark_proposal_rejected(
                    key=key, claim_id=claim_id, reason_code="invalid_test_context_command"
                )
                return False
            try:
                await self._publisher.publish(
                    self._topic,
                    command.idempotency_key,
                    {
                        "event_id": record["proposal_id"],
                        "id": record["proposal_id"],
                        "correlation_id": command.idempotency_key,
                        "idempotency_key": record["proposal_id"],
                        "source": "operator-context-command",
                        "event_type": "test_context.command.v1",
                        "attributes": command.model_dump(mode="json"),
                    },
                )
            except Exception as exc:
                await self._store.release_proposal_claim(key=key, claim_id=claim_id)
                _LOGGER.warning(
                    "test_context_delivery_retry", extra={"error_type": type(exc).__name__}
                )
                return False
            return await self._store.mark_proposal_published(key=key, claim_id=claim_id)


def command_from_record(record: Mapping[str, Any]) -> TestContextCommand:
    """Use only the authenticated durable principal; never accept actor fields from body."""
    payload = record["payload"]
    scope = payload["scope"]
    if scope["subject_id"] != record["principal_id"] or scope.get("principal_kind") != "human":
        raise ValueError("test context command must retain its authenticated human principal")
    request = TestContextRequest.model_validate(payload["body"])
    operation = "test-context." + request.operation
    if record["operation"] != operation or payload["operation"] != operation:
        raise ValueError("test context command operation mismatch")
    if payload["idempotency_key"] != record["idempotency_key"]:
        raise ValueError("test context command idempotency mismatch")
    return TestContextCommand(
        request=request,
        actor_id=record["principal_id"],
        actor_roles=tuple(
            role for role in scope["roles"] if role in {"Contributor", "Approver", "Owner"}
        ),
        idempotency_key=record["idempotency_key"],
        requested_at=datetime.fromisoformat(record["accepted_at"]),
    )
