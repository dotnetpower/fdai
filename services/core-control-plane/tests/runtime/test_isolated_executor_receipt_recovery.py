"""Receipt retry and proven-no-publication cleanup without duplicate dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from uuid import UUID

import pytest
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.isolated_executor_receipt_journal import (
    BoundCommandCorrelation,
    BoundExecutorReceiptJournal,
)
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import Action, ExecutionPath, Mode, SafeguardBoundExecutorCommand
from fdai.shared.providers.event_bus import EventPublishNotAttemptedError, PublishReceipt
from fdai.shared.providers.executor_receipt_journal import BoundExecutorCommandContext
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC, EXECUTOR_RECEIPT_TOPIC
from psycopg import OperationalError
from tests.core.executor.test_direct_api_executor import _action
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator
from tests.runtime.test_isolated_executor_receipt_journal import (
    _PREFIX,
    _bind_journal,
    _command,
    _ObservedStateStore,
    _receipt,
)


class _TransientReceiptStore(_ObservedStateStore):
    """Fail the first terminal persistence operation, leaving delivery unacknowledged."""

    def __init__(self, failure: str) -> None:
        super().__init__()
        self.failure = failure
        self.attempts = 0
        self.failed = asyncio.Event()

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if key.startswith(f"{_PREFIX}terminal-receipt:"):
            self.attempts += 1
            if self.attempts == 1:
                self.failed.set()
                if self.failure == "connection":
                    raise ConnectionError("synthetic transient storage failure")
                if self.failure == "postgres":
                    raise OperationalError("synthetic transient storage failure")
                await asyncio.Event().wait()
        return await super().write_state_with_audit_if_absent(key, value, audit_entry)


class _NotAttemptedPublishBus(InMemoryEventBus):
    async def publish(
        self,
        topic: str,
        key: str,
        payload: Mapping[str, Any],
    ) -> PublishReceipt:
        if topic == EXECUTOR_COMMAND_TOPIC:
            raise EventPublishNotAttemptedError("synthetic pre-send failure")
        return await super().publish(topic, key, payload)


@pytest.mark.parametrize("failure", ["connection", "postgres", "timeout"])
async def test_receipt_storage_recovers_without_new_publication_or_start(failure: str) -> None:
    store = _TransientReceiptStore(failure)
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-retry", retry_seconds=0.001)
    _bind_journal(client, coordinator._closure._closure_store)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
        command = await _command(bus)
        consumer = client._consumer_task
        client.response_timeout_seconds = 0.05
        await bus.publish(
            EXECUTOR_RECEIPT_TOPIC, command.partition_key, _receipt(command).model_dump(mode="json")
        )
        await asyncio.wait_for(store.reconciled.wait(), timeout=2)
        assert store.attempts == 2
        assert client._consumer_task is consumer
        assert consumer is not None and not consumer.done()
        assert await _command(bus, group="test-no-republication") == command
    finally:
        await client.stop()


async def test_cancelled_receipt_persistence_stops_without_resubscribing() -> None:
    store = _TransientReceiptStore("timeout")
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-cancel")
    _bind_journal(client, coordinator._closure._closure_store)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
        command = await _command(bus)
        consumer = client._consumer_task
        await bus.publish(
            EXECUTOR_RECEIPT_TOPIC, command.partition_key, _receipt(command).model_dump(mode="json")
        )
        await asyncio.wait_for(store.failed.wait(), timeout=2)
        await client.stop()
        assert consumer is not None and consumer.cancelled()
        assert store.attempts == 1
        assert await store.read_state(f"{_PREFIX}terminal-receipt:{command.command_id}") is None
    finally:
        await client.stop()


async def test_proven_unsent_command_releases_receipt_work_and_stays_retryable() -> None:
    store = InMemoryStateStore()
    bus = _NotAttemptedPublishBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-not-attempted")
    _bind_journal(client, coordinator._closure._closure_store)
    try:
        result = await SafeguardBoundEventBusDirectApiExecutionClient(
            client,
            coordinator,
        ).execute(action=_action(mode=Mode.ENFORCE))

        assert result.outcome.value == "rejected_invariant"
        assert result.reason == "dispatch transport proved no publication"
        rows = await store.read_states(f"{_PREFIX}not-published:", limit=1)
        assert len(rows) == 1
        work = await store.read_state(f"{_PREFIX}receipt-work")
        assert work is not None and work["commands"] == []
        assert [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-empty")] == []
    finally:
        await client.stop()


def _context(action: Action, identity_digit: str) -> BoundExecutorCommandContext:
    return BoundExecutorCommandContext(
        action_id=str(action.action_id),
        reservation_attempt=1,
        source_revision="commit:" + "c" * 40,
        execution_path=ExecutionPath.DIRECT_API.value,
        safeguard_bundle_digest="sha256:" + "b" * 64,
        reservation_identity_digest="sha256:" + identity_digit * 64,
        evidence_identity_digest="sha256:" + identity_digit * 64,
        target_digest="sha256:" + "d" * 64,
        target_fence_generation=1,
    )


@pytest.mark.parametrize("failure", ["refused", "cancelled", "timeout"])
async def test_guard_failure_releases_capacity_but_attempt_cannot_be_republished(
    failure: str,
) -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-guard", max_pending_requests=1)
    _bind_journal(client, coordinator._closure._closure_store)
    first = _action(mode=Mode.ENFORCE)
    first_context = _context(first, "1")
    entered = asyncio.Event()

    async def refused_guard() -> datetime:
        entered.set()
        if failure == "refused":
            raise RuntimeError("synthetic guard refusal")
        await asyncio.Event().wait()
        raise AssertionError("blocked guard must not resume")

    async def guard() -> datetime:
        return datetime.now(UTC)

    async def replay_guard() -> datetime:
        raise AssertionError("replay must not reach the guard")

    try:
        if failure == "timeout":
            client.response_timeout_seconds = 0.05
        pending = asyncio.create_task(
            client.publish_bound(
                action=first,
                safeguard_bundle_digest=first_context.safeguard_bundle_digest,
                source_revision=first_context.source_revision,
                attempt=1,
                pre_publish_guard=refused_guard,
                correlation_context=first_context,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        if failure == "cancelled":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        elif failure == "timeout":
            with pytest.raises(TimeoutError):
                await pending
        else:
            with pytest.raises(RuntimeError, match="guard refusal"):
                await pending
        rows = await store.read_states(f"{_PREFIX}command:", limit=1)
        correlation = BoundCommandCorrelation.model_validate(rows[0])
        marker = await store.read_state(f"{_PREFIX}not-published:{correlation.command.command_id}")
        assert marker is not None and marker["outcome"] == "publication_not_started"
        assert marker["execution_authority"] is False and marker["effect_verified"] is False
        work = await store.read_state(f"{_PREFIX}receipt-work")
        assert work is not None and work["commands"] == []
        assert await store.read_state(f"{_PREFIX}attempt:{correlation.closure_key}") is not None
        with pytest.raises(RuntimeError, match="already claimed"):
            await client.publish_bound(
                action=first,
                safeguard_bundle_digest=first_context.safeguard_bundle_digest,
                source_revision=first_context.source_revision,
                attempt=1,
                pre_publish_guard=replay_guard,
                correlation_context=first_context,
            )
        second = _action(
            action_id="00000000-0000-0000-0000-000000000020",
            idempotency_key="second-attempt",
            mode=Mode.ENFORCE,
        )
        second_context = _context(second, "2")
        command = await client.publish_bound(
            action=second,
            safeguard_bundle_digest=second_context.safeguard_bundle_digest,
            source_revision=second_context.source_revision,
            attempt=1,
            pre_publish_guard=guard,
            correlation_context=second_context,
        )
        assert await _command(bus) == command
        assert command.action_id == second.action_id
        assert await store.read_state(f"{_PREFIX}not-published:{command.command_id}") is None
    finally:
        await client.stop()


async def test_durable_no_publication_marker_repairs_interrupted_capacity_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    closures = coordinator._closure._closure_store
    client = EventBusDirectApiExecutionClient(bus, store, "core-cleanup")
    journal = _bind_journal(client, closures)
    action = _action(mode=Mode.ENFORCE)
    context = _context(action, "1")
    original_change = journal._change_work

    async def fail_removal(command_id: UUID, *, add: bool) -> None:
        if not add:
            raise ConnectionError("synthetic cleanup interruption")
        await original_change(command_id, add=add)

    async def refused_guard() -> datetime:
        raise RuntimeError("synthetic guard refusal")

    monkeypatch.setattr(journal, "_change_work", fail_removal)
    try:
        with pytest.raises(RuntimeError, match="guard refusal"):
            await client.publish_bound(
                action=action,
                safeguard_bundle_digest=context.safeguard_bundle_digest,
                source_revision=context.source_revision,
                attempt=1,
                pre_publish_guard=refused_guard,
                correlation_context=context,
            )
    finally:
        await client.stop()
    restarted = BoundExecutorReceiptJournal(store, capacity=1, closure_store=closures)
    assert await restarted.reconcile() == 1
    assert await restarted.reconcile() == 0
    work = await store.read_state(f"{_PREFIX}receipt-work")
    assert work is not None and work["commands"] == []
    assert [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-empty")] == []


async def test_failed_no_publication_marker_retires_at_the_receipt_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    bus = _NotAttemptedPublishBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(
        bus,
        store,
        "core-marker-failure",
        retry_seconds=0.001,
    )
    current_time = [datetime.now(UTC)]
    journal = BoundExecutorReceiptJournal(
        store,
        capacity=1,
        closure_store=coordinator._closure._closure_store,
        clock=lambda: current_time[0],
    )
    client.bind_receipt_journal(journal)
    original_write = store.write_state_with_audit_if_absent

    async def fail_marker(
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        if key.startswith(f"{_PREFIX}not-published:"):
            raise ConnectionError("synthetic marker outage")
        return await original_write(key, value, audit_entry)

    monkeypatch.setattr(store, "write_state_with_audit_if_absent", fail_marker)
    action = _action(mode=Mode.ENFORCE)
    context = _context(action, "1")
    try:
        with pytest.raises(EventPublishNotAttemptedError):
            await client.publish_bound(
                action=action,
                safeguard_bundle_digest=context.safeguard_bundle_digest,
                source_revision=context.source_revision,
                attempt=1,
                pre_publish_guard=lambda: asyncio.sleep(0, result=datetime.now(UTC)),
                correlation_context=context,
            )
    finally:
        await client.stop()

    rows = await store.read_states(f"{_PREFIX}command:", limit=1)
    correlation = BoundCommandCorrelation.model_validate(rows[0])
    work = await store.read_state(f"{_PREFIX}receipt-work")
    assert work is not None and str(correlation.command.command_id) in work["commands"]

    monkeypatch.setattr(store, "write_state_with_audit_if_absent", original_write)
    current_time[0] = correlation.command.deadline_at + timedelta(seconds=31)
    assert await journal.reconcile() == 1
    work = await store.read_state(f"{_PREFIX}receipt-work")
    assert work is not None and work["commands"] == []
    timeout = await store.read_state(f"{_PREFIX}receipt-timeout:{correlation.command.command_id}")
    assert timeout is not None

    assert await journal.accept(
        _receipt(correlation.command),
        partition_key=correlation.command.partition_key,
    )
    work = await store.read_state(f"{_PREFIX}receipt-work")
    assert work is not None and str(correlation.command.command_id) in work["commands"]


@pytest.mark.parametrize(
    "failure",
    ["lost_response", "cancelled", "timeout", "readback_connection", "readback_unobserved"],
)
async def test_lost_registration_reply_retires_exact_owned_work(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(
        bus, store, "core-register-reply", max_pending_requests=1, retry_seconds=0.001
    )
    journal = _bind_journal(client, coordinator._closure._closure_store)
    original_register = journal.register
    original_read = store.read_state
    entered = asyncio.Event()
    unread = 2 if failure.startswith("readback_") else 0

    async def readback(key: str) -> Mapping[str, Any] | None:
        nonlocal unread
        if key.startswith(f"{_PREFIX}command:") and unread:
            unread -= 1
            if failure == "readback_unobserved":
                return None
            raise ConnectionError("synthetic registration readback failure")
        return await original_read(key)

    async def lost_reply(
        command: SafeguardBoundExecutorCommand,
        context: BoundExecutorCommandContext,
        *,
        registration_id: UUID,
    ) -> tuple[SafeguardBoundExecutorCommand, bool]:
        await original_register(command, context, registration_id=registration_id)
        entered.set()
        if failure in {"cancelled", "timeout"}:
            await asyncio.Event().wait()
        raise ConnectionError("synthetic lost registration response")

    async def guard() -> datetime:
        raise AssertionError("failed registration must not reach the guard")

    monkeypatch.setattr(store, "read_state", readback)
    monkeypatch.setattr(journal, "register", lost_reply)
    action = _action(mode=Mode.ENFORCE)
    context = _context(action, "1")
    if failure == "timeout":
        client.response_timeout_seconds = 0.05
    try:
        pending = asyncio.create_task(
            client.publish_bound(
                action=action,
                safeguard_bundle_digest=context.safeguard_bundle_digest,
                source_revision=context.source_revision,
                attempt=1,
                pre_publish_guard=guard,
                correlation_context=context,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        if failure == "cancelled":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        elif failure == "timeout":
            with pytest.raises(TimeoutError):
                await pending
        else:
            with pytest.raises(ConnectionError, match="lost registration response"):
                await pending
        rows = await store.read_states(f"{_PREFIX}command:", limit=1)
        correlation = BoundCommandCorrelation.model_validate(rows[0])
        marker = await store.read_state(f"{_PREFIX}not-published:{correlation.command.command_id}")
        assert marker is not None
        assert marker["registration_id"] == str(correlation.registration_id)
        work = await store.read_state(f"{_PREFIX}receipt-work")
        assert work is not None and work["commands"] == []
        assert await store.read_state(f"{_PREFIX}attempt:{correlation.closure_key}") is not None
        assert unread == 0
        assert [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-empty")] == []
    finally:
        await client.stop()


@pytest.mark.parametrize("lost_duplicate_reply", [False, True])
async def test_duplicate_registration_never_retires_original_command(
    monkeypatch: pytest.MonkeyPatch, lost_duplicate_reply: bool
) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FrozenDatetime:
            instant = cls(2026, 9, 12, tzinfo=UTC)
            return instant.replace(tzinfo=None) if tz is None else instant.astimezone(tz)

    monkeypatch.setattr("fdai.runtime.isolated_executor_client.datetime", FrozenDatetime)
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-duplicate", max_pending_requests=1)
    journal = _bind_journal(client, coordinator._closure._closure_store)
    original_register = journal.register
    action = _action(mode=Mode.ENFORCE)
    context = _context(action, "1")
    guard_calls = 0

    async def guard() -> datetime:
        nonlocal guard_calls
        guard_calls += 1
        return datetime.now(UTC)

    async def lost_reply(
        command: SafeguardBoundExecutorCommand,
        context: BoundExecutorCommandContext,
        *,
        registration_id: UUID,
    ) -> tuple[SafeguardBoundExecutorCommand, bool]:
        _registered, owner = await original_register(
            command, context, registration_id=registration_id
        )
        assert not owner
        raise ConnectionError("synthetic lost duplicate response")

    try:
        command = await client.publish_bound(
            action=action,
            safeguard_bundle_digest=context.safeguard_bundle_digest,
            source_revision=context.source_revision,
            attempt=1,
            pre_publish_guard=guard,
            correlation_context=context,
        )
        if lost_duplicate_reply:
            monkeypatch.setattr(journal, "register", lost_reply)
        expected_error = ConnectionError if lost_duplicate_reply else RuntimeError
        with pytest.raises(expected_error):
            await client.publish_bound(
                action=action,
                safeguard_bundle_digest=context.safeguard_bundle_digest,
                source_revision=context.source_revision,
                attempt=1,
                pre_publish_guard=guard,
                correlation_context=context,
            )
        work = await store.read_state(f"{_PREFIX}receipt-work")
        assert work is not None and work["commands"] == [str(command.command_id)]
        assert await store.read_state(f"{_PREFIX}not-published:{command.command_id}") is None
        assert guard_calls == 1
        assert await _command(bus) == command
    finally:
        await client.stop()
