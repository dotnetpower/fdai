"""Correlated Core client for the isolated Executor direct-API boundary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast
from uuid import UUID, uuid4

from fdai_service_contracts import (
    CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP,
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_RECEIPT_TOPIC,
    CompatibilityError,
    ConsumerCodec,
    load_manifest_codec,
)
from fdai_service_contracts.executor_models import (
    executor_command_id_from_action_payload,
    safeguard_bound_executor_command_id,
)
from pydantic import ValidationError

from fdai.shared.contracts import (
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
)
from fdai.shared.contracts.models import (
    Action,
    AnyExecutorCommand,
    ExecutionPath,
    Mode,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.event_bus import EventBus, EventPublishNotAttemptedError, subscription
from fdai.shared.providers.executor_receipt_journal import (
    BoundExecutorCommandContext,
    ExecutorReceiptJournal,
    ExecutorReceiptRegistrationUnobservedError,
    ExecutorReceiptStorageUnavailableError,
)
from fdai.shared.providers.executor_receipt_journal import (
    receipt_matches_command as _receipt_matches_command,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.runtime.isolated_executor_client")
_EXECUTOR_RECEIPT_CONSUMER = cast(
    ConsumerCodec,
    load_manifest_codec(
        "executor-receipt",
        artifact_kind="consumer_codecs",
        release="N",
    ),
)
type ExecutorReceipt = ExecutorShadowReceipt | ExecutorEffectReceipt
type PrePublishGuard = Callable[[], Awaitable[datetime]]


class RemoteDirectApiExecutionOutcome(StrEnum):
    """Terminal outcomes returned through the remote Executor port."""

    DISPATCHED = "dispatched"
    ALREADY_APPLIED = "already_applied"
    ABSTAINED_BLAST_RADIUS = "abstained_blast_radius"
    ABSTAINED_PRECONDITION = "abstained_precondition"
    STOPPED = "stopped"
    FAILED = "failed"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    POLICY_DENIED = "policy_denied"
    NETWORK_DENIED = "network_denied"
    REJECTED_MODE = "rejected_mode"
    REJECTED_INVARIANT = "rejected_invariant"
    REJECTED_IDEMPOTENCY_CONFLICT = "rejected_idempotency_conflict"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class RemoteDirectApiExecutionResult:
    """Core-facing structural result without importing a service implementation."""

    action_id: str
    outcome: RemoteDirectApiExecutionOutcome
    mode: Mode = Mode.SHADOW
    receipt_ref: str | None = None
    safeguard_bundle_digest: str | None = None
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _PendingExecutorRequest:
    command: AnyExecutorCommand
    future: asyncio.Future[ExecutorReceipt]


@dataclass(slots=True)
class EventBusDirectApiExecutionClient:
    """Publish governed Actions and correlate unverified dispatch receipts."""

    event_bus: EventBus
    audit_store: StateStore
    instance_id: str
    response_timeout_seconds: float = 45.0
    retry_seconds: float = 0.05
    max_pending_requests: int = 256
    _consumer_task: asyncio.Task[None] | None = None
    _reconciliation_task: asyncio.Task[None] | None = field(default=None, init=False)
    _receipt_journal: ExecutorReceiptJournal | None = field(default=None, init=False)
    _pending: dict[str, _PendingExecutorRequest] = field(default_factory=dict)

    def bind_receipt_journal(self, journal: ExecutorReceiptJournal) -> None:
        """Inject durable receipt correlation without importing its implementation."""

        self._receipt_journal = journal

    async def start(self) -> None:
        """Start receipt ingestion and bounded restart-safe post-release correlation."""

        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consume(),
                name=f"isolated-executor-client:{self.instance_id}",
            )
            self._consumer_task.add_done_callback(self._report_worker_failure)
            await asyncio.sleep(0)
        if self._reconciliation_task is None or self._reconciliation_task.done():
            self._reconciliation_task = asyncio.create_task(
                self._reconcile_receipts(),
                name=f"isolated-executor-receipts:{self.instance_id}",
            )
            self._reconciliation_task.add_done_callback(self._report_worker_failure)

    @staticmethod
    def _report_worker_failure(task: asyncio.Task[None]) -> None:
        """Make unhandled provider failures observable without swallowing or reclassifying them."""

        if not task.cancelled():
            error = task.exception()
            if error is not None:
                _LOGGER.error(
                    "isolated_executor_receipt_worker_failed",
                    extra={"error_type": type(error).__name__},
                )

    async def stop(self) -> None:
        """Stop receipt correlation and cancel unresolved commands."""

        task = self._consumer_task
        self._consumer_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        reconciliation = self._reconciliation_task
        self._reconciliation_task = None
        if reconciliation is not None:
            reconciliation.cancel()
            await asyncio.gather(reconciliation, return_exceptions=True)
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()

    async def execute(self, *, action: Action) -> RemoteDirectApiExecutionResult:
        """Dispatch one Action, failing closed when transport closure is unavailable."""

        now = datetime.now(UTC)
        command = ExecutorCommand.from_action(
            command_id=executor_command_id(action),
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            attempt=1,
            issued_at=now,
            deadline_at=now + timedelta(seconds=self.response_timeout_seconds),
        )
        return await self._execute_command(
            action=action,
            command=command,
            pre_publish_guard=None,
        )

    async def execute_bound(
        self,
        *,
        action: Action,
        safeguard_bundle_digest: str,
        source_revision: str,
        attempt: int,
        pre_publish_guard: PrePublishGuard | None = None,
    ) -> RemoteDirectApiExecutionResult:
        """Dispatch a v1.1 command bound to the finalized safeguard bundle."""

        now = datetime.now(UTC)
        deadline_at = now + timedelta(seconds=self.response_timeout_seconds)
        command = SafeguardBoundExecutorCommand.from_action(
            command_id=_safeguard_bound_command_id(
                action,
                safeguard_bundle_digest=safeguard_bundle_digest,
                source_revision=source_revision,
                attempt=attempt,
                issued_at=now,
                deadline_at=deadline_at,
            ),
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            attempt=attempt,
            issued_at=now,
            deadline_at=deadline_at,
            safeguard_proof_bundle_digest=safeguard_bundle_digest,
            source_revision=source_revision,
        )
        return await self._execute_command(
            action=action,
            command=command,
            pre_publish_guard=pre_publish_guard,
        )

    async def publish_bound(
        self,
        *,
        action: Action,
        safeguard_bundle_digest: str,
        source_revision: str,
        attempt: int,
        pre_publish_guard: PrePublishGuard,
        correlation_context: BoundExecutorCommandContext,
    ) -> SafeguardBoundExecutorCommand:
        """Persist exact correlation before one bounded publication, without waiting.

        Claims survive failure/restart and are never republished. Only the
        original caller may send, under its fresh Core pre-publication guard.
        Missing journal injection fails closed before the guard or publication.
        A failed or cancelled guard retires receipt work, not the attempt claim.
        """

        journal = self._receipt_journal
        if journal is None:
            raise RuntimeError("isolated Executor bound publication requires a receipt journal")
        await self.start()
        now = datetime.now(UTC)
        deadline_at = now + timedelta(seconds=self.response_timeout_seconds)
        command = SafeguardBoundExecutorCommand.from_action(
            command_id=_safeguard_bound_command_id(
                action,
                safeguard_bundle_digest=safeguard_bundle_digest,
                source_revision=source_revision,
                attempt=attempt,
                issued_at=now,
                deadline_at=deadline_at,
            ),
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
            attempt=attempt,
            issued_at=now,
            deadline_at=deadline_at,
            safeguard_proof_bundle_digest=safeguard_bundle_digest,
            source_revision=source_revision,
        )
        registration_id = uuid4()
        duplicate = False
        publication_started = False
        try:
            async with asyncio.timeout(self.response_timeout_seconds):
                registered_command, owner = await journal.register(
                    command, correlation_context, registration_id=registration_id
                )
                if not owner:
                    duplicate = True
                    raise RuntimeError(
                        "isolated Executor attempt already claimed; publication not retried"
                    )
                if registered_command != command:
                    raise RuntimeError("isolated Executor registered command mismatched")
                await pre_publish_guard()
                publication_started = True
                try:
                    await self.event_bus.publish(
                        EXECUTOR_COMMAND_TOPIC,
                        command.partition_key,
                        command.model_dump(mode="json"),
                    )
                except EventPublishNotAttemptedError:
                    publication_started = False
                    raise
        finally:
            if not publication_started and not duplicate:
                await self._record_not_published(journal, command, registration_id=registration_id)
        return command

    async def _record_not_published(
        self,
        journal: ExecutorReceiptJournal,
        command: SafeguardBoundExecutorCommand,
        *,
        registration_id: UUID,
    ) -> None:
        """Retry exact-owned cleanup within one deadline without masking the original failure."""

        try:
            async with asyncio.timeout(self.response_timeout_seconds):
                for attempt in range(4):
                    try:
                        await journal.record_not_published(command, registration_id=registration_id)
                        return
                    except (
                        OSError,
                        ExecutorReceiptStorageUnavailableError,
                        ExecutorReceiptRegistrationUnobservedError,
                    ):
                        if attempt == 3:
                            raise
                        await asyncio.sleep(min(max(self.retry_seconds, 0.01) * 2**attempt, 1.0))
        except (OSError, RuntimeError, ValueError) as exc:
            _LOGGER.error(
                "isolated_executor_no_publication_persistence_failed",
                extra={
                    "command_id": str(command.command_id),
                    "error_type": type(exc).__name__,
                },
            )

    async def _reconcile_receipts(self) -> None:
        """Retry retained receipt/closure joins independently of the Core target lock."""

        while True:
            journal = self._receipt_journal
            if journal is not None:
                try:
                    async with asyncio.timeout(self.response_timeout_seconds):
                        await journal.reconcile()
                except (OSError, RuntimeError, ValueError) as exc:
                    _LOGGER.error(
                        "isolated_executor_receipt_reconciliation_unavailable",
                        extra={"error_type": type(exc).__name__},
                    )
            await asyncio.sleep(max(self.retry_seconds, 0.1))

    async def _execute_command(
        self,
        *,
        action: Action,
        command: AnyExecutorCommand,
        pre_publish_guard: PrePublishGuard | None,
    ) -> RemoteDirectApiExecutionResult:
        await self.start()
        key = str(command.command_id)
        existing = self._pending.get(key)
        if existing is None:
            owner = True
            if len(self._pending) >= self.max_pending_requests:
                return await self._transport_failure(
                    action,
                    "executor command capacity exceeded",
                )
            pending = _PendingExecutorRequest(
                command=command,
                future=asyncio.get_running_loop().create_future(),
            )
            self._pending[key] = pending
            if pre_publish_guard is not None:
                try:
                    await pre_publish_guard()
                except (asyncio.CancelledError, Exception):
                    self._pending.pop(key, None)
                    raise
            try:
                await self.event_bus.publish(
                    EXECUTOR_COMMAND_TOPIC,
                    command.partition_key,
                    command.model_dump(mode="json"),
                )
            except asyncio.CancelledError:
                self._pending.pop(key, None)
                if not pending.future.done():
                    pending.future.cancel()
                raise
            except Exception:
                self._pending.pop(key, None)
                return await self._transport_failure(
                    action,
                    "executor command publication failed",
                )
        else:
            owner = False
            pending = existing
        try:
            receipt = await asyncio.wait_for(
                asyncio.shield(pending.future),
                timeout=self.response_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return await self._transport_failure(action, "executor receipt deadline expired")
        finally:
            if owner:
                self._pending.pop(key, None)
        return _result_from_receipt(action, receipt)

    async def _transport_failure(
        self,
        action: Action,
        reason: str,
    ) -> RemoteDirectApiExecutionResult:
        await self.audit_store.append_audit_entry(
            {
                "event_id": str(action.event_id),
                "action_id": str(action.action_id),
                "idempotency_key": action.idempotency_key,
                "actor": "fdai.runtime.isolated_executor_client",
                "action_kind": "executor.remote.failed",
                "audit_phase": "terminal",
                "mode": action.mode.value,
                "execution_path": "direct_api",
                "outcome": "failed",
                "reason": reason,
                "resource_ref": action.target_resource_ref,
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
        return RemoteDirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=RemoteDirectApiExecutionOutcome.FAILED,
            mode=action.mode,
            reason=reason,
            audit_context={
                "resource_ref": action.target_resource_ref,
                "transport_failure": True,
            },
        )

    async def _consume(self) -> None:
        """Resubscribe after transient persistence failure without acknowledging the delivery."""

        base_backoff = min(max(self.retry_seconds, 0.01), 1.0)
        backoff = base_backoff
        while True:
            try:
                await self._consume_subscription()
            except (OSError, ExecutorReceiptStorageUnavailableError) as exc:
                _LOGGER.warning(
                    "isolated_executor_receipt_subscription_retry",
                    extra={"error_type": type(exc).__name__},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 1.0)
            else:
                backoff = base_backoff
                await asyncio.sleep(self.retry_seconds)

    async def _consume_subscription(self) -> None:
        """Close the subscription on persistence errors before requesting the next record."""

        group_id = CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP
        async with subscription(self.event_bus, EXECUTOR_RECEIPT_TOPIC, group_id) as stream:
            async for envelope in stream:
                try:
                    payload = _EXECUTOR_RECEIPT_CONSUMER.decode_mapping(envelope.payload)
                    receipt = _executor_receipt_from_payload(payload)
                except (CompatibilityError, ValidationError):
                    _LOGGER.warning(
                        "isolated_executor_receipt_rejected",
                        extra={"consumer_group": group_id},
                    )
                    continue
                try:
                    async with asyncio.timeout(self.response_timeout_seconds):
                        journal = self._receipt_journal
                        pending = self._pending.get(str(receipt.command_id))
                        if journal is None and (pending is None or pending.future.done()):
                            raise ExecutorReceiptStorageUnavailableError(
                                "isolated Executor receipt journal is not bound"
                            )
                        retained = (
                            await journal.accept(receipt, partition_key=envelope.key)
                            if journal is not None
                            else False
                        )
                except (OSError, RuntimeError, ValueError) as exc:
                    _LOGGER.error(
                        "isolated_executor_receipt_persistence_failed",
                        extra={
                            "command_id": str(receipt.command_id),
                            "error_type": type(exc).__name__,
                        },
                    )
                    raise
                if retained:
                    continue
                pending = self._pending.get(str(receipt.command_id))
                if pending is None or pending.future.done():
                    continue
                if not _receipt_matches_command(
                    pending.command,
                    receipt,
                    partition_key=envelope.key,
                ):
                    _LOGGER.warning(
                        "isolated_executor_receipt_binding_mismatch",
                        extra={
                            "command_id": str(receipt.command_id),
                            "receipt_id": str(receipt.receipt_id),
                        },
                    )
                    continue
                pending.future.set_result(receipt)


def executor_command_id(action: Action) -> UUID:
    return executor_command_id_from_action_payload(
        action_payload=action.model_dump(mode="json", exclude_none=True),
        idempotency_key=action.idempotency_key,
    )


def _safeguard_bound_command_id(
    action: Action,
    *,
    safeguard_bundle_digest: str,
    source_revision: str,
    attempt: int,
    issued_at: datetime,
    deadline_at: datetime,
) -> UUID:
    return safeguard_bound_executor_command_id(
        action_payload=action.model_dump(mode="json", exclude_none=True),
        idempotency_key=action.idempotency_key,
        execution_path=ExecutionPath.DIRECT_API.value,
        safeguard_bundle_digest=safeguard_bundle_digest,
        source_revision=source_revision,
        attempt=attempt,
        issued_at=issued_at,
        deadline_at=deadline_at,
    )


def _executor_receipt_from_payload(payload: dict[str, Any]) -> ExecutorReceipt:
    version = payload["schema_version"]
    if version == "1.0.0":
        return ExecutorShadowReceipt.model_validate(payload)
    return ExecutorEffectReceipt.model_validate(payload)


def _result_from_receipt(
    action: Action,
    receipt: ExecutorReceipt,
) -> RemoteDirectApiExecutionResult:
    if isinstance(receipt, ExecutorShadowReceipt):
        outcome = (
            RemoteDirectApiExecutionOutcome.EXPIRED
            if receipt.status.value == "expired"
            else RemoteDirectApiExecutionOutcome.REJECTED_MODE
        )
        receipt_ref = None
        rollback_succeeded = None
        effect_verified = False
    else:
        outcome = RemoteDirectApiExecutionOutcome(receipt.status.value)
        receipt_ref = receipt.provider_receipt_ref
        rollback_succeeded = receipt.rollback_succeeded
        effect_verified = receipt.effect_verified
    safeguard_bundle_digest = (
        receipt.safeguard_proof_bundle_digest
        if isinstance(receipt, ExecutorEffectReceipt)
        else None
    )
    return RemoteDirectApiExecutionResult(
        action_id=str(action.action_id),
        outcome=outcome,
        mode=action.mode,
        receipt_ref=receipt_ref,
        safeguard_bundle_digest=safeguard_bundle_digest,
        rollback_succeeded=rollback_succeeded,
        reason=receipt.reason,
        audit_context={
            "resource_ref": action.target_resource_ref,
            "action_type": action.action_type,
            "executor_receipt_ref": str(receipt.receipt_id),
            "receipt_schema_version": receipt.schema_version,
            "effect_applied": receipt.effect_applied,
            "effect_verified": effect_verified,
            "audit_ref": receipt.audit_ref,
            "safeguard_bundle_digest": safeguard_bundle_digest,
        },
    )


__all__ = [
    "EventBusDirectApiExecutionClient",
    "RemoteDirectApiExecutionOutcome",
    "RemoteDirectApiExecutionResult",
    "executor_command_id",
]
