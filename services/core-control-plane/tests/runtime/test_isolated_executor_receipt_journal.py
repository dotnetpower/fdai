"""Durable receipt correlation without dispatch, sink, or verification escalation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fdai.core.executor.post_release_closure import PostReleaseClosureOutcome
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.runtime.isolated_executor_client import EventBusDirectApiExecutionClient
from fdai.runtime.isolated_executor_receipt_journal import (
    BoundCommandCorrelation,
    BoundExecutorReceiptJournal,
    _bound_receipt_matches,
)
from fdai.runtime.providers import _build_resource_lock, _build_safeguard_lifecycle_coordinator
from fdai.runtime.safeguard_isolated_executor import SafeguardBoundEventBusDirectApiExecutionClient
from fdai.shared.contracts.models import (
    ExecutorEffectReceipt,
    ExecutorEffectReceiptStatus,
    Mode,
    SafeguardBoundExecutorCommand,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.executor_receipt_journal import (
    BoundExecutorCommandContext,
    ExecutorReceiptJournal,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.process_runtime import InMemoryProcessRuntimeStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts import EXECUTOR_COMMAND_TOPIC, EXECUTOR_RECEIPT_TOPIC
from tests.core.executor.test_direct_api_executor import _action
from tests.core.executor.test_safeguard_lifecycle_coordinator import _coordinator

_PREFIX = "runtime:isolated-executor:"


class _ObservedStateStore(InMemoryStateStore):
    """Signal durable terminal writes without timing-dependent consumer polling."""

    def __init__(self) -> None:
        super().__init__()
        self.retained = asyncio.Event()
        self.reconciled = asyncio.Event()

    async def write_state_with_audit_if_absent(
        self,
        key: str,
        value: Mapping[str, Any],
        audit_entry: Mapping[str, Any],
    ) -> bool:
        result = await super().write_state_with_audit_if_absent(key, value, audit_entry)
        if key.startswith(f"{_PREFIX}terminal-receipt:"):
            self.retained.set()
        if key.startswith(f"{_PREFIX}receipt-reconciliation:"):
            self.reconciled.set()
        return result


def _receipt(
    command: SafeguardBoundExecutorCommand,
    status: ExecutorEffectReceiptStatus = ExecutorEffectReceiptStatus.DISPATCHED,
) -> ExecutorEffectReceipt:
    return ExecutorEffectReceipt(
        receipt_id=UUID(int=99),
        command_id=command.command_id,
        action_id=command.action_id,
        idempotency_key=command.idempotency_key,
        attempt=command.attempt,
        action_payload_digest=command.action_payload_digest,
        requested_mode=command.requested_mode,
        status=status,
        executor_instance_id="executor-test",
        received_at=command.issued_at,
        completed_at=command.issued_at + timedelta(seconds=1),
        effect_applied=status is ExecutorEffectReceiptStatus.DISPATCHED,
        provider_receipt_ref=(
            "provider:test" if status is ExecutorEffectReceiptStatus.DISPATCHED else None
        ),
        safeguard_proof_bundle_digest=command.safeguard_proof_bundle_digest,
        audit_ref=f"action:{command.action_id}",
    )


async def _command(
    bus: InMemoryEventBus, *, group: str = "test-command-reader"
) -> SafeguardBoundExecutorCommand:
    commands = [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, group)]
    assert len(commands) == 1
    return SafeguardBoundExecutorCommand.model_validate(commands[0].payload)


async def _correlation(
    store: InMemoryStateStore, command: SafeguardBoundExecutorCommand
) -> BoundCommandCorrelation:
    return BoundCommandCorrelation.model_validate(
        await store.read_state(f"{_PREFIX}command:{command.command_id}")
    )


def _bind_journal(
    client: EventBusDirectApiExecutionClient, closures: PostReleaseClosureStore
) -> BoundExecutorReceiptJournal:
    journal = BoundExecutorReceiptJournal(
        client.audit_store,
        capacity=client.max_pending_requests,
        closure_store=closures,
    )
    client.bind_receipt_journal(journal)
    return journal


@pytest.mark.parametrize(
    "status",
    [ExecutorEffectReceiptStatus.DISPATCHED, ExecutorEffectReceiptStatus.REJECTED_INVARIANT],
)
async def test_terminal_delivery_retained_after_core_release_without_authority_escalation(
    status: ExecutorEffectReceiptStatus,
) -> None:
    store = _ObservedStateStore()
    bus = InMemoryEventBus()
    coordinator, lock = _coordinator(store)
    closures = coordinator._closure._closure_store
    client = EventBusDirectApiExecutionClient(bus, store, "core-test")
    _bind_journal(client, closures)
    wrapper = SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator)
    action = _action(mode=Mode.ENFORCE)
    try:
        result = await wrapper.execute(action=action)
        assert result.outcome.value == "failed"
        assert not any(lock.snapshot().values())
        assert client._pending == {}
        command = await _command(bus)
        correlation = await _correlation(store, command)
        before = await closures.read(correlation.closure_key)
        assert before is not None and before.outcome is PostReleaseClosureOutcome.QUARANTINED
        receipt = _receipt(command, status)
        await bus.publish(
            EXECUTOR_RECEIPT_TOPIC, command.partition_key, receipt.model_dump(mode="json")
        )
        await asyncio.wait_for(store.retained.wait(), timeout=2)
        await asyncio.wait_for(store.reconciled.wait(), timeout=2)
        assert await closures.read(correlation.closure_key) == before
        record = await store.read_state(f"{_PREFIX}receipt-reconciliation:{command.command_id}")
        assert record is not None
        assert record["outcome"] == "authoritative_reconciliation_evidence_required"
        assert record["effect_verified"] is False
        assert record["execution_authority"] is False
        assert record["safeguard_bundle_digest"] == command.safeguard_proof_bundle_digest
        await wrapper.execute(action=action)
        assert await _command(bus, group="test-command-replay") == command
    finally:
        await client.stop()


async def test_restart_consumes_original_receipt_without_a_pending_waiter_or_republication() -> (
    None
):
    store = _ObservedStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    first = EventBusDirectApiExecutionClient(bus, store, "core-before")
    _bind_journal(first, coordinator._closure._closure_store)
    await SafeguardBoundEventBusDirectApiExecutionClient(first, coordinator).execute(
        action=_action(mode=Mode.ENFORCE)
    )
    await first.stop()
    command = await _command(bus)
    restarted = EventBusDirectApiExecutionClient(bus, store, "core-after")
    _bind_journal(restarted, coordinator._closure._closure_store)
    await restarted.start()
    try:
        await bus.publish(
            EXECUTOR_RECEIPT_TOPIC, command.partition_key, _receipt(command).model_dump(mode="json")
        )
        await asyncio.wait_for(store.reconciled.wait(), timeout=2)
        assert restarted._pending == {}
        assert await _command(bus, group="test-command-replay") == command
    finally:
        await restarted.stop()


async def test_unbound_startup_consumer_retries_receipt_until_journal_is_bound() -> None:
    store = _ObservedStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    first = EventBusDirectApiExecutionClient(bus, store, "core-before")
    _bind_journal(first, coordinator._closure._closure_store)
    await SafeguardBoundEventBusDirectApiExecutionClient(first, coordinator).execute(
        action=_action(mode=Mode.ENFORCE)
    )
    await first.stop()
    command = await _command(bus)
    restarted = EventBusDirectApiExecutionClient(
        bus,
        store,
        "core-before-bind",
        retry_seconds=0.001,
    )
    await restarted.start()
    try:
        await bus.publish(
            EXECUTOR_RECEIPT_TOPIC,
            command.partition_key,
            _receipt(command).model_dump(mode="json"),
        )
        await asyncio.sleep(0.01)
        assert store.retained.is_set() is False

        _bind_journal(restarted, coordinator._closure._closure_store)
        await asyncio.wait_for(store.retained.wait(), timeout=2)
    finally:
        await restarted.stop()


async def test_receipt_binding_allows_bounded_cross_host_clock_skew() -> None:
    bus = InMemoryEventBus()
    store = InMemoryStateStore()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-clock-skew")
    _bind_journal(client, coordinator._closure._closure_store)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
        command = await _command(bus)
        receipt = _receipt(command).model_copy(
            update={
                "received_at": command.issued_at - timedelta(seconds=10),
                "completed_at": command.issued_at - timedelta(seconds=9),
            }
        )

        assert _bound_receipt_matches(
            command,
            receipt,
            partition_key=command.partition_key,
        )
    finally:
        await client.stop()


@pytest.mark.parametrize("unknown_publish", [False, True])
async def test_durable_attempt_claim_never_republishes_even_after_uncertain_send(
    monkeypatch: pytest.MonkeyPatch, unknown_publish: bool
) -> None:
    class PublishBus(InMemoryEventBus):
        async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
            result = await super().publish(topic, key, payload)
            if unknown_publish:
                raise ConnectionError("publication outcome unknown")
            return result

    store = InMemoryStateStore()
    bus = PublishBus()
    coordinator, _lock = _coordinator(store)
    action = _action(mode=Mode.ENFORCE)
    client = EventBusDirectApiExecutionClient(bus, store, "core-original")
    journal = _bind_journal(client, coordinator._closure._closure_store)
    contexts: list[BoundExecutorCommandContext] = []
    original_register = journal.register

    async def capture(
        command: SafeguardBoundExecutorCommand,
        context: BoundExecutorCommandContext,
        *,
        registration_id: UUID,
    ) -> tuple[SafeguardBoundExecutorCommand, bool]:
        contexts.append(context)
        return await original_register(command, context, registration_id=registration_id)

    monkeypatch.setattr(journal, "register", capture)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=action
        )
    finally:
        await client.stop()
    command = await _command(bus)
    assert len(contexts) == 1
    assert await store.read_state(f"{_PREFIX}not-published:{command.command_id}") is None
    work = await store.read_state(f"{_PREFIX}receipt-work")
    assert work is not None and str(command.command_id) in work["commands"]
    restarted = EventBusDirectApiExecutionClient(bus, store, "core-restarted")
    _bind_journal(restarted, coordinator._closure._closure_store)
    guard_called = False

    async def guard() -> datetime:
        nonlocal guard_called
        guard_called = True
        return datetime.now(UTC)

    try:
        with pytest.raises(RuntimeError, match="already claimed"):
            await restarted.publish_bound(
                action=action,
                safeguard_bundle_digest=command.safeguard_proof_bundle_digest,
                source_revision=command.source_revision,
                attempt=command.attempt,
                pre_publish_guard=guard,
                correlation_context=contexts[0],
            )
        assert not guard_called
        assert await _command(bus, group="test-command-replay") == command
    finally:
        await restarted.stop()


async def test_early_terminal_survives_restart_until_exact_core_closure_exists() -> None:
    store = _ObservedStateStore()
    coordinator, lock = _coordinator(store)
    closures = coordinator._closure._closure_store
    journal = BoundExecutorReceiptJournal(store, capacity=2, closure_store=closures)

    class EarlyReceiptBus(InMemoryEventBus):
        async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
            command = SafeguardBoundExecutorCommand.model_validate(payload)
            assert any(lock.snapshot().values())
            correlation = await _correlation(store, command)
            assert await closures.read(correlation.closure_key) is None
            assert await journal.accept(_receipt(command), partition_key=key)
            assert await journal.reconcile() == 0
            return await super().publish(topic, key, payload)

    bus = EarlyReceiptBus()
    client = EventBusDirectApiExecutionClient(bus, store, "core-early")
    client.bind_receipt_journal(journal)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
    finally:
        await client.stop()
    restarted_journal = BoundExecutorReceiptJournal(store, capacity=2, closure_store=closures)
    assert await restarted_journal.reconcile() == 1
    assert await restarted_journal.reconcile() == 0
    assert await _command(bus)
    assert not any(lock.snapshot().values())


async def test_exact_replay_is_deduplicated_and_conflicting_terminal_is_retained() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-dedupe")
    journal = _bind_journal(client, coordinator._closure._closure_store)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
    finally:
        await client.stop()
    command = await _command(bus)
    receipt = _receipt(command)
    assert await journal.accept(receipt, partition_key=command.partition_key)
    assert await journal.accept(receipt, partition_key=command.partition_key)
    assert await journal.accept(
        _receipt(command, ExecutorEffectReceiptStatus.REJECTED_INVARIANT),
        partition_key=command.partition_key,
    )
    assert await store.read_state(f"{_PREFIX}terminal-receipt:{command.command_id}") == (
        receipt.model_dump(mode="json")
    )
    conflicts = await store.read_states(f"{_PREFIX}receipt-rejected:", limit=10)
    assert len(conflicts) == 1 and conflicts[0]["reason"] == "terminal_receipt_conflict"
    retained = await store.read_states(f"{_PREFIX}terminal-receipt:", limit=10)
    assert len(retained) == 1
    await journal.reconcile()
    correlation = await _correlation(store, command)
    closure = await coordinator._closure._closure_store.read(correlation.closure_key)
    assert closure is not None and closure.outcome is PostReleaseClosureOutcome.QUARANTINED


@pytest.mark.parametrize(
    "changed",
    [
        {"command_id": UUID(int=555)},
        {"attempt": 2},
        {"action_id": UUID(int=123)},
        {"safeguard_proof_bundle_digest": "sha256:" + "e" * 64},
        {"action_payload_digest": "sha256:" + "f" * 64},
        {"requested_mode": Mode.SHADOW},
        {"received_at": datetime(2020, 1, 1, tzinfo=UTC)},
    ],
)
async def test_foreign_or_mismatched_terminal_never_completes_attempt(
    changed: dict[str, object],
) -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-mismatch")
    journal = _bind_journal(client, coordinator._closure._closure_store)
    try:
        await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
    finally:
        await client.stop()
    command = await _command(bus)
    payload = _receipt(command, ExecutorEffectReceiptStatus.REJECTED_INVARIANT).model_dump()
    payload.update(changed)
    receipt = ExecutorEffectReceipt.model_validate(payload)
    correlated = await journal.accept(receipt, partition_key=command.partition_key)
    assert correlated is ("command_id" not in changed)
    assert await store.read_state(f"{_PREFIX}terminal-receipt:{command.command_id}") is None
    assert await journal.reconcile() == 0


async def test_capacity_failure_prevents_publication_and_leaves_claim_fail_closed() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-full", max_pending_requests=0)
    _bind_journal(client, coordinator._closure._closure_store)
    try:
        result = await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
            action=_action(mode=Mode.ENFORCE)
        )
        assert result.outcome.value == "failed"
        assert [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-empty")] == []
    finally:
        await client.stop()


def test_runtime_composition_injects_journal_without_executor_authority() -> None:
    journals: list[ExecutorReceiptJournal] = []
    _build_safeguard_lifecycle_coordinator(
        audit_store=InMemoryStateStore(),
        resource_lock=_build_resource_lock({"RUNTIME_ENV": "test"}),
        process_store=InMemoryProcessRuntimeStore(),
        environment={"RUNTIME_ENV": "test"},
        receipt_journal_consumer=journals.append,
    )
    assert len(journals) == 1
    assert isinstance(journals[0], BoundExecutorReceiptJournal)


async def test_bound_publication_without_injected_journal_fails_closed() -> None:
    store = InMemoryStateStore()
    bus = InMemoryEventBus()
    coordinator, _lock = _coordinator(store)
    client = EventBusDirectApiExecutionClient(bus, store, "core-unbound")
    result = await SafeguardBoundEventBusDirectApiExecutionClient(client, coordinator).execute(
        action=_action(mode=Mode.ENFORCE)
    )
    assert result.outcome.value == "failed"
    assert client._consumer_task is None
    assert await store.read_states(f"{_PREFIX}command:", limit=1) == ()
    assert [item async for item in bus.subscribe(EXECUTOR_COMMAND_TOPIC, "test-empty")] == []
