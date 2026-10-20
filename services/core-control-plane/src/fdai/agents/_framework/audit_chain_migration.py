"""Explicit, checkpoint-anchored recovery of complete legacy Saga histories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.agents._framework.audit_chain_journal import (
    _ENTRY_FIELDS,
    _GENESIS_HASH,
    AUDIT_JOURNAL_LIMIT,
    AuditJournal,
    _decode_entry,
    _is_hash,
    entry_hash,
    verify_entries,
)


@dataclass(frozen=True)
class SagaAuditMigration:
    """A reviewed plan, not authority to discard history or execute an action."""

    journal: AuditJournal
    source_count: int
    detached_count: int
    checkpoint_digest: str
    history_digest: str

    def summary(self) -> dict[str, Any]:
        return {
            "checkpoint_digest": self.checkpoint_digest,
            "history_digest": self.history_digest,
            "source_count": self.source_count,
            "detached_count": self.detached_count,
            "length": self.journal.length,
            "head_hash": self.journal.head_hash,
            "retained_count": len(self.journal.entries),
        }

    @property
    def plan_digest(self) -> str:
        return _digest(self.summary())

    def checkpoint(self) -> dict[str, Any]:
        return self.journal.encode()


def prepare_saga_audit_migration(
    checkpoint: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> SagaAuditMigration:
    """Verify complete history and follow the sole chain selected by a v1 head.

    Independent historical roots remain in the append-only log. A fork anywhere
    on the selected chain, missing ancestry, or corrupted detached history holds
    recovery. This path never guesses a head from row order or maximum sequence.
    """
    length, head = checkpoint.get("length"), checkpoint.get("head_hash")
    if (
        set(checkpoint) != {"schema_version", "length", "head_hash"}
        or checkpoint.get("schema_version") != "1.0.0"
        or type(length) is not int
        or length < 1
        or not _is_hash(head)
    ):
        raise AuditChainError("reviewed migration requires a nonempty valid v1 checkpoint")
    entries: dict[str, AuditEntry] = {}
    children: dict[str, list[AuditEntry]] = {}
    for record in records:
        entry = _decode_entry({key: record[key] for key in _ENTRY_FIELDS if key in record})
        if record.get("actor") != "Saga" or record.get("action_kind") != "audit.record":
            raise AuditChainError("reviewed migration requires only Saga audit records")
        if "payload" not in record or _digest(record["payload"]) != entry.payload_digest:
            raise AuditChainError("legacy audit payload digest mismatch")
        if entry.entry_hash not in (entry_hash(entry), entry_hash(entry, legacy=True)):
            raise AuditChainError("legacy audit entry hash mismatch")
        if entry.entry_hash in entries:
            raise AuditChainError("legacy audit history contains duplicate entry hashes")
        entries[entry.entry_hash] = entry
        children.setdefault(entry.prev_hash, []).append(entry)
    for entry in entries.values():
        parent = entries.get(entry.prev_hash)
        if entry.seq == 0:
            if entry.prev_hash != _GENESIS_HASH:
                raise AuditChainError("legacy audit root is invalid")
        elif parent is None or parent.seq != entry.seq - 1:
            raise AuditChainError("legacy audit history has missing or inconsistent ancestry")
    anchor = entries.get(head)
    if anchor is None or anchor.seq != length - 1:
        raise AuditChainError("legacy audit checkpoint has no matching history")
    selected: list[AuditEntry] = []
    current = anchor
    while True:
        selected.append(current)
        if current.seq == 0:
            break
        current = entries[current.prev_hash]
    selected.reverse()
    for entry in selected[:-1]:
        if len(children.get(entry.entry_hash, ())) != 1:
            raise AuditChainError("selected legacy audit history contains a fork")
    while descendants := children.get(selected[-1].entry_hash):
        if len(descendants) != 1:
            raise AuditChainError("selected legacy audit history contains a fork")
        selected.append(descendants[0])
    verify_entries(selected, base_length=0, base_hash=_GENESIS_HASH)
    retained = tuple(selected[-AUDIT_JOURNAL_LIMIT:])
    journal = AuditJournal(
        revision=1,
        base_length=retained[0].seq,
        base_hash=retained[0].prev_hash,
        entries=retained,
    )
    journal.encode()
    return SagaAuditMigration(
        journal=journal,
        source_count=len(records),
        detached_count=len(records) - len(selected),
        checkpoint_digest=_digest(checkpoint),
        history_digest=_digest([entry.entry_hash for entry in entries.values()]),
    )
