"""SD-08 remote direct-API execution across the isolated process boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fdai.core.executor import DirectApiExecutionOutcome, DirectApiShadowExecutor
from fdai.core.executor.lock import ResourceLockManager
from fdai.runtime.isolated_executor import IsolatedExecutorEffectService
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.isolated_executor_runtime import (
    EXECUTOR_RECEIPT_TOPIC,
    IsolatedExecutorCommandConsumer,
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
    executor = DirectApiShadowExecutor(
        executor=provider,
        audit_store=audit,
        resource_lock=ResourceLockManager(),
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

    assert first.outcome is DirectApiExecutionOutcome.DISPATCHED
    assert duplicate == first
    assert len(provider.records) == 1
    assert (EXECUTOR_RECEIPT_TOPIC, "fdai-isolated-executor-client-core") in bus._offsets
    assert [row["entry"]["audit_phase"] for row in audit.audit_entries] == [
        "intent",
        "terminal",
    ]
