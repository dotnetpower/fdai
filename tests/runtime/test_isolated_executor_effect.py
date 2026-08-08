"""SD-08 remote direct-API execution across the isolated process boundary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor
from fdai_executor_service.runtime import (
    EXECUTOR_RECEIPT_TOPIC,
    IsolatedExecutorCommandConsumer,
)
from fdai_executor_service.service import IsolatedExecutorEffectService
from fdai_service_contracts.executor import (
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiOutcome,
    DirectApiReceipt,
    DirectApiRequest,
    ExecutionPath,
    ExecutorCommand,
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    executor_action_payload_digest,
)

from fdai.core.executor import DirectApiExecutionOutcome
from fdai.runtime.isolated_executor_client import (
    EventBusDirectApiExecutionClient,
    executor_command_id,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from fdai.shared.providers.testing import (
    InMemoryEventBus,
    InMemoryStateStore,
    RecordingDirectApiExecutor,
)
from fdai.shared.providers.testing.idempotency import InMemoryIdempotencyStore


class _ResourceLock:
    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        del resource_id
        yield


class _UncontrolledProvider:
    def __init__(self, detail: str) -> None:
        self._detail = detail

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        del request
        raise RuntimeError(self._detail)


class _TypedErrorProvider:
    def __init__(self, error: DirectApiError) -> None:
        self._error = error

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        del request
        raise self._error


class _RecoverableProvider:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.status_calls = 0
        self.applied = False

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        self.execute_calls += 1
        self.applied = True
        return DirectApiReceipt(
            outcome=DirectApiOutcome.SUCCEEDED,
            receipt_ref=f"provider:{request.idempotency_key}",
            detail="provider mutation completed",
        )

    async def operation_status(
        self,
        request: DirectApiRequest,
    ) -> DirectApiReceipt | None:
        self.status_calls += 1
        if not self.applied:
            return None
        return DirectApiReceipt(
            outcome=DirectApiOutcome.ALREADY_APPLIED,
            receipt_ref=f"provider:{request.idempotency_key}",
            detail="durable provider status confirms mutation already applied",
        )


class _FailTerminalAuditOnceStore(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self._fail_terminal = True

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        if entry.get("audit_phase") == "terminal" and self._fail_terminal:
            self._fail_terminal = False
            raise RuntimeError("terminal audit unavailable")
        await super().append_audit_entry(entry)


def _action() -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000801"),
        event_id=UUID("00000000-0000-0000-0000-000000000802"),
        idempotency_key="sd08-effect-one",
        action_type="ops.start-vm",
        target_resource_ref="resource:example/vm-one",
        operation=Operation.RESTART,
        params={"resource_group": "example", "vm_name": "vm-one"},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="stop-vm"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["ops.start-vm"],
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
    )


async def test_remote_effect_is_audited_and_duplicate_safe() -> None:
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    provider = RecordingDirectApiExecutor()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
    )
    service = IsolatedExecutorEffectService(
        direct_api_executor=executor,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-effect-1",
    )
    server = IsolatedExecutorCommandConsumer(
        event_bus=bus,
        service=service,
        retry_seconds=0.01,
    )
    client = EventBusDirectApiExecutionClient(
        event_bus=bus,
        audit_store=audit,
        instance_id="core-one",
        response_timeout_seconds=1.0,
        retry_seconds=0.01,
    )
    server_task = asyncio.create_task(server.run())
    try:
        await client.start()
        first = await client.execute(action=_action())
        duplicate = await client.execute(action=_action())
    finally:
        await client.stop()
        server_task.cancel()
        await asyncio.gather(server_task, return_exceptions=True)

    assert first.outcome.value == DirectApiExecutionOutcome.DISPATCHED.value
    assert duplicate == first
    assert len(provider.records) == 1
    assert (EXECUTOR_RECEIPT_TOPIC, "fdai-isolated-executor-client-core") in bus._offsets
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == [
        "intent",
        "terminal",
    ]


async def test_post_deadline_redelivery_recovers_effect_after_terminal_audit_failure() -> None:
    issued_at = datetime(2026, 8, 8, tzinfo=UTC)
    deadline_at = issued_at + timedelta(seconds=30)
    current_time = [issued_at]
    provider = _RecoverableProvider()
    audit = _FailTerminalAuditOnceStore()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
        clock=lambda: current_time[0],
    )
    service = IsolatedExecutorEffectService(
        direct_api_executor=executor,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-effect-1",
        clock=lambda: current_time[0],
    )
    command = ExecutorCommand.from_action(
        command_id=UUID("00000000-0000-0000-0000-000000000808"),
        action=_action(),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=issued_at,
        deadline_at=deadline_at,
    )

    with pytest.raises(RuntimeError, match="terminal audit unavailable"):
        await service.handle(command)
    current_time[0] = deadline_at + timedelta(seconds=1)

    receipt = await service.handle(command)

    assert receipt.status is ExecutorEffectReceiptStatus.ALREADY_APPLIED
    assert receipt.effect_applied is True
    assert receipt.provider_receipt_ref == "provider:sd08-effect-one"
    assert provider.execute_calls == 1
    assert provider.status_calls == 1
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == [
        "intent",
        "terminal",
    ]


async def test_effect_executor_rejects_missing_safeguard_before_provider() -> None:
    audit = InMemoryStateStore()
    provider = RecordingDirectApiExecutor()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
    )
    action = _action().model_copy(update={"stop_condition": ""})

    result = await executor.execute(action=action)

    assert result.outcome.value == "rejected_invariant"
    assert provider.records == ()
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == ["terminal"]


async def test_effect_executor_rejects_excessive_blast_radius_before_provider() -> None:
    audit = InMemoryStateStore()
    provider = RecordingDirectApiExecutor()
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
    )
    action = _action().model_copy(
        update={
            "blast_radius": BlastRadius(
                scope=BlastRadiusScope.RESOURCE,
                count=11,
            )
        }
    )

    result = await executor.execute(action=action)

    assert result.outcome.value == "abstained_blast_radius"
    assert provider.records == ()
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == ["terminal"]


async def test_uncontrolled_provider_error_is_redacted_before_audit_and_receipt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    leaked_detail = "credential=must-not-escape-" + "x" * 1024
    audit = InMemoryStateStore()
    now = _action().created_at
    executor = ServiceDirectApiEffectExecutor(
        executor=_UncontrolledProvider(leaked_detail),
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
        clock=lambda: now,
    )
    service = IsolatedExecutorEffectService(
        direct_api_executor=executor,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-effect-1",
        clock=lambda: now,
    )
    command = ExecutorCommand.from_action(
        command_id=UUID("00000000-0000-0000-0000-000000000807"),
        action=_action(),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now,
        deadline_at=now + timedelta(minutes=1),
    )

    with caplog.at_level(logging.ERROR, logger="fdai.isolated_executor.effect"):
        receipt = await service.handle(command)

    terminal = audit.audit_entries[-1]["entry"]
    assert receipt.status is ExecutorEffectReceiptStatus.FAILED
    assert receipt.reason == "provider failed with an uncontrolled error"
    assert terminal["reason"] == receipt.reason
    assert len(receipt.reason) <= 512
    assert leaked_detail not in caplog.text
    assert leaked_detail not in str(terminal)
    assert leaked_detail not in receipt.model_dump_json()


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_reason"),
    [
        (
            DirectApiAuthenticationError("credential=must-not-escape"),
            ExecutorEffectReceiptStatus.AUTHENTICATION_FAILED,
            "provider authentication failed",
        ),
        (
            DirectApiError("token=classified-secret", "credential=must-not-escape"),
            ExecutorEffectReceiptStatus.FAILED,
            "provider failed with a classified adapter error",
        ),
    ],
)
async def test_typed_provider_error_is_sanitized_before_audit_log_and_receipt(
    error: DirectApiError,
    expected_status: ExecutorEffectReceiptStatus,
    expected_reason: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    audit = InMemoryStateStore()
    now = _action().created_at
    executor = ServiceDirectApiEffectExecutor(
        executor=_TypedErrorProvider(error),
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
        clock=lambda: now,
    )
    service = IsolatedExecutorEffectService(
        direct_api_executor=executor,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-effect-1",
        clock=lambda: now,
    )
    command = ExecutorCommand.from_action(
        command_id=UUID("00000000-0000-0000-0000-000000000809"),
        action=_action(),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=now,
        deadline_at=now + timedelta(minutes=1),
    )

    with caplog.at_level(logging.WARNING, logger="fdai.isolated_executor.effect"):
        receipt = await service.handle(command)

    terminal = audit.audit_entries[-1]["entry"]
    serialized = f"{caplog.text}\n{terminal!r}\n{receipt.model_dump_json()}"
    assert receipt.status is expected_status
    assert receipt.reason == expected_reason
    assert terminal["reason"] == expected_reason
    assert "must-not-escape" not in serialized
    assert "classified-secret" not in serialized


async def test_effect_command_expired_while_waiting_never_reaches_provider() -> None:
    audit = InMemoryStateStore()
    provider = RecordingDirectApiExecutor()
    issued_at = datetime(2026, 8, 8, tzinfo=UTC)
    deadline_at = issued_at + timedelta(seconds=30)
    executor = ServiceDirectApiEffectExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=_ResourceLock(),
        idempotency=InMemoryIdempotencyStore(),
        allow_enforce=True,
        clock=lambda: deadline_at + timedelta(microseconds=1),
    )
    service = IsolatedExecutorEffectService(
        direct_api_executor=executor,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-effect-1",
        clock=lambda: issued_at,
    )
    command = ExecutorCommand.from_action(
        command_id=UUID("00000000-0000-0000-0000-000000000803"),
        action=_action(),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=issued_at,
        deadline_at=deadline_at,
    )

    receipt = await service.handle(command)

    assert receipt.status.value == "expired"
    assert receipt.effect_applied is False
    assert provider.records == ()
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == ["terminal"]


async def test_core_client_rejects_receipt_rebound_to_another_action() -> None:
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    action = _action()
    client = EventBusDirectApiExecutionClient(
        event_bus=bus,
        audit_store=audit,
        instance_id="core-one",
        response_timeout_seconds=1.0,
        retry_seconds=0.01,
    )
    task = asyncio.create_task(client.execute(action=action))
    for _attempt in range(20):
        if client._pending:
            break
        await asyncio.sleep(0)
    assert client._pending
    now = datetime.now(tz=UTC)
    command_id = executor_command_id(action)
    forged = ExecutorEffectReceipt(
        receipt_id=UUID("00000000-0000-0000-0000-000000000804"),
        command_id=command_id,
        action_id=UUID("00000000-0000-0000-0000-000000000805"),
        idempotency_key=action.idempotency_key,
        attempt=1,
        action_payload_digest="sha256:" + "0" * 64,
        requested_mode=action.mode,
        status=ExecutorEffectReceiptStatus.DISPATCHED,
        executor_instance_id="isolated-executor-effect-1",
        received_at=now,
        completed_at=now,
        effect_applied=True,
        provider_receipt_ref="provider:forged",
        audit_ref="action:forged",
    )
    await bus.publish(
        EXECUTOR_RECEIPT_TOPIC,
        action.target_resource_ref,
        forged.model_dump(mode="json"),
    )
    await asyncio.sleep(0.01)
    assert task.done() is False

    payload = action.model_dump(mode="json", exclude_none=True)
    valid = forged.model_copy(
        update={
            "receipt_id": UUID("00000000-0000-0000-0000-000000000806"),
            "action_id": action.action_id,
            "action_payload_digest": executor_action_payload_digest(payload),
            "provider_receipt_ref": "provider:valid",
            "audit_ref": f"action:{action.action_id}",
        }
    )
    await bus.publish(
        EXECUTOR_RECEIPT_TOPIC,
        action.target_resource_ref,
        valid.model_dump(mode="json"),
    )
    try:
        result = await task
    finally:
        await client.stop()

    assert result.outcome.value == "dispatched"
    assert result.receipt_ref == "provider:valid"
