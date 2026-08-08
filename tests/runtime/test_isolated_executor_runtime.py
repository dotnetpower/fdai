"""Event-bus and process lifecycle tests for the isolated Executor."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import fdai_executor_service.runtime as runtime_module
import pytest
from fdai_executor_service.runtime import (
    EXECUTOR_COMMAND_TOPIC,
    EXECUTOR_RECEIPT_TOPIC,
    IsolatedExecutorCommandConsumer,
    IsolatedExecutorSupervisor,
)
from fdai_executor_service.service import IsolatedExecutorShadowService

from fdai.shared.contracts import ExecutorCommand, executor_action_payload_digest
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
from fdai.shared.contracts.validation import JsonSchemaContractValidator
from fdai.shared.providers.event_bus import EventEnvelope, PublishReceipt
from fdai.shared.providers.testing import InMemoryEventBus, InMemoryStateStore

NOW = datetime(2026, 8, 7, 6, 0, tzinfo=UTC)


def _command() -> ExecutorCommand:
    action = Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000101"),
        idempotency_key="isolated-executor-runtime-1",
        event_id=UUID("00000000-0000-0000-0000-000000000102"),
        action_type="ops.restart-service",
        target_resource_ref="resource:one",
        operation=Operation.RESTART,
        params={"cooldown_seconds": 30},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(
            kind=RollbackKind.SCRIPTED,
            reference="rollback:one",
        ),
        blast_radius=BlastRadius(
            scope=BlastRadiusScope.RESOURCE,
            count=1,
            rate_per_minute=1,
        ),
        mode=Mode.SHADOW,
        citing_rules=["ops.restart-service"],
        created_at=NOW,
    )
    return ExecutorCommand.from_action(
        command_id=UUID("00000000-0000-0000-0000-000000000103"),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=NOW,
        deadline_at=NOW + timedelta(minutes=1),
    )


def _service(store: InMemoryStateStore) -> IsolatedExecutorShadowService:
    return IsolatedExecutorShadowService(
        state_store=store,
        contract_validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        executor_instance_id="isolated-executor-runtime-1",
        clock=lambda: NOW,
    )


def _envelope(command: ExecutorCommand, *, key: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        topic=EXECUTOR_COMMAND_TOPIC,
        key=key or command.partition_key,
        payload=command.model_dump(mode="json"),
        offset=0,
    )


async def _records(bus: InMemoryEventBus, topic: str) -> tuple[EventEnvelope, ...]:
    return tuple([record async for record in bus.subscribe(topic, f"observer:{topic}")])


async def test_consumer_publishes_terminal_shadow_receipt() -> None:
    bus = InMemoryEventBus()
    command = _command()
    consumer = IsolatedExecutorCommandConsumer(
        event_bus=bus, service=_service(InMemoryStateStore())
    )

    receipt = await consumer.handle_envelope(_envelope(command))
    assert await consumer._drain_once() == 1

    published = await _records(bus, EXECUTOR_RECEIPT_TOPIC)
    assert receipt is not None and receipt.effect_applied is False
    assert len(published) == 1
    assert published[0].key == command.partition_key
    assert published[0].payload["receipt_id"] == str(receipt.receipt_id)


@pytest.mark.parametrize(
    ("envelope_factory", "reason"),
    [
        (
            lambda command: _envelope(command, key="resource:other"),
            "executor_partition_key_mismatch",
        ),
        (
            lambda command: _envelope(
                command.model_copy(
                    update={
                        "action_payload": {
                            **command.action_payload,
                            "operation": "invalid",
                        },
                        "action_payload_digest": executor_action_payload_digest(
                            {**command.action_payload, "operation": "invalid"}
                        ),
                    }
                )
            ),
            "invalid_executor_action_payload",
        ),
    ],
)
async def test_consumer_dead_letters_immutable_poison_records(
    envelope_factory: Callable[[ExecutorCommand], EventEnvelope],
    reason: str,
) -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    consumer = IsolatedExecutorCommandConsumer(event_bus=bus, service=_service(store))

    receipt = await consumer.handle_envelope(envelope_factory(_command()))

    dead_letters = await _records(bus, f"{EXECUTOR_COMMAND_TOPIC}.dlq")
    assert receipt is None
    assert dead_letters[0].payload["reason"] == reason
    assert await store.read_states("isolated-executor:attempt:", limit=10) == ()


class _FailOnceReceiptBus(InMemoryEventBus):
    def __init__(self) -> None:
        super().__init__()
        self._fail_receipt = True

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic == EXECUTOR_RECEIPT_TOPIC and self._fail_receipt:
            self._fail_receipt = False
            raise RuntimeError("receipt transport unavailable")
        return await super().publish(topic, key, payload)


async def test_receipt_publish_retry_does_not_change_durable_command_result(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="fdai.isolated_executor")
    bus = _FailOnceReceiptBus()
    store = InMemoryStateStore()
    command = _command()
    consumer = IsolatedExecutorCommandConsumer(event_bus=bus, service=_service(store))

    receipt = await consumer.handle_envelope(_envelope(command))
    assert any("isolated_executor_receipt_committed" in row.message for row in caplog.records)
    assert not any("isolated_executor_receipt_published" in row.message for row in caplog.records)
    with pytest.raises(RuntimeError, match="transport unavailable"):
        await consumer._drain_once()
    assert not any("isolated_executor_receipt_published" in row.message for row in caplog.records)
    assert await consumer._drain_once() == 1
    assert sum("isolated_executor_receipt_published" in row.message for row in caplog.records) == 1

    published = await _records(bus, EXECUTOR_RECEIPT_TOPIC)
    assert receipt is not None and len(published) == 1
    assert published[0].payload["receipt_id"] == str(receipt.receipt_id)
    assert len(await store.read_states("isolated-executor:attempt:", limit=10)) == 1


class _ConsumerLoop:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.failure = failure
        self.cancelled = False

    async def run(self) -> None:
        self.started.set()
        try:
            await self.release.wait()
            if self.failure is not None:
                raise self.failure
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@dataclass
class _Health:
    port: int
    readiness: Callable[[], bool]
    started: bool = False
    closed: bool = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


async def test_supervisor_exposes_health_and_drains_on_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health: _Health | None = None

    def health_factory(*, port: int, readiness: Callable[[], bool]) -> _Health:
        nonlocal health
        health = _Health(port=port, readiness=readiness)
        return health

    monkeypatch.setattr(runtime_module, "RuntimeHealthServer", health_factory)
    consumer = _ConsumerLoop()
    closed = False

    async def close() -> None:
        nonlocal closed
        closed = True

    stop = asyncio.Event()
    supervisor = IsolatedExecutorSupervisor(
        consumer=consumer,
        health_port=8000,
        shutdown_callbacks=(close,),
    )
    task = asyncio.create_task(supervisor.run(stop=stop))
    await consumer.started.wait()

    assert supervisor.ready is True
    assert health is not None and health.started and health.readiness()
    stop.set()
    assert await task == 0
    assert supervisor.ready is False
    assert health.closed and not health.readiness()
    assert consumer.cancelled is True
    assert closed is True


async def test_supervisor_fails_closed_when_consumer_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "RuntimeHealthServer", _Health)
    consumer = _ConsumerLoop(failure=RuntimeError("broker unavailable"))
    supervisor = IsolatedExecutorSupervisor(
        consumer=consumer,
        health_port=8000,
    )
    task = asyncio.create_task(supervisor.run(stop=asyncio.Event()))
    await consumer.started.wait()
    consumer.release.set()

    with pytest.raises(RuntimeError, match="runtime failed"):
        await task
    assert supervisor.ready is False


async def test_supervisor_readiness_requires_broker_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "RuntimeHealthServer", _Health)
    consumer = _ConsumerLoop()
    broker_owned = False
    supervisor = IsolatedExecutorSupervisor(
        consumer=consumer,
        health_port=8000,
        readiness_checks=(lambda: broker_owned,),
    )
    stop = asyncio.Event()
    task = asyncio.create_task(supervisor.run(stop=stop))
    await consumer.started.wait()

    assert supervisor.ready is False
    broker_owned = True
    assert supervisor.ready is True
    stop.set()
    assert await task == 0


def test_supervisor_rejects_invalid_health_port() -> None:
    with pytest.raises(ValueError, match="health port"):
        IsolatedExecutorSupervisor(consumer=_ConsumerLoop(), health_port=0)
