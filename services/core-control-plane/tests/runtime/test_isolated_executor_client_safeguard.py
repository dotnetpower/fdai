"""Core-to-isolated-Executor safeguard-bound command tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.shared.contracts.models import (
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    Mode,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC, EXECUTOR_RECEIPT_TOPIC
from tests.core.executor.test_direct_api_executor import _action

_BUNDLE_DIGEST = "sha256:" + "b" * 64
_SOURCE_REVISION = "commit:" + "c" * 40


async def test_client_publishes_safeguard_bound_command_and_retains_digest() -> None:
    bus = InMemoryEventBus()
    client = EventBusDirectApiExecutionClient(
        event_bus=bus,
        audit_store=InMemoryStateStore(),
        instance_id="core-1",
        response_timeout_seconds=2,
        retry_seconds=0.001,
    )
    action = _action(mode=Mode.ENFORCE)
    pending = asyncio.create_task(
        client.execute_bound(
            action=action,
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            source_revision=_SOURCE_REVISION,
            attempt=2,
        )
    )
    command_envelope = None
    for _ in range(20):
        commands = [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-reader")]
        if commands:
            command_envelope = commands[0]
            break
        await asyncio.sleep(0.001)
    assert command_envelope is not None
    command = SafeguardBoundExecutorCommand.model_validate(command_envelope.payload)
    assert command.safeguard_proof_bundle_digest == _BUNDLE_DIGEST
    assert command.source_revision == _SOURCE_REVISION
    assert command.attempt == 2

    now = datetime.now(UTC)
    await bus.publish(
        EXECUTOR_RECEIPT_TOPIC,
        command.partition_key,
        ExecutorEffectReceipt(
            receipt_id=UUID(int=99),
            command_id=command.command_id,
            action_id=command.action_id,
            idempotency_key=command.idempotency_key,
            attempt=command.attempt,
            action_payload_digest=command.action_payload_digest,
            requested_mode=command.requested_mode,
            status=ExecutorEffectReceiptStatus.DISPATCHED,
            executor_instance_id="executor-1",
            received_at=now,
            completed_at=now,
            effect_applied=True,
            provider_receipt_ref="provider:1",
            safeguard_proof_bundle_digest=_BUNDLE_DIGEST,
            audit_ref=f"action:{command.action_id}",
        ).model_dump(mode="json"),
    )

    result = await pending
    await client.stop()
    assert result.safeguard_bundle_digest == _BUNDLE_DIGEST
    assert result.receipt_ref == "provider:1"
