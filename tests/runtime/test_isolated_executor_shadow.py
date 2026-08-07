"""Durable no-effect behavior for the isolated Executor shadow consumer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from fdai.runtime.isolated_executor import IsolatedExecutorShadowService
from fdai.shared.contracts import (
    ExecutorCommand,
    ExecutorShadowReceiptStatus,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    ContractValidationError,
    JsonSchemaContractValidator,
)
from fdai.shared.providers.testing import InMemoryStateStore

NOW = datetime(2026, 8, 7, 5, 0, tzinfo=UTC)


def _action(
    *,
    idempotency_key: str = "isolated-executor-action-1",
    mode: Mode = Mode.SHADOW,
    params: dict[str, Any] | None = None,
) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000081"),
        idempotency_key=idempotency_key,
        event_id=UUID("00000000-0000-0000-0000-000000000082"),
        action_type="ops.restart-service",
        target_resource_ref="resource:one",
        operation=Operation.RESTART,
        params=params or {"cooldown_seconds": 30},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback:one"),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE,
            count=1,
            rate_per_minute=1,
        ),
        mode=mode,
        citing_rules=["ops.restart-service"],
        created_at=NOW,
    )


def _command(
    *,
    command_id: int = 83,
    attempt: int = 1,
    action: Action | None = None,
    issued_at: datetime = NOW,
    deadline_at: datetime | None = None,
) -> ExecutorCommand:
    return ExecutorCommand.from_action(
        command_id=UUID(f"00000000-0000-0000-0000-{command_id:012d}"),
        action=action or _action(),
        execution_path=ExecutionPath.DIRECT_API,
        attempt=attempt,
        issued_at=issued_at,
        deadline_at=deadline_at or issued_at + timedelta(minutes=1),
    )


def _service(
    store: InMemoryStateStore,
    *,
    instance: str = "isolated-executor-1",
    now: datetime = NOW,
) -> IsolatedExecutorShadowService:
    return IsolatedExecutorShadowService(
        state_store=store,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id=instance,
        clock=lambda: now,
    )


async def test_shadow_command_persists_terminal_no_effect_receipt() -> None:
    store = InMemoryStateStore()

    receipt = await _service(store).handle(_command())

    assert receipt.status is ExecutorShadowReceiptStatus.SHADOWED
    assert receipt.effect_applied is False
    assert len(await store.read_states("isolated_executor_attempt:", limit=10)) == 1


async def test_exact_replay_and_restart_return_the_same_receipt() -> None:
    store = InMemoryStateStore()
    command = _command()
    first = await _service(store, instance="executor-before-restart").handle(command)

    replay = await _service(store, instance="executor-after-restart").handle(command)

    assert replay == first
    assert len(await store.read_states("isolated_executor_attempt:", limit=10)) == 1
    assert len(await store.read_states("isolated_executor_delivery:", limit=10)) == 0


async def test_duplicate_and_reordered_attempts_are_durable_no_effect_receipts() -> None:
    store = InMemoryStateStore()
    service = _service(store)
    original = await service.handle(_command(command_id=84, attempt=2))

    reordered = await service.handle(_command(command_id=85, attempt=1))
    replayed = await _service(store).handle(_command(command_id=85, attempt=1))

    assert original.status is ExecutorShadowReceiptStatus.SHADOWED
    assert reordered.status is ExecutorShadowReceiptStatus.DUPLICATE
    assert reordered.effect_applied is False
    assert replayed == reordered


async def test_idempotency_payload_conflict_is_rejected_and_replay_stable() -> None:
    store = InMemoryStateStore()
    service = _service(store)
    await service.handle(_command(command_id=86))
    changed = _command(command_id=87, action=_action(params={"cooldown_seconds": 45}))

    rejected = await service.handle(changed)
    replayed = await _service(store).handle(changed)

    assert rejected.status is ExecutorShadowReceiptStatus.REJECTED
    assert rejected.effect_applied is False
    assert replayed == rejected


async def test_enforce_and_expired_commands_close_without_effect() -> None:
    store = InMemoryStateStore()
    service = _service(store)

    enforce = await service.handle(_command(command_id=88, action=_action(mode=Mode.ENFORCE)))
    expired = await service.handle(
        _command(
            command_id=89,
            action=_action(idempotency_key="expired-command"),
            issued_at=NOW - timedelta(minutes=2),
            deadline_at=NOW - timedelta(minutes=1),
        )
    )

    assert enforce.status is ExecutorShadowReceiptStatus.REJECTED
    assert expired.status is ExecutorShadowReceiptStatus.EXPIRED
    assert enforce.effect_applied is expired.effect_applied is False


async def test_invalid_inner_action_is_rejected_before_state_write() -> None:
    store = InMemoryStateStore()
    valid = _command(command_id=90)
    invalid = valid.model_copy(
        update={"action_payload": {**valid.action_payload, "operation": "bad"}}
    )

    with pytest.raises(ContractValidationError):
        await _service(store).handle(invalid)

    assert await store.read_states("isolated_executor_attempt:", limit=10) == ()


async def test_concurrent_duplicate_claims_converge_on_one_receipt() -> None:
    import asyncio

    store = InMemoryStateStore()
    service = _service(store)
    command = _command(command_id=91)

    first, second = await asyncio.gather(service.handle(command), service.handle(command))

    assert first == second
    assert len(await store.read_states("isolated_executor_attempt:", limit=10)) == 1
