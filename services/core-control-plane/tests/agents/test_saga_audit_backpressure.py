"""Audit backpressure retains authenticated input without releasing an unaudited seal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fdai.agents import Saga, StateStoreAuditChainAdapter
from fdai.agents._framework import audit_chain_rehydrate
from fdai.agents._framework.adapters import AuditChainError
from fdai.agents._framework.audit_chain_journal import AUDIT_CHECKPOINT_KEY
from fdai.agents._framework.audit_chain_rehydrate import AuditAppendDeferredError
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents._framework.saga_audit_runtime import _AUDIT_INBOX_PREFIX
from fdai.shared.providers.testing import InMemoryStateStore


class BackpressuredStore(InMemoryStateStore):
    blocked = True

    async def compare_and_set_state_with_audit(self, key, *args, **kwargs):
        if key == AUDIT_CHECKPOINT_KEY and self.blocked:
            return False
        return await super().compare_and_set_state_with_audit(key, *args, **kwargs)


def verdict():
    upload_id = str(uuid4())
    return {
        "producer_principal": "Forseti",
        "kind": "document_ingestion",
        "stage": "received",
        "decision": "admit",
        "reason": "ingress_validated",
        "correlation_id": upload_id,
        "idempotency_key": f"document.received:{upload_id}",
        "upload_id": upload_id,
        "document_id": str(uuid4()),
    }


def saga_for(store, bus, *, clock=lambda: datetime.now(UTC)):
    saga = Saga(
        audit_chain=StateStoreAuditChainAdapter(store),
        durable_state_store=store,
        clock=clock,
    )
    saga.bind_bus(bus)
    return saga


async def append(chain):
    return await chain.append(
        principal="Forseti", topic="object.verdict", correlation_id="example", payload={}
    )


async def test_local_queue_wait_does_not_consume_active_append_budget(monkeypatch):
    monkeypatch.setattr(audit_chain_rehydrate, "_APPEND_DEADLINE_SECONDS", 0.01)
    chain = StateStoreAuditChainAdapter(InMemoryStateStore())
    await chain._append_lock.acquire()
    task = asyncio.create_task(append(chain))
    await asyncio.sleep(0.03)
    assert not task.done()
    chain._append_lock.release()
    assert (await task).seq == 0
    assert chain._queued_appends == 0


async def test_queue_capacity_and_cancellation_do_not_leak_admission(monkeypatch):
    monkeypatch.setattr(audit_chain_rehydrate, "_APPEND_QUEUE_LIMIT", 1)
    chain = StateStoreAuditChainAdapter(InMemoryStateStore())
    await chain._append_lock.acquire()
    task = asyncio.create_task(append(chain))
    await asyncio.sleep(0)
    with pytest.raises(AuditAppendDeferredError, match="queue is full"):
        await append(chain)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert chain._queued_appends == 0
    chain._append_lock.release()
    assert (await append(chain)).seq == 0


async def test_failed_append_is_durable_and_restart_releases_only_audited_decision():
    store = BackpressuredStore()
    bus = InMemoryBus(registry=load_pantheon())
    saga = saga_for(store, bus)
    payload = verdict()
    await saga.on_typed_message("object.verdict", payload)
    assert not bus.messages_on("object.audit-entry")
    rows, count = await store.read_state_page(_AUDIT_INBOX_PREFIX, limit=10)
    assert count == 1 and rows[0]["status"] == "pending"
    assert saga.audit_chain.entries == []
    store.blocked = False
    restarted = saga_for(store, bus)
    await restarted.recover_audit_outbox()
    assert len(restarted.audit_chain.entries) == 1
    assert len(bus.messages_on("object.audit-entry")) == 1
    assert bus.messages_on("object.audit-entry")[0].payload["upload_id"] == payload["upload_id"]
    await restarted.recover_audit_outbox()
    assert len(bus.messages_on("object.audit-entry")) == 1
    assert (await store.read_state_page(_AUDIT_INBOX_PREFIX, limit=10))[0][0]["status"] == (
        "recovered"
    )


async def test_recovery_keeps_failure_pending_and_replica_lease_is_exclusive(monkeypatch):
    store = BackpressuredStore()
    bus = InMemoryBus(registry=load_pantheon())
    first, second = saga_for(store, bus), saga_for(store, bus)
    await first.on_typed_message("object.verdict", verdict())
    await second.recover_audit_outbox()
    assert not bus.messages_on("object.audit-entry")
    rows, _ = await store.read_state_page(_AUDIT_INBOX_PREFIX, limit=10)
    assert rows[0]["status"] == "pending"
    entered, release = asyncio.Event(), asyncio.Event()
    original = first._process_audited_message

    async def pause(topic, payload):
        entered.set()
        await release.wait()
        await original(topic, payload)

    monkeypatch.setattr(first, "_process_audited_message", pause)
    store.blocked = False
    task = asyncio.create_task(first.recover_audit_outbox())
    await entered.wait()
    await second.recover_audit_outbox()
    assert not bus.messages_on("object.audit-entry")
    release.set()
    await task
    assert len(bus.messages_on("object.audit-entry")) == 1


async def test_cancelled_recovery_is_reclaimable_only_after_lease_expiry(monkeypatch):
    now = datetime(2026, 10, 23, tzinfo=UTC)
    store = BackpressuredStore()
    bus = InMemoryBus(registry=load_pantheon())
    first = saga_for(store, bus, clock=lambda: now)
    await first.on_typed_message("object.verdict", verdict())
    entered = asyncio.Event()

    async def pause(*_args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(first, "_process_audited_message", pause)
    task = asyncio.create_task(first.recover_audit_outbox())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    store.blocked = False
    restarted = saga_for(store, bus, clock=lambda: now)
    await restarted.recover_audit_outbox()
    assert not bus.messages_on("object.audit-entry")
    now += timedelta(seconds=121)
    await restarted.recover_audit_outbox()
    assert len(bus.messages_on("object.audit-entry")) == 1


async def test_integrity_failure_and_missing_durable_recovery_still_fail_closed(monkeypatch):
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    saga = saga_for(store, bus)

    async def corrupt(**_kwargs):
        raise AuditChainError("chain is corrupt")

    monkeypatch.setattr(saga.audit_chain, "append", corrupt)
    with pytest.raises(AuditChainError, match="corrupt"):
        await saga.on_typed_message("object.verdict", verdict())
    assert (await store.read_state_page(_AUDIT_INBOX_PREFIX, limit=10))[1] == 0
    assert not bus.messages_on("object.audit-entry")
    transient = Saga(audit_chain=StateStoreAuditChainAdapter(BackpressuredStore()))
    transient.bind_bus(bus)
    with pytest.raises(AuditAppendDeferredError, match="durable state"):
        await transient.on_typed_message("object.verdict", verdict())


async def test_document_source_replay_redelivers_identical_seal_but_rejects_collision():
    store = InMemoryStateStore()
    bus = InMemoryBus(registry=load_pantheon())
    saga = saga_for(store, bus)
    payload = verdict()
    await saga.on_typed_message("object.verdict", payload)
    await saga.on_typed_message("object.verdict", payload)
    seals = bus.messages_on("object.audit-entry")
    assert len(seals) == 2 and seals[0].payload == seals[1].payload
    with pytest.raises(RuntimeError, match="idempotency collision"):
        await saga.on_typed_message("object.verdict", {**payload, "decision": "hold"})
    assert len(bus.messages_on("object.audit-entry")) == 2
