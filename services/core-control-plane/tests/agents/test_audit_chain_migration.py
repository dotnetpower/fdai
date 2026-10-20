"""A reviewed migration preserves complete legacy evidence without guessing a head."""

from dataclasses import asdict, replace

import pytest
from fdai.agents import prepare_saga_audit_migration
from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.agents._framework.audit_chain_journal import _decode_journal, entry_hash


def _history(count: int, *, name: str = "main", legacy: bool = False):
    records = []
    previous = "0" * 64
    for seq in range(count):
        payload = {"record": seq, "name": name}
        entry = AuditEntry(seq, previous, "", "Saga", "object.event", name, _digest(payload))
        entry = replace(entry, entry_hash=entry_hash(entry, legacy=legacy))
        records.append(
            {
                **asdict(entry),
                "actor": "Saga",
                "action_kind": "audit.record",
                "payload": payload,
            }
        )
        previous = entry.entry_hash
    return records


def _checkpoint(records, *, length: int | None = None):
    size = len(records) if length is None else length
    return {
        "schema_version": "1.0.0",
        "length": size,
        "head_hash": records[size - 1]["entry_hash"],
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_migration_anchors_large_history_and_retains_unmodified_detached_roots(legacy):
    records = _history(1_200, legacy=legacy)
    detached = _history(14, name="old")
    history = [*detached, *records]
    original = [dict(row) for row in history]
    checkpoint = _checkpoint(records, length=1_100)

    plan = prepare_saga_audit_migration(checkpoint, history)

    assert plan.source_count == 1_214
    assert plan.detached_count == 14
    assert plan.journal.length == 1_200
    assert plan.journal.base_length == 688
    assert len(plan.journal.entries) == 512
    assert plan.journal.head_hash == records[-1]["entry_hash"]
    assert _decode_journal(plan.checkpoint()) == plan.journal
    assert history == original
    assert prepare_saga_audit_migration(checkpoint, history).plan_digest == plan.plan_digest


@pytest.mark.parametrize("corruption", ["payload", "hash", "missing", "checkpoint", "duplicate"])
def test_migration_rejects_corruption_without_modifying_inputs(corruption):
    records = _history(4)
    checkpoint = _checkpoint(records)
    if corruption == "payload":
        records[0]["payload"] = {"changed": True}
    elif corruption == "hash":
        records[0]["entry_hash"] = "f" * 64
    elif corruption == "missing":
        records.pop(0)
    elif corruption == "checkpoint":
        checkpoint["head_hash"] = "f" * 64
    else:
        records.append(dict(records[0]))
    with pytest.raises(AuditChainError):
        prepare_saga_audit_migration(checkpoint, records)


@pytest.mark.parametrize("anchor_length", [1, 2])
def test_migration_rejects_fork_before_or_after_checkpoint(anchor_length):
    records = _history(3)
    fork = dict(records[1])
    fork["payload"] = {"fork": True}
    fork["payload_digest"] = _digest(fork["payload"])
    entry = AuditEntry(**{key: fork[key] for key in asdict(AuditEntry(0, "", "", "", "", "", ""))})
    fork["entry_hash"] = entry_hash(entry)
    with pytest.raises(AuditChainError, match="fork"):
        prepare_saga_audit_migration(_checkpoint(records, length=anchor_length), [*records, fork])


def test_migration_rejects_corrupted_detached_history():
    records = _history(3)
    detached = _history(2, name="old")
    detached[0]["payload"] = {"changed": True}
    with pytest.raises(AuditChainError, match="payload digest"):
        prepare_saga_audit_migration(_checkpoint(records), [*detached, *records])
