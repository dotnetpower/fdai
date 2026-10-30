"""Compact heads preserve the full verified recent view without repeated history writes."""

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest
from fdai.agents._framework.adapters import AuditChainError
from fdai.agents._framework.audit_chain_journal import AUDIT_CHECKPOINT_KEY, load_journal
from fdai.agents._framework.audit_chain_rehydrate import (
    StateStoreAuditChainAdapter,
    rehydrate_audit_entries,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class CountingStore(InMemoryStateStore):
    written_bytes = 0

    async def compare_and_set_state_with_audit(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        expected_revision: int,
        audit_entry: Mapping[str, Any],
    ) -> bool:
        committed = await super().compare_and_set_state_with_audit(
            key, value, expected_revision=expected_revision, audit_entry=audit_entry
        )
        if committed:
            self.written_bytes += len(json.dumps(value, sort_keys=True).encode())
        return committed


class CompactStore(CountingStore):
    window_reads = 0

    async def read_audit_chain_window(
        self, *, start_seq: int, end_seq: int, head_hash: str
    ) -> tuple[Mapping[str, Any], ...]:
        self.window_reads += 1
        records = [deepcopy(row["entry"]) for row in self._audit]
        selected = []
        current = head_hash
        for _ in range(end_seq - start_seq):
            matches = [record for record in records if record.get("entry_hash") == current]
            selected.extend(matches)
            if len(matches) != 1:
                break
            current = matches[0]["prev_hash"]
        return tuple(reversed(selected))


async def _append(chain: StateStoreAuditChainAdapter, index: int) -> None:
    await chain.append(
        principal="Saga",
        topic="object.verdict",
        correlation_id=f"correlation-{index}",
        payload={"event": index, "reason": "unchanged"},
    )


async def test_same_history_writes_a_compact_head_but_retains_512_entry_restart_view() -> None:
    legacy, compact = CountingStore(), CompactStore()
    before, after = StateStoreAuditChainAdapter(legacy), StateStoreAuditChainAdapter(compact)
    for index in range(600):
        await _append(before, index)
        await _append(after, index)
    assert compact.window_reads == 0
    assert before.entries == after.entries
    assert len(after.entries) == 512
    stored = await compact.read_state(AUDIT_CHECKPOINT_KEY)
    assert stored is not None
    assert stored["schema_version"] == "3.0.0"
    assert len(stored["entries"]) == 1
    assert len(json.dumps(stored).encode()) < 1024
    assert compact.written_bytes * 50 < legacy.written_bytes
    restored = await rehydrate_audit_entries(compact)
    assert restored == after.entries
    assert compact.window_reads == 1
    after.verify()
    assert await compact.verify_chain()
    assert [row["entry"] for row in legacy.audit_entries] == [
        row["entry"] for row in compact.audit_entries
    ]


async def test_replicas_and_paired_cas_keep_one_chain_and_do_not_use_a_stale_mirror() -> None:
    store = CompactStore()
    one, two = StateStoreAuditChainAdapter(store), StateStoreAuditChainAdapter(store)
    for index in range(12):
        await _append(one if index % 2 else two, index)
    await store.write_state("aggregate", {"schema_version": "1.0.0", "revision": 1})
    snapshot = await store.read_state(AUDIT_CHECKPOINT_KEY)
    rejected = await one.append_with_state_pair(
        state_key="aggregate",
        state_value={"schema_version": "1.0.0", "revision": 3},
        expected_state_revision=2,
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="paired",
        payload={"count": 3},
    )
    assert rejected is None
    assert await store.read_state(AUDIT_CHECKPOINT_KEY) == snapshot
    committed = await one.append_with_state_pair(
        state_key="aggregate",
        state_value={"schema_version": "1.0.0", "revision": 2},
        expected_state_revision=1,
        principal="Saga",
        topic="object.audit-entry",
        correlation_id="paired",
        payload={"count": 3},
    )
    assert committed is not None
    assert committed.seq == 12
    assert len(await rehydrate_audit_entries(store)) == 13
    one.verify()


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "payload", "head"])
async def test_recovery_rejects_missing_duplicate_or_corrupted_canonical_records(
    corruption: str,
) -> None:
    store = CompactStore()
    chain = StateStoreAuditChainAdapter(store)
    for index in range(5):
        await _append(chain, index)
    if corruption == "missing":
        store._audit.pop(2)
    elif corruption == "duplicate":
        store._audit.append(deepcopy(store._audit[-1]))
    elif corruption == "payload":
        store._audit[2]["entry"]["payload"] = {"forged": True}
    else:
        existing = await store.read_state(AUDIT_CHECKPOINT_KEY)
        assert existing is not None
        checkpoint = dict(existing)
        checkpoint["content_digest"] = "f" * 64
        await store.write_state(AUDIT_CHECKPOINT_KEY, checkpoint)
    with pytest.raises(AuditChainError):
        await rehydrate_audit_entries(store)


async def test_v3_checkpoint_cannot_fall_back_to_an_unsupported_reader() -> None:
    store = CompactStore()
    await _append(StateStoreAuditChainAdapter(store), 0)
    unsupported = InMemoryStateStore()
    checkpoint = await store.read_state(AUDIT_CHECKPOINT_KEY)
    assert checkpoint is not None
    await unsupported.write_state(AUDIT_CHECKPOINT_KEY, checkpoint)
    with pytest.raises(AuditChainError, match="requires the bounded window reader"):
        await load_journal(unsupported)


async def test_window_ignores_detached_chains_with_equal_sequences() -> None:
    store = CompactStore()
    chain = StateStoreAuditChainAdapter(store)
    for index in range(8):
        await _append(chain, index)
    detached = CountingStore()
    other = StateStoreAuditChainAdapter(detached)
    for index in range(4):
        await _append(other, index + 100)
    for record in detached.audit_entries:
        await store.append_audit_entry(record["entry"])
    assert await rehydrate_audit_entries(store) == chain.entries
    assert len(tuple(store.audit_entries)) == 12


async def test_legacy_journal_cuts_over_without_rewriting_any_canonical_audit_record() -> None:
    store = CompactStore()
    legacy = CountingStore()
    chain = StateStoreAuditChainAdapter(legacy)
    for index in range(4):
        await _append(chain, index)
    checkpoint = await legacy.read_state(AUDIT_CHECKPOINT_KEY)
    assert checkpoint is not None
    await store.write_state(AUDIT_CHECKPOINT_KEY, checkpoint)
    store._audit = deepcopy(legacy._audit)
    preserved = deepcopy(store._audit)
    cutover = StateStoreAuditChainAdapter(store)
    await _append(cutover, 4)
    assert store._audit[:4] == preserved
    assert cutover.entries[:4] == chain.entries
    assert len(cutover.entries) == 5
    assert await rehydrate_audit_entries(store) == cutover.entries
