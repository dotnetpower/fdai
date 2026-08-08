"""Durable shadow consumer for the isolated Executor process boundary.

Responsibility: validate one Executor command and persist one terminal shadow
receipt with its audit evidence.
Boundary: this module consumes versioned wire records and never imports or
invokes a Core executor, provider mutation adapter, or agent implementation.
Authority and state: all SD-07 outcomes have ``effect_applied=false``. The
injected StateStore owns durable idempotency and atomic audit persistence.
Dependencies: shared contracts, ContractValidator, StateStore, and an injected
clock only.
Deployment: this service is independently runnable composition material, but
this module does not create ingress, identity, or a Container App.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.executor import (
    Action,
    DirectApiExecutionResultLike,
    ExecutionPath,
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    ExecutorShadowReceipt,
    ExecutorShadowReceiptStatus,
    Mode,
)
from fdai_service_contracts.schema import ContractValidator

from fdai_executor_service.ports import ExecutorStateStore

_ATTEMPT_PREFIX = "isolated-executor:attempt:"
_DELIVERY_PREFIX = "isolated-executor:delivery:"
_LEGACY_ATTEMPT_PREFIX = "isolated_executor_attempt:"
_LEGACY_DELIVERY_PREFIX = "isolated_executor_delivery:"


class ExecutorCommandConflictError(RuntimeError):
    """A command identity was rebound to a different immutable envelope."""


class DirectApiCommandExecutor(Protocol):
    """Direct-API surface already enforcing the seven action safeguards."""

    async def execute(
        self,
        *,
        action: Action,
        deadline_at: datetime,
    ) -> DirectApiExecutionResultLike: ...


class IsolatedExecutorEffectService:
    """Validate a command and dispatch it through the governed direct-API executor."""

    def __init__(
        self,
        *,
        direct_api_executor: DirectApiCommandExecutor,
        contract_validator: ContractValidator,
        executor_instance_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not executor_instance_id or len(executor_instance_id) > 512:
            raise ValueError("executor instance id MUST be bounded and non-empty")
        self._direct_api_executor = direct_api_executor
        self._contract_validator = contract_validator
        self._executor_instance_id = executor_instance_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, command: ExecutorCommand) -> ExecutorEffectReceipt:
        """Dispatch one command without claiming independent effect verification."""

        self._contract_validator.validate(
            "executor-command",
            command.model_dump(mode="json"),
            version=command.schema_version,
        )
        self._contract_validator.validate(
            "action",
            command.action_payload,
            version=command.action_schema_version,
        )
        received_at = self._clock()
        if received_at.tzinfo is None:
            raise ValueError("isolated Executor clock MUST be timezone-aware")
        if received_at > command.deadline_at:
            return self._effect_receipt(
                command,
                status=ExecutorEffectReceiptStatus.EXPIRED,
                reason="command deadline expired before dispatch",
                received_at=received_at,
                completed_at=received_at,
            )
        if command.execution_path is not ExecutionPath.DIRECT_API:
            return self._effect_receipt(
                command,
                status=ExecutorEffectReceiptStatus.REJECTED_INVARIANT,
                reason="isolated effect authority supports direct_api commands only",
                received_at=received_at,
                completed_at=received_at,
            )

        action = Action.model_validate(command.action_payload)
        result = await self._direct_api_executor.execute(
            action=action,
            deadline_at=command.deadline_at,
        )
        completed_at = self._clock()
        status = ExecutorEffectReceiptStatus(result.outcome.value)
        effect_applied = result.outcome.value in {"dispatched", "already_applied"}
        return self._effect_receipt(
            command,
            status=status,
            reason=result.reason,
            received_at=received_at,
            completed_at=completed_at,
            effect_applied=effect_applied,
            rollback_succeeded=result.rollback_succeeded,
            provider_receipt_ref=result.receipt_ref,
        )

    def _effect_receipt(
        self,
        command: ExecutorCommand,
        *,
        status: ExecutorEffectReceiptStatus,
        reason: str | None,
        received_at: datetime,
        completed_at: datetime,
        effect_applied: bool = False,
        rollback_succeeded: bool | None = None,
        provider_receipt_ref: str | None = None,
    ) -> ExecutorEffectReceipt:
        receipt_id = uuid5(
            NAMESPACE_URL,
            f"fdai:isolated-executor-effect:{command.command_id}:{status.value}",
        )
        receipt = ExecutorEffectReceipt(
            receipt_id=receipt_id,
            command_id=command.command_id,
            action_id=command.action_id,
            idempotency_key=command.idempotency_key,
            attempt=command.attempt,
            action_payload_digest=command.action_payload_digest,
            requested_mode=command.requested_mode,
            status=status,
            reason=_bounded_optional(reason),
            executor_instance_id=self._executor_instance_id,
            received_at=received_at,
            completed_at=completed_at,
            effect_applied=effect_applied,
            rollback_succeeded=rollback_succeeded,
            provider_receipt_ref=_bounded_optional(provider_receipt_ref),
            audit_ref=f"action:{command.action_id}",
        )
        self._contract_validator.validate(
            "executor-receipt",
            receipt.model_dump(mode="json"),
            version=receipt.schema_version,
        )
        return receipt


class IsolatedExecutorShadowService:
    """Validate and durably record commands without applying any effect."""

    def __init__(
        self,
        *,
        state_store: ExecutorStateStore,
        contract_validator: ContractValidator,
        executor_instance_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not executor_instance_id or len(executor_instance_id) > 512:
            raise ValueError("executor instance id MUST be bounded and non-empty")
        self._state_store = state_store
        self._contract_validator = contract_validator
        self._executor_instance_id = executor_instance_id
        self._clock = clock or (lambda: datetime.now(UTC))

    async def handle(self, command: ExecutorCommand) -> ExecutorShadowReceipt:
        """Return one durable no-effect receipt for a validated command."""

        self._contract_validator.validate(
            "executor-command",
            command.model_dump(mode="json"),
            version=command.schema_version,
        )
        self._contract_validator.validate(
            "action",
            command.action_payload,
            version=command.action_schema_version,
        )
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("isolated Executor clock MUST be timezone-aware")

        attempt_key = _attempt_key(command.idempotency_key)
        legacy_attempt_key = _legacy_attempt_key(command.idempotency_key)
        existing = await _read_compatible_state(
            self._state_store,
            attempt_key,
            legacy_attempt_key,
        )
        if existing is not None:
            return await self._resolve_existing(command, existing, now=now)

        status, reason = _first_terminal_outcome(command, now=now)
        receipt = self._receipt(command, status=status, reason=reason, now=now)
        created = await self._state_store.write_state_with_audit_if_absent(
            attempt_key,
            _state_record(command, receipt),
            _audit_entry(command, receipt),
        )
        if created:
            return receipt
        winner = await _read_compatible_state(
            self._state_store,
            attempt_key,
            legacy_attempt_key,
        )
        if winner is None:
            raise RuntimeError("isolated Executor attempt disappeared after atomic claim")
        return await self._resolve_existing(command, winner, now=now)

    async def _resolve_existing(
        self,
        command: ExecutorCommand,
        raw: Mapping[str, Any],
        *,
        now: datetime,
    ) -> ExecutorShadowReceipt:
        stored_command, stored_receipt = _decode_state_record(raw)
        if stored_command == command:
            return stored_receipt
        if _same_action_intent(stored_command, command):
            return await self._persist_secondary(
                command,
                status=ExecutorShadowReceiptStatus.DUPLICATE,
                reason="duplicate or reordered command matched a terminal shadow attempt",
                now=now,
            )
        return await self._persist_secondary(
            command,
            status=ExecutorShadowReceiptStatus.REJECTED,
            reason="idempotency key is bound to a different Executor command",
            now=now,
        )

    async def _persist_secondary(
        self,
        command: ExecutorCommand,
        *,
        status: ExecutorShadowReceiptStatus,
        reason: str,
        now: datetime,
    ) -> ExecutorShadowReceipt:
        receipt = self._receipt(command, status=status, reason=reason, now=now)
        key = _delivery_key(command.idempotency_key, str(command.command_id))
        legacy_key = _legacy_delivery_key(command.idempotency_key, str(command.command_id))
        existing = await _read_compatible_state(self._state_store, key, legacy_key)
        if existing is not None:
            stored_command, stored_receipt = _decode_state_record(existing)
            if stored_command != command:
                raise ExecutorCommandConflictError(
                    "Executor command id is bound to another immutable envelope"
                )
            return stored_receipt
        created = await self._state_store.write_state_with_audit_if_absent(
            key,
            _state_record(command, receipt),
            _audit_entry(command, receipt),
        )
        if created:
            return receipt
        existing = await _read_compatible_state(self._state_store, key, legacy_key)
        if existing is None:
            raise RuntimeError("isolated Executor delivery disappeared after atomic claim")
        stored_command, stored_receipt = _decode_state_record(existing)
        if stored_command != command:
            raise ExecutorCommandConflictError(
                "Executor command id is bound to another immutable envelope"
            )
        return stored_receipt

    def _receipt(
        self,
        command: ExecutorCommand,
        *,
        status: ExecutorShadowReceiptStatus,
        reason: str,
        now: datetime,
    ) -> ExecutorShadowReceipt:
        receipt_id = uuid5(
            NAMESPACE_URL,
            "fdai:isolated-executor:"
            f"{command.command_id}:{command.action_payload_digest}:{status.value}",
        )
        return ExecutorShadowReceipt(
            receipt_id=receipt_id,
            command_id=command.command_id,
            action_id=command.action_id,
            idempotency_key=command.idempotency_key,
            attempt=command.attempt,
            action_payload_digest=command.action_payload_digest,
            requested_mode=command.requested_mode,
            status=status,
            reason=reason,
            executor_instance_id=self._executor_instance_id,
            received_at=now,
            completed_at=now,
            effect_applied=False,
            audit_ref=f"isolated-executor:{receipt_id}",
        )


def _first_terminal_outcome(
    command: ExecutorCommand,
    *,
    now: datetime,
) -> tuple[ExecutorShadowReceiptStatus, str]:
    if now > command.deadline_at:
        return ExecutorShadowReceiptStatus.EXPIRED, "command deadline expired before observation"
    if command.requested_mode is Mode.ENFORCE:
        return (
            ExecutorShadowReceiptStatus.REJECTED,
            "effect authority is not available before SD-08",
        )
    return ExecutorShadowReceiptStatus.SHADOWED, "shadow command recorded without dispatch"


def _same_action_intent(left: ExecutorCommand, right: ExecutorCommand) -> bool:
    return (
        left.action_id == right.action_id
        and left.event_id == right.event_id
        and left.idempotency_key == right.idempotency_key
        and left.target_resource_ref == right.target_resource_ref
        and left.execution_path is right.execution_path
        and left.requested_mode is right.requested_mode
        and left.action_payload_digest == right.action_payload_digest
    )


def _state_record(
    command: ExecutorCommand,
    receipt: ExecutorShadowReceipt,
) -> Mapping[str, Any]:
    return {
        "revision": 1,
        "command": command.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
    }


def _decode_state_record(
    raw: Mapping[str, Any],
) -> tuple[ExecutorCommand, ExecutorShadowReceipt]:
    command = raw.get("command")
    receipt = raw.get("receipt")
    if not isinstance(command, Mapping) or not isinstance(receipt, Mapping):
        raise RuntimeError("isolated Executor durable attempt record is malformed")
    return (
        ExecutorCommand.model_validate(dict(command)),
        ExecutorShadowReceipt.model_validate(dict(receipt)),
    )


def _audit_entry(
    command: ExecutorCommand,
    receipt: ExecutorShadowReceipt,
) -> Mapping[str, Any]:
    return {
        "kind": "isolated_executor.shadow_terminal",
        "idempotency_key": f"isolated-executor:{receipt.receipt_id}",
        "command_id": str(command.command_id),
        "action_id": str(command.action_id),
        "action_payload_digest": command.action_payload_digest,
        "attempt": command.attempt,
        "mode": command.requested_mode.value,
        "status": receipt.status.value,
        "effect_applied": False,
        "audit_ref": receipt.audit_ref,
        "timestamp": receipt.completed_at.isoformat(),
    }


def _attempt_key(idempotency_key: str) -> str:
    return _ATTEMPT_PREFIX + hashlib.sha256(idempotency_key.encode()).hexdigest()


def _legacy_attempt_key(idempotency_key: str) -> str:
    return _LEGACY_ATTEMPT_PREFIX + hashlib.sha256(idempotency_key.encode()).hexdigest()


def _delivery_key(idempotency_key: str, command_id: str) -> str:
    identity = f"{idempotency_key}\x00{command_id}".encode()
    return _DELIVERY_PREFIX + hashlib.sha256(identity).hexdigest()


def _legacy_delivery_key(idempotency_key: str, command_id: str) -> str:
    identity = f"{idempotency_key}\x00{command_id}".encode()
    return _LEGACY_DELIVERY_PREFIX + hashlib.sha256(identity).hexdigest()


async def _read_compatible_state(
    state_store: ExecutorStateStore,
    canonical_key: str,
    legacy_key: str,
) -> Mapping[str, Any] | None:
    current = await state_store.read_state(canonical_key)
    if current is not None:
        return current
    return await state_store.read_state(legacy_key)


def _bounded_optional(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:512] or None


__all__ = [
    "ExecutorCommandConflictError",
    "IsolatedExecutorEffectService",
    "IsolatedExecutorShadowService",
]
