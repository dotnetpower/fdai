"""Bounded shared Saga head and quiesced legacy-history migration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, TypeGuard

from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.shared.providers.state_store import (
    StateStore,
    StateStoreAuditChainReader,
    StateStoreAuditChainWindowReader,
    StateStoreAuditReader,
)

AUDIT_CHECKPOINT_KEY = "pantheon/saga/audit-chain/verified-head"
AUDIT_JOURNAL_LIMIT = 512
_GENESIS_HASH = "0" * 64
_JOURNAL_BYTE_LIMIT = 512 * 1_024
_ENTRY_FIELDS = frozenset(
    {"seq", "prev_hash", "entry_hash", "principal", "topic", "correlation_id", "payload_digest"}
)
_JOURNAL_FIELDS = frozenset(
    {"schema_version", "revision", "base_length", "base_hash", "entries", "content_digest"}
)


def entry_hash(entry: AuditEntry, *, legacy: bool = False) -> str:
    body = asdict(entry)
    del body["entry_hash"]
    if legacy:
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
    return _digest(body)


def _is_hash(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decode_entry(raw: Mapping[str, Any]) -> AuditEntry:
    if (
        set(raw) != _ENTRY_FIELDS
        or type(raw.get("seq")) is not int
        or raw["seq"] < 0
        or any(
            not _is_hash(raw.get(field)) for field in ("prev_hash", "entry_hash", "payload_digest")
        )
        or any(
            not isinstance(raw.get(field), str)
            for field in ("principal", "topic", "correlation_id")
        )
    ):
        raise AuditChainError("durable audit journal entry is malformed")
    return AuditEntry(**dict(raw))


def verify_entries(entries: Sequence[AuditEntry], *, base_length: int, base_hash: str) -> None:
    previous = base_hash
    for expected_seq, entry in enumerate(entries, start=base_length):
        if entry.seq != expected_seq or entry.prev_hash != previous:
            raise AuditChainError("durable audit chain sequence or previous hash is not contiguous")
        if entry.entry_hash not in (entry_hash(entry), entry_hash(entry, legacy=True)):
            raise AuditChainError(f"entry hash mismatch at seq {entry.seq}")
        previous = entry.entry_hash


@dataclass(frozen=True)
class AuditJournal:
    revision: int
    base_length: int
    base_hash: str
    entries: tuple[AuditEntry, ...]

    @property
    def length(self) -> int:
        return self.base_length + len(self.entries)

    @property
    def head_hash(self) -> str:
        return self.entries[-1].entry_hash if self.entries else self.base_hash

    def encode(self, *, compact: bool = False) -> dict[str, Any]:
        if compact:
            # A small head must not bypass the complete recent-window admission budget.
            self.encode()
        entries = self.entries[-1:] if compact else self.entries
        base_length = self.length - len(entries)
        base_hash = entries[0].prev_hash if entries else self.base_hash
        body = {
            "schema_version": "3.0.0" if compact else "2.0.0",
            "revision": self.revision,
            "base_length": base_length,
            "base_hash": base_hash,
            "entries": [asdict(entry) for entry in entries],
        }
        stored = {**body, "content_digest": _digest(body)}
        if len(json.dumps(stored, ensure_ascii=True).encode("utf-8")) > _JOURNAL_BYTE_LIMIT:
            raise AuditChainError("durable audit journal exceeds its byte budget")
        return stored

    def advanced(self, entry: AuditEntry) -> AuditJournal:
        retained = (*self.entries, entry)
        base_length, base_hash = self.base_length, self.base_hash
        if len(retained) > AUDIT_JOURNAL_LIMIT:
            base_length, base_hash = retained[0].seq + 1, retained[0].entry_hash
            retained = retained[1:]
        return AuditJournal(self.revision + 1, base_length, base_hash, retained)


def _decode_journal(stored: Mapping[str, Any]) -> AuditJournal:
    revision, base_length, base_hash = (
        stored.get("revision"),
        stored.get("base_length"),
        stored.get("base_hash"),
    )
    raw_entries = stored.get("entries")
    if (
        set(stored) != _JOURNAL_FIELDS
        or stored.get("schema_version") not in ("2.0.0", "3.0.0")
        or type(revision) is not int
        or revision < 1
        or type(base_length) is not int
        or base_length < 0
        or not _is_hash(base_hash)
        or (base_length == 0 and base_hash != _GENESIS_HASH)
        or not isinstance(raw_entries, list)
        or len(raw_entries) > AUDIT_JOURNAL_LIMIT
        or (stored.get("schema_version") == "3.0.0" and len(raw_entries) > 1)
        or (base_length > 0 and not raw_entries)
        or any(not isinstance(raw, Mapping) for raw in raw_entries)
    ):
        raise AuditChainError("durable audit journal is malformed")
    journal = AuditJournal(
        revision, base_length, base_hash, tuple(_decode_entry(raw) for raw in raw_entries)
    )
    body = {key: value for key, value in stored.items() if key != "content_digest"}
    if _digest(body) != stored.get("content_digest"):
        raise AuditChainError("durable audit journal content digest mismatch")
    verify_entries(journal.entries, base_length=journal.base_length, base_hash=journal.base_hash)
    return journal


async def _load_window(store: StateStore, journal: AuditJournal) -> AuditJournal:
    if not isinstance(store, StateStoreAuditChainWindowReader):
        raise AuditChainError("compact audit checkpoint requires the bounded window reader")
    if not journal.length:
        return journal
    start = max(0, journal.length - AUDIT_JOURNAL_LIMIT)
    records = await store.read_audit_chain_window(
        start_seq=start, end_seq=journal.length, head_hash=journal.head_hash
    )
    if len(records) != journal.length - start:
        raise AuditChainError("compact audit recovery window is incomplete or duplicated")
    entries = []
    for record in records:
        entry = _decode_entry({key: record[key] for key in _ENTRY_FIELDS if key in record})
        if "payload" in record and _digest(record["payload"]) != entry.payload_digest:
            raise AuditChainError("compact audit recovery payload digest mismatch")
        entries.append(entry)
    base_hash = entries[0].prev_hash
    if start == 0 and base_hash != _GENESIS_HASH:
        raise AuditChainError("compact audit recovery genesis hash mismatch")
    verify_entries(entries, base_length=start, base_hash=base_hash)
    if entries[-1].entry_hash != journal.head_hash:
        raise AuditChainError("compact audit recovery head mismatch")
    restored = AuditJournal(journal.revision, start, base_hash, tuple(entries))
    restored.encode()
    return restored


async def supports_compact_checkpoint(store: StateStore) -> bool:
    return (
        isinstance(store, StateStoreAuditChainWindowReader)
        and await store.supports_compact_audit_checkpoint()
    )


async def load_journal(store: StateStore, *, with_window: bool = False) -> AuditJournal | None:
    """Load a verified window; migration requires quiesced old writers.

    None means another replica won initialization; the caller must reload.
    Missing readers, incomplete history and inconsistent checkpoints hold writes.
    """
    stored = await store.read_state(AUDIT_CHECKPOINT_KEY)
    if stored is not None and stored.get("schema_version") in ("2.0.0", "3.0.0"):
        journal = _decode_journal(stored)
        if stored["schema_version"] == "3.0.0":
            if not isinstance(store, StateStoreAuditChainWindowReader):
                raise AuditChainError("compact audit checkpoint requires the bounded window reader")
            if not await store.supports_compact_audit_checkpoint():
                raise AuditChainError("compact audit checkpoint requires canonical header storage")
            if with_window:
                return await _load_window(store, journal)
        return journal
    # The audit table is shared by every writer. Reading it unfiltered makes a fresh runtime
    # unable to start the chain once unrelated rows exceed the bound, so ask for chain rows only.
    if callable(getattr(store, "read_audit_chain_entries", None)) and isinstance(
        store, StateStoreAuditChainReader
    ):
        records, truncated = await store.read_audit_chain_entries(limit=AUDIT_JOURNAL_LIMIT)
    elif callable(getattr(store, "read_audit_entries", None)) and isinstance(
        store, StateStoreAuditReader
    ):
        records, truncated = await store.read_audit_entries(limit=AUDIT_JOURNAL_LIMIT)
    else:
        raise AuditChainError("durable audit history reader is required for legacy migration")
    if truncated:
        raise AuditChainError(
            "legacy audit history exceeds bounded migration; reviewed migration required"
        )
    restored: list[AuditEntry] = []
    for record in records:
        if _ENTRY_FIELDS.issubset(record) or (
            record.get("actor") == "Saga" and record.get("action_kind") == "audit.record"
        ):
            entry = _decode_entry(
                {key: value for key, value in record.items() if key in _ENTRY_FIELDS}
            )
            if "payload" in record and _digest(record["payload"]) != entry.payload_digest:
                raise AuditChainError("legacy audit payload digest mismatch")
            restored.append(entry)
    verify_entries(restored, base_length=0, base_hash=_GENESIS_HASH)
    if stored is not None:
        length, head_hash = stored.get("length"), stored.get("head_hash")
        if (
            set(stored) != {"schema_version", "length", "head_hash"}
            or stored.get("schema_version") != "1.0.0"
            or type(length) is not int
            or not 0 <= length <= len(restored)
            or not _is_hash(head_hash)
            or head_hash != (restored[length - 1].entry_hash if length else _GENESIS_HASH)
        ):
            raise AuditChainError(
                "durable audit checkpoint is inconsistent with complete legacy history"
            )
    journal = AuditJournal(1, 0, _GENESIS_HASH, tuple(restored))
    if stored is None:
        created = await store.write_state_if_absent(AUDIT_CHECKPOINT_KEY, journal.encode())
    else:
        created = await store.compare_and_set_state(
            AUDIT_CHECKPOINT_KEY, journal.encode(), expected_revision=0
        )
    return journal if created else None
