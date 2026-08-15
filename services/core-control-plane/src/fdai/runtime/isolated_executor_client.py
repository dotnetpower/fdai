"""Correlated Core client for the isolated Executor direct-API boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai_service_contracts import (
    CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP,
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_RECEIPT_TOPIC,
    CompatibilityError,
    ConsumerCodec,
    load_manifest_codec,
)
from pydantic import ValidationError

from fdai.shared.contracts import (
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorShadowReceipt,
)
from fdai.shared.contracts.models import Action, ExecutionPath, Mode
from fdai.shared.providers.event_bus import EventBus, subscription
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
    rollback_succeeded: bool | None = None
    reason: str | None = None
    audit_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _PendingExecutorRequest:
    command: ExecutorCommand
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
    _pending: dict[str, _PendingExecutorRequest] = field(default_factory=dict)

    async def start(self) -> None:
        """Start the single receipt consumer used by all pending commands."""

        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consume(),
                name=f"isolated-executor-client:{self.instance_id}",
            )
            await asyncio.sleep(0)

    async def stop(self) -> None:
        """Stop receipt correlation and cancel unresolved commands."""

        task = self._consumer_task
        self._consumer_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()

    async def execute(self, *, action: Action) -> RemoteDirectApiExecutionResult:
        """Dispatch one Action, failing closed when transport closure is unavailable."""

        await self.start()
        command_id = executor_command_id(action)
        key = str(command_id)
        existing = self._pending.get(key)
        if existing is None:
            owner = True
            if len(self._pending) >= self.max_pending_requests:
                return await self._transport_failure(
                    action,
                    "executor command capacity exceeded",
                )
            now = datetime.now(UTC)
            command = ExecutorCommand.from_action(
                command_id=command_id,
                action=action,
                execution_path=ExecutionPath.DIRECT_API,
                attempt=1,
                issued_at=now,
                deadline_at=now + timedelta(seconds=self.response_timeout_seconds),
            )
            pending = _PendingExecutorRequest(
                command=command,
                future=asyncio.get_running_loop().create_future(),
            )
            self._pending[key] = pending
            try:
                await self.event_bus.publish(
                    EXECUTOR_COMMAND_TOPIC,
                    command.partition_key,
                    command.model_dump(mode="json"),
                )
            except asyncio.CancelledError:
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
            audit_context={"resource_ref": action.target_resource_ref},
        )

    async def _consume(self) -> None:
        group_id = CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP
        while True:
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
            await asyncio.sleep(self.retry_seconds)


def executor_command_id(action: Action) -> UUID:
    payload = json.dumps(
        action.model_dump(mode="json", exclude_none=True),
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return uuid5(NAMESPACE_URL, f"fdai:executor-command:{action.idempotency_key}:{digest}")


def _receipt_matches_command(
    command: ExecutorCommand,
    receipt: ExecutorReceipt,
    *,
    partition_key: str,
) -> bool:
    return (
        partition_key == command.partition_key
        and receipt.command_id == command.command_id
        and receipt.action_id == command.action_id
        and receipt.idempotency_key == command.idempotency_key
        and receipt.attempt == command.attempt
        and receipt.action_payload_digest == command.action_payload_digest
        and receipt.requested_mode is command.requested_mode
        and receipt.audit_ref in {None, f"action:{command.action_id}"}
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
    return RemoteDirectApiExecutionResult(
        action_id=str(action.action_id),
        outcome=outcome,
        mode=action.mode,
        receipt_ref=receipt_ref,
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
        },
    )


__all__ = [
    "EventBusDirectApiExecutionClient",
    "RemoteDirectApiExecutionOutcome",
    "RemoteDirectApiExecutionResult",
    "executor_command_id",
]
