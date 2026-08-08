"""SD-08 remote direct-API execution across the isolated process boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fdai_executor_service.effect_executor import ServiceDirectApiEffectExecutor
from fdai_executor_service.runtime import (
    EXECUTOR_RECEIPT_TOPIC,
    IsolatedExecutorCommandConsumer,
)
from fdai_executor_service.service import IsolatedExecutorEffectService
from fdai_service_contracts.executor import ExecutionPath, ExecutorCommand

from fdai.core.executor import DirectApiExecutionOutcome
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
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
