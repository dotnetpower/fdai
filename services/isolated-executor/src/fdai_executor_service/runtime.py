"""Event-bus ingress and process supervision for the isolated Executor.

The SD-07 runtime consumes versioned commands, delegates durable no-effect
handling, and publishes terminal shadow receipts. It owns no provider effect
adapter, workload identity, or authority promotion path.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

from fdai_service_contracts import (
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_CONSUMER_GROUP,
    EXECUTOR_RECEIPT_TOPIC,
)
from fdai_service_contracts.executor import (
    EventBus,
    EventEnvelope,
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
)
from fdai_service_contracts.schema import ContractValidationError
from pydantic import ValidationError

from fdai_executor_service.health import RuntimeHealthServer
from fdai_executor_service.lock import ExecutorShadowCommandHandler
from fdai_executor_service.ports import ExecutorReceiptOutbox, PendingExecutorReceipt
from fdai_executor_service.service import ExecutorCommandConflictError

_LOGGER = logging.getLogger("fdai.isolated_executor")
type ExecutorReceipt = ExecutorShadowReceipt | ExecutorEffectReceipt


class MemoryExecutorReceiptOutbox:
    """Faithful process-local outbox used only when tests omit PostgreSQL."""

    def __init__(self) -> None:
        self._pending: dict[UUID, PendingExecutorReceipt] = {}
        self._committed: dict[UUID, Mapping[str, Any]] = {}

    async def commit_receipt(
        self, receipt_id: UUID, partition_key: str, payload: Mapping[str, Any]
    ) -> None:
        self._committed.setdefault(receipt_id, dict(payload))
        self._pending.setdefault(
            receipt_id,
            PendingExecutorReceipt(receipt_id, partition_key, dict(payload)),
        )

    async def claim_receipts(self, *, limit: int) -> tuple[PendingExecutorReceipt, ...]:
        return tuple(self._pending.values())[:limit]

    async def mark_receipt_published(self, receipt_id: UUID) -> None:
        self._pending.pop(receipt_id, None)


class ExecutorCommandHandler(Protocol):
    """Handle one validated Executor command under its owned safeguards."""

    async def handle(self, command: ExecutorCommand) -> ExecutorReceipt: ...


class IsolatedExecutorCommandConsumer:
    """Consume commands and publish durable terminal no-effect receipts."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        service: ExecutorCommandHandler | ExecutorShadowCommandHandler,
        command_topic: str = EXECUTOR_COMMAND_TOPIC,
        receipt_topic: str = EXECUTOR_RECEIPT_TOPIC,
        group_id: str = EXECUTOR_CONSUMER_GROUP,
        retry_seconds: float = 2.0,
        receipt_outbox: ExecutorReceiptOutbox | None = None,
    ) -> None:
        if not command_topic or not receipt_topic or not group_id or retry_seconds <= 0:
            raise ValueError("isolated Executor consumer settings MUST be valid")
        if command_topic == receipt_topic:
            raise ValueError("isolated Executor command and receipt topics MUST differ")
        self._event_bus = event_bus
        self._service = service
        self._command_topic = command_topic
        self._receipt_topic = receipt_topic
        self._group_id = group_id
        self._retry_seconds = retry_seconds
        self._receipt_outbox = receipt_outbox or MemoryExecutorReceiptOutbox()

    async def run(self) -> None:
        """Consume forever, retrying transport failures after bounded backoff."""
        drainer = asyncio.create_task(self.drain_outbox(), name="executor-receipt-outbox")
        try:
            while True:
                try:
                    async for envelope in self._event_bus.subscribe(
                        self._command_topic,
                        self._group_id,
                    ):
                        await self.handle_envelope(envelope)
                    await asyncio.sleep(self._retry_seconds)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - broker retry boundary
                    _LOGGER.error(
                        "isolated_executor_consumer_failed",
                        extra={"exception_type": type(exc).__name__},
                    )
                    await asyncio.sleep(self._retry_seconds)
        finally:
            drainer.cancel()
            await asyncio.gather(drainer, return_exceptions=True)

    async def drain_outbox(self) -> None:
        """Retry committed receipt delivery independently of command arrival."""
        while True:
            try:
                published = await self._drain_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - durable rows remain retryable
                _LOGGER.error(
                    "isolated_executor_receipt_outbox_failed",
                    extra={"exception_type": type(exc).__name__},
                )
                published = 0
            await asyncio.sleep(0.1 if published else self._retry_seconds)

    async def handle_envelope(
        self,
        envelope: EventEnvelope,
    ) -> ExecutorReceipt | None:
        """Validate one broker envelope and publish its terminal receipt.

        Invalid immutable records are dead-lettered. State or receipt transport
        failures propagate so the at-least-once broker can redeliver the command.
        """

        try:
            command = ExecutorCommand.model_validate(envelope.payload)
        except ValidationError:
            await self._dead_letter(envelope, "invalid_executor_command")
            return None
        if envelope.key != command.partition_key:
            await self._dead_letter(envelope, "executor_partition_key_mismatch")
            return None
        try:
            receipt = await self._service.handle(command)
        except ContractValidationError:
            await self._dead_letter(envelope, "invalid_executor_action_payload")
            return None
        except ValueError as exc:
            if type(exc).__name__ != "ContractValidationError":
                raise
            await self._dead_letter(envelope, "invalid_executor_action_payload")
            return None
        except ExecutorCommandConflictError:
            await self._dead_letter(envelope, "executor_command_identity_conflict")
            return None

        await self._receipt_outbox.commit_receipt(
            receipt.receipt_id,
            command.partition_key,
            receipt.model_dump(mode="json"),
        )
        _LOGGER.info(
            json.dumps(
                {
                    "event": "isolated_executor_receipt_committed",
                    "command_id": str(command.command_id),
                    "action_id": str(command.action_id),
                    "status": receipt.status.value,
                    "attempt": command.attempt,
                    "effect_applied": receipt.effect_applied,
                    "effect_verified": getattr(receipt, "effect_verified", False),
                    "command_offset": envelope.offset,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            extra={
                "command_id": str(command.command_id),
                "action_id": str(command.action_id),
                "status": receipt.status.value,
                "attempt": command.attempt,
                "effect_applied": receipt.effect_applied,
                "command_offset": envelope.offset,
            },
        )
        return receipt

    async def _drain_once(self) -> int:
        published = 0
        for pending in await self._receipt_outbox.claim_receipts(limit=100):
            broker_receipt = await self._event_bus.publish(
                self._receipt_topic,
                pending.partition_key,
                pending.payload,
            )
            await self._receipt_outbox.mark_receipt_published(pending.receipt_id)
            _LOGGER.info(
                json.dumps(
                    {
                        "event": "isolated_executor_receipt_published",
                        "receipt_id": str(pending.receipt_id),
                        "topic": broker_receipt.topic,
                        "partition": broker_receipt.partition,
                        "offset": broker_receipt.offset,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                extra={
                    "receipt_id": str(pending.receipt_id),
                    "topic": broker_receipt.topic,
                    "partition": broker_receipt.partition,
                    "offset": broker_receipt.offset,
                },
            )
            published += 1
        return published

    async def _dead_letter(self, envelope: EventEnvelope, reason: str) -> None:
        _LOGGER.warning(
            "isolated_executor_command_dead_lettered",
            extra={
                "reason": reason,
                "topic": envelope.topic,
                "offset": envelope.offset,
            },
        )
        await self._event_bus.dead_letter(
            envelope.topic,
            envelope.key,
            envelope.payload,
            reason,
        )


class IsolatedExecutorConsumerLoop(Protocol):
    """Required command loop supplied to the process supervisor."""

    async def run(self) -> None: ...


class IsolatedExecutorSupervisor:
    """Expose health while supervising the required command consumer."""

    def __init__(
        self,
        *,
        consumer: IsolatedExecutorConsumerLoop,
        health_port: int,
        startup_checks: tuple[Callable[[], Awaitable[None]], ...] = (),
        readiness_checks: tuple[Callable[[], bool], ...] = (),
        shutdown_callbacks: tuple[Callable[[], Awaitable[None]], ...] = (),
    ) -> None:
        if not 1 <= health_port <= 65_535:
            raise ValueError("isolated Executor health port MUST be between 1 and 65535")
        self._consumer = consumer
        self._health_port = health_port
        self._startup_checks = startup_checks
        self._readiness_checks = readiness_checks
        self._shutdown_callbacks = shutdown_callbacks
        self._ready = False
        self._consumer_task: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        """Return true only while the required consumer task is running."""

        if not (self._ready and self._consumer_task is not None and not self._consumer_task.done()):
            return False
        try:
            return all(check() for check in self._readiness_checks)
        except Exception:  # noqa: BLE001 - probe callbacks fail closed
            return False

    async def run(self, *, stop: asyncio.Event) -> int:
        """Run until shutdown or required-consumer failure, then drain owners."""

        health = RuntimeHealthServer(
            port=self._health_port,
            readiness=lambda: self.ready,
        )
        stop_task: asyncio.Task[bool] | None = None
        failure: BaseException | None = None
        try:
            for check in self._startup_checks:
                await check()
            await health.start()
            self._consumer_task = asyncio.create_task(
                self._consumer.run(),
                name="isolated-executor-command-consumer",
            )
            stop_task = asyncio.create_task(stop.wait(), name="isolated-executor-stop")
            self._ready = True
            done, _pending = await asyncio.wait(
                {self._consumer_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self._consumer_task in done:
                try:
                    await self._consumer_task
                except BaseException as exc:  # noqa: BLE001 - re-raised after drain
                    failure = exc
                else:
                    failure = RuntimeError("isolated Executor command consumer stopped")
        finally:
            self._ready = False
            tasks = tuple(task for task in (self._consumer_task, stop_task) if task is not None)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await health.close()
            close_results = await asyncio.gather(
                *(callback() for callback in self._shutdown_callbacks),
                return_exceptions=True,
            )
            for result in close_results:
                if isinstance(result, BaseException):
                    _LOGGER.error(
                        "isolated_executor_shutdown_failed",
                        exc_info=result,
                    )
                    if failure is None:
                        failure = result
            self._consumer_task = None
        if failure is not None:
            raise RuntimeError("isolated Executor runtime failed") from failure
        return 0


__all__ = [
    "EXECUTOR_COMMAND_TOPIC",
    "EXECUTOR_CONSUMER_GROUP",
    "EXECUTOR_RECEIPT_TOPIC",
    "ExecutorCommandHandler",
    "MemoryExecutorReceiptOutbox",
    "IsolatedExecutorCommandConsumer",
    "IsolatedExecutorConsumerLoop",
    "IsolatedExecutorSupervisor",
]
