"""Core-to-isolated-Executor safeguard-bound command tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.shared.contracts.models import (
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    Mode,
    SafeguardBoundExecutorCommand,
    WorkflowActionRef,
)
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError, PublishReceipt
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC, EXECUTOR_RECEIPT_TOPIC
from tests.core.executor.test_direct_api_executor import _action

_BUNDLE_DIGEST = "sha256:" + "b" * 64
_SOURCE_REVISION = "commit:" + "c" * 40


class _CancellingPublishBus(InMemoryEventBus):
    """Cancel while publishing so the pending request must be released."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        del topic, key, payload
        raise asyncio.CancelledError


class _UnknownPublishBus(InMemoryEventBus):
    """Fail after entering a transport whose publication result is unknown."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        del topic, key, payload
        raise OSError("synthetic ambiguous transport failure")


class _NotAttemptedPublishBus(InMemoryEventBus):
    """Prove the broker call was not attempted."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        del topic, key, payload
        raise EventPublishNotAttemptedError("synthetic no-publication result")


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
            receipt_id=UUID(int=98),
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
            provider_receipt_ref="provider:wrong",
            safeguard_proof_bundle_digest="sha256:" + "d" * 64,
            audit_ref=f"action:{command.action_id}",
        ).model_dump(mode="json"),
    )
    await asyncio.sleep(0.01)
    assert not pending.done()
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


async def test_bound_client_checks_capacity_before_pre_publish_guard() -> None:
    bus = InMemoryEventBus()
    audit = InMemoryStateStore()
    client = EventBusDirectApiExecutionClient(
        event_bus=bus,
        audit_store=audit,
        instance_id="core-capacity",
        max_pending_requests=0,
    )
    guard_called = False

    async def guard() -> datetime:
        nonlocal guard_called
        guard_called = True
        return datetime.now(UTC)

    action = _action(mode=Mode.ENFORCE).model_copy(
        update={
            "workflow_action": WorkflowActionRef(
                process_id="process-remote-001",
                step_id="restart",
                proposal_ref="proposal:remote:001",
                attempt=4,
            )
        }
    )
    result = await client.execute_bound(
        action=action,
        safeguard_bundle_digest=_BUNDLE_DIGEST,
        source_revision=_SOURCE_REVISION,
        attempt=1,
        pre_publish_guard=guard,
    )
    commands = [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "capacity-reader")]
    await client.stop()

    assert result.outcome.value == "dispatch_not_attempted"
    assert guard_called is False
    assert commands == []
    assert audit.audit_entries[-1]["entry"]["workflow_action"]["attempt"] == 4


async def test_legacy_receipt_timeout_remains_pending_not_failed() -> None:
    store = InMemoryStateStore()
    client = EventBusDirectApiExecutionClient(
        event_bus=InMemoryEventBus(),
        audit_store=store,
        instance_id="core-timeout",
        response_timeout_seconds=0.01,
        retry_seconds=0.001,
    )

    result = await client.execute(action=_action(mode=Mode.SHADOW))
    await client.stop()

    assert result.outcome.value == "receipt_timeout"
    assert result.audit_context["effect_possible"] is True
    assert result.audit_context["reconciliation_required"] is True
    assert store.audit_entries[-1]["entry"]["audit_phase"] == "post_release"


@pytest.mark.parametrize(
    ("bus", "expected"),
    [
        (_NotAttemptedPublishBus(), "dispatch_not_attempted"),
        (_UnknownPublishBus(), "execution_unknown"),
    ],
)
async def test_legacy_publication_failure_preserves_effect_uncertainty(
    bus: InMemoryEventBus,
    expected: str,
) -> None:
    client = EventBusDirectApiExecutionClient(
        event_bus=bus,
        audit_store=InMemoryStateStore(),
        instance_id=f"core-{expected}",
        response_timeout_seconds=0.1,
        retry_seconds=0.001,
    )

    result = await client.execute(action=_action(mode=Mode.SHADOW))
    await client.stop()

    assert result.outcome.value == expected
    assert result.audit_context["effect_possible"] is (expected == "execution_unknown")


async def test_cancelled_publish_releases_the_pending_request() -> None:
    client = EventBusDirectApiExecutionClient(
        event_bus=_CancellingPublishBus(),
        audit_store=InMemoryStateStore(),
        instance_id="core-cancelled-publish",
    )

    with pytest.raises(asyncio.CancelledError):
        await client.execute_bound(
            action=_action(mode=Mode.ENFORCE),
            safeguard_bundle_digest=_BUNDLE_DIGEST,
            source_revision=_SOURCE_REVISION,
            attempt=1,
        )

    assert client._pending == {}
    await client.stop()
