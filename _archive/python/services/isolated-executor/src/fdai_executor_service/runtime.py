"""Event-bus ingress and process supervision for the isolated Executor.

The SD-07 runtime consumes versioned commands, delegates durable no-effect
handling, and publishes terminal shadow receipts. It owns no provider effect
adapter, workload identity, or authority promotion path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol
from uuid import UUID

from fdai_service_contracts import (
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_CONSUMER_GROUP,
    EXECUTOR_RECEIPT_TOPIC,
    CompatibilityError,
)
from fdai_service_contracts.executor import (
    AnyExecutorCommand,
    EventBus,
    EventEnvelope,
    ExecutionPath,
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
    Mode,
    ResourceLock,
    SafeguardBoundExecutorCommand,
    executor_command_id_from_action_payload,
    safeguard_bound_executor_command_id,
)
from fdai_service_contracts.schema import ContractValidationError
from pydantic import TypeAdapter, ValidationError

from fdai_executor_service.contract_codecs import EXECUTOR_COMMAND_CONSUMER_V11
from fdai_executor_service.health import RuntimeHealthServer
from fdai_executor_service.lock import ExecutorShadowCommandHandler
from fdai_executor_service.ports import ExecutorReceiptOutbox, PendingExecutorReceipt
from fdai_executor_service.service import ExecutorCommandConflictError

_LOGGER = logging.getLogger("fdai.isolated_executor")
type ExecutorReceipt = ExecutorShadowReceipt | ExecutorEffectReceipt
_EXECUTOR_COMMAND_ADAPTER: TypeAdapter[AnyExecutorCommand] = TypeAdapter(AnyExecutorCommand)
_EXECUTOR_RECEIPT_ADAPTER: TypeAdapter[ExecutorReceipt] = TypeAdapter(ExecutorReceipt)


class MemoryExecutorReceiptOutbox:
    """Faithful process-local outbox used only when tests omit PostgreSQL."""

    def __init__(self) -> None:
        self._pending: dict[UUID, PendingExecutorReceipt] = {}
        self._committed: dict[UUID, Mapping[str, Any]] = {}
        self._committed_by_command: dict[str, Mapping[str, Any]] = {}

    async def read_committed_receipt(
        self,
        command_id: str,
    ) -> Mapping[str, Any] | None:
        return self._committed_by_command.get(command_id)

    async def commit_receipt(
        self,
        receipt_id: UUID,
        partition_key: str,
        payload: Mapping[str, Any],
        *,
        command_id: str,
        command_offset: int | None,
    ) -> None:
        existing = self._committed_by_command.get(command_id)
        if existing is not None:
            if existing != payload:
                raise RuntimeError("Executor command already has a different terminal receipt")
            self._pending[receipt_id] = PendingExecutorReceipt(
                receipt_id=receipt_id,
                partition_key=partition_key,
                payload=dict(payload),
                command_id=command_id,
                command_offset=command_offset,
            )
            return
        self._committed.setdefault(receipt_id, dict(payload))
        self._committed_by_command[command_id] = dict(payload)
        self._pending.setdefault(
            receipt_id,
            PendingExecutorReceipt(
                receipt_id=receipt_id,
                partition_key=partition_key,
                payload=dict(payload),
                command_id=command_id,
                command_offset=command_offset,
            ),
        )

    async def claim_receipts(self, *, limit: int) -> tuple[PendingExecutorReceipt, ...]:
        return tuple(self._pending.values())[:limit]

    async def mark_receipt_published(self, receipt_id: UUID) -> None:
        self._pending.pop(receipt_id, None)


class ExecutorCommandHandler(Protocol):
    """Handle one validated Executor command under its owned safeguards."""

    async def handle(self, command: AnyExecutorCommand) -> ExecutorReceipt: ...


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
        outbox_readiness_freshness_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        command_lock: ResourceLock | None = None,
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
        self._outbox_readiness_freshness_seconds = (
            outbox_readiness_freshness_seconds
            if outbox_readiness_freshness_seconds is not None
            else max(10.0, retry_seconds * 3)
        )
        if self._outbox_readiness_freshness_seconds < retry_seconds:
            raise ValueError("receipt outbox freshness MUST cover at least one retry interval")
        self._monotonic = monotonic
        self._command_lock = command_lock
        self._local_command_lock = asyncio.Lock()
        self._outbox_task: asyncio.Task[None] | None = None
        self._last_outbox_success: float | None = None

    @property
    def receipt_publication_ready(self) -> bool:
        """Return true only while durable receipt publication is fresh and running."""

        last_success = self._last_outbox_success
        return (
            self._outbox_task is not None
            and not self._outbox_task.done()
            and last_success is not None
            and self._monotonic() - last_success <= self._outbox_readiness_freshness_seconds
        )

    async def run(self) -> None:
        """Consume forever, retrying transport failures after bounded backoff."""
        self._outbox_task = asyncio.create_task(self.drain_outbox(), name="executor-receipt-outbox")
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
            self._outbox_task.cancel()
            await asyncio.gather(self._outbox_task, return_exceptions=True)
            self._outbox_task = None
            self._last_outbox_success = None

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
            else:
                self._last_outbox_success = self._monotonic()
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
            payload = EXECUTOR_COMMAND_CONSUMER_V11.decode_mapping(envelope.payload)
            command = _EXECUTOR_COMMAND_ADAPTER.validate_python(payload)
        except (CompatibilityError, ContractValidationError, ValidationError):
            await self._dead_letter(envelope, "invalid_executor_command")
            return None
        if envelope.key != command.partition_key:
            await self._dead_letter(envelope, "executor_partition_key_mismatch")
            return None
        legacy_bound_identity = False
        if isinstance(command, SafeguardBoundExecutorCommand):
            current_id = safeguard_bound_executor_command_id(
                action_payload=command.action_payload,
                idempotency_key=command.idempotency_key,
                execution_path=command.execution_path.value,
                safeguard_bundle_digest=command.safeguard_proof_bundle_digest,
                source_revision=command.source_revision,
                attempt=command.attempt,
                issued_at=command.issued_at,
                deadline_at=command.deadline_at,
            )
            if command.command_id != current_id:
                legacy_id = executor_command_id_from_action_payload(
                    action_payload=command.action_payload,
                    idempotency_key=command.idempotency_key,
                )
                if command.command_id != legacy_id:
                    await self._dead_letter(envelope, "executor_command_identity_conflict")
                    return None
                legacy_bound_identity = True
        if self._command_lock is None:
            async with self._local_command_lock:
                return await self._handle_validated_command(
                    envelope,
                    command,
                    legacy_bound_identity=legacy_bound_identity,
                )
        async with self._command_lock.acquire(f"fdai:executor-command:{command.command_id}"):
            return await self._handle_validated_command(
                envelope,
                command,
                legacy_bound_identity=legacy_bound_identity,
            )

    async def _handle_validated_command(
        self,
        envelope: EventEnvelope,
        command: AnyExecutorCommand,
        *,
        legacy_bound_identity: bool,
    ) -> ExecutorReceipt | None:
        """Run one command and commit its receipt under command serialization."""

        existing_payload = await self._receipt_outbox.read_committed_receipt(
            str(command.command_id)
        )
        if existing_payload is not None:
            try:
                existing_receipt = _EXECUTOR_RECEIPT_ADAPTER.validate_python(existing_payload)
            except ValidationError as exc:
                raise RuntimeError("stored Executor receipt is malformed") from exc
            if not _receipt_matches_command(command, existing_receipt):
                await self._dead_letter(envelope, "executor_command_identity_conflict")
                return None
            await self._receipt_outbox.commit_receipt(
                existing_receipt.receipt_id,
                command.partition_key,
                existing_receipt.model_dump(mode="json"),
                command_id=str(command.command_id),
                command_offset=envelope.offset,
            )
            return existing_receipt
        if legacy_bound_identity and command.requested_mode is not Mode.SHADOW:
            await self._dead_letter(envelope, "executor_command_identity_conflict")
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
            command_id=str(command.command_id),
            command_offset=envelope.offset,
        )
        correlation = _receipt_correlation(
            receipt_id=receipt.receipt_id,
            payload=receipt.model_dump(mode="json"),
            command_id=str(command.command_id),
            command_offset=envelope.offset,
        )
        _LOGGER.info(
            json.dumps(
                {
                    "event": "isolated_executor_receipt_committed",
                    **correlation,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            extra=correlation,
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
            correlation = _receipt_correlation(
                receipt_id=pending.receipt_id,
                payload=pending.payload,
                command_id=pending.command_id,
                command_offset=pending.command_offset,
            )
            _LOGGER.info(
                json.dumps(
                    {
                        "event": "isolated_executor_receipt_published",
                        **correlation,
                        "topic": broker_receipt.topic,
                        "partition": broker_receipt.partition,
                        "offset": broker_receipt.offset,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                extra={
                    **correlation,
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


def _receipt_matches_command(
    command: AnyExecutorCommand,
    receipt: ExecutorReceipt,
) -> bool:
    return (
        receipt.command_id == command.command_id
        and receipt.action_id == command.action_id
        and receipt.idempotency_key == command.idempotency_key
        and receipt.attempt == command.attempt
        and receipt.action_payload_digest == command.action_payload_digest
        and receipt.requested_mode is command.requested_mode
        and not (
            isinstance(receipt, ExecutorEffectReceipt)
            and command.execution_path is not ExecutionPath.DIRECT_API
            and not _command_identity_binds_execution_path(command)
        )
        and (
            not isinstance(command, SafeguardBoundExecutorCommand)
            or isinstance(receipt, ExecutorShadowReceipt)
            or (
                isinstance(receipt, ExecutorEffectReceipt)
                and receipt.safeguard_proof_bundle_digest == command.safeguard_proof_bundle_digest
            )
        )
    )


def _command_identity_binds_execution_path(command: AnyExecutorCommand) -> bool:
    if not isinstance(command, SafeguardBoundExecutorCommand):
        return False
    return command.command_id == safeguard_bound_executor_command_id(
        action_payload=command.action_payload,
        idempotency_key=command.idempotency_key,
        execution_path=command.execution_path.value,
        safeguard_bundle_digest=command.safeguard_proof_bundle_digest,
        source_revision=command.source_revision,
        attempt=command.attempt,
        issued_at=command.issued_at,
        deadline_at=command.deadline_at,
    )


def _receipt_correlation(
    *,
    receipt_id: UUID,
    payload: Mapping[str, Any],
    command_id: str | None,
    command_offset: int | None,
) -> dict[str, Any]:
    """Project bounded identifiers shared by commit and publication telemetry."""

    return {
        "receipt_id": str(receipt_id),
        "command_id": command_id or _optional_text(payload.get("command_id")),
        "action_id": _optional_text(payload.get("action_id")),
        "command_offset": command_offset,
        "status": _optional_text(payload.get("status")),
        "attempt": payload.get("attempt") if isinstance(payload.get("attempt"), int) else None,
        "effect_applied": payload.get("effect_applied") is True,
        "effect_verified": payload.get("effect_verified") is True,
    }


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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
