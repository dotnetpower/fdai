"""Correlated Core client for the isolated Executor direct-API boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai_service_contracts import (
    CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP,
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_RECEIPT_TOPIC,
)
from pydantic import ValidationError

from fdai.shared.contracts import ExecutorCommand, ExecutorEffectReceipt
from fdai.shared.contracts.models import Action, ExecutionPath, Mode
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore


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
    _pending: dict[str, asyncio.Future[ExecutorEffectReceipt]] = field(default_factory=dict)

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
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def execute(self, *, action: Action) -> RemoteDirectApiExecutionResult:
        """Dispatch one Action, failing closed when transport closure is unavailable."""

        await self.start()
        if len(self._pending) >= self.max_pending_requests:
            return await self._transport_failure(action, "executor command capacity exceeded")
        command_id = executor_command_id(action)
        key = str(command_id)
        existing = self._pending.get(key)
        owner = existing is None
        future = existing or asyncio.get_running_loop().create_future()
        if owner:
            self._pending[key] = future
            now = datetime.now(UTC)
            command = ExecutorCommand.from_action(
                command_id=command_id,
                action=action,
                execution_path=ExecutionPath.DIRECT_API,
                attempt=1,
                issued_at=now,
                deadline_at=now + timedelta(seconds=self.response_timeout_seconds),
            )
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
        try:
            receipt = await asyncio.wait_for(
                asyncio.shield(future),
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
            async for envelope in self.event_bus.subscribe(EXECUTOR_RECEIPT_TOPIC, group_id):
                try:
                    receipt = ExecutorEffectReceipt.model_validate(envelope.payload)
                except ValidationError:
                    continue
                future = self._pending.get(str(receipt.command_id))
                if future is not None and not future.done():
                    future.set_result(receipt)
            await asyncio.sleep(self.retry_seconds)


def executor_command_id(action: Action) -> UUID:
    payload = json.dumps(
        action.model_dump(mode="json", exclude_none=True),
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return uuid5(NAMESPACE_URL, f"fdai:executor-command:{action.idempotency_key}:{digest}")


def _result_from_receipt(
    action: Action,
    receipt: ExecutorEffectReceipt,
) -> RemoteDirectApiExecutionResult:
    return RemoteDirectApiExecutionResult(
        action_id=str(action.action_id),
        outcome=RemoteDirectApiExecutionOutcome(receipt.status.value),
        mode=action.mode,
        receipt_ref=receipt.provider_receipt_ref,
        rollback_succeeded=receipt.rollback_succeeded,
        reason=receipt.reason,
        audit_context={
            "resource_ref": action.target_resource_ref,
            "action_type": action.action_type,
            "executor_receipt_ref": str(receipt.receipt_id),
            "effect_applied": receipt.effect_applied,
            "effect_verified": receipt.effect_verified,
            "audit_ref": receipt.audit_ref,
        },
    )


__all__ = [
    "EventBusDirectApiExecutionClient",
    "RemoteDirectApiExecutionOutcome",
    "RemoteDirectApiExecutionResult",
    "executor_command_id",
]
