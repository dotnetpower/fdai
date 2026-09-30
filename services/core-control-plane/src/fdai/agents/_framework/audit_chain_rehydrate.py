"""Restart helpers for provider-backed Saga audit chains."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.shared.providers.state_store import StateStore

_AUDIT_CHECKPOINT_KEY = "pantheon/saga/audit-chain/verified-head"
_AUDIT_CHECKPOINT_INTERVAL = 1_024
_AUDIT_REHYDRATE_PAGE_SIZE = 512


async def rehydrate_audit_entries(store: StateStore) -> list[AuditEntry]:
    """Return Saga entries restored from the last verified durable checkpoint."""

    audit_entries = getattr(store, "audit_entries", None)
    if audit_entries is None:
        return []
    checkpoint = await _read_checkpoint(store)
    start_seq = checkpoint.length
    prev_hash = checkpoint.head_hash
    restored: list[AuditEntry] = []
    records = tuple(audit_entries)
    for offset in range(start_seq, len(records), _AUDIT_REHYDRATE_PAGE_SIZE):
        page = records[offset : offset + _AUDIT_REHYDRATE_PAGE_SIZE]
        for record in page:
            entry = record.get("entry") if isinstance(record, Mapping) else None
            if not isinstance(entry, Mapping):
                raise RuntimeError("durable audit entry is malformed")
            if not _looks_like_saga_chain_entry(entry):
                continue
            restored_entry = _audit_entry_from_state(entry)
            if restored_entry.seq != len(restored) + start_seq:
                raise RuntimeError("durable audit chain sequence is not contiguous")
            if restored_entry.prev_hash != prev_hash:
                raise RuntimeError("durable audit hash chain verification failed")
            recomputed = _entry_hash(
                seq=restored_entry.seq,
                prev_hash=restored_entry.prev_hash,
                principal=restored_entry.principal,
                topic=restored_entry.topic,
                correlation_id=restored_entry.correlation_id,
                payload_digest=restored_entry.payload_digest,
            )
            if recomputed != restored_entry.entry_hash:
                raise RuntimeError("durable audit hash chain verification failed")
            prev_hash = restored_entry.entry_hash
            restored.append(restored_entry)
    if restored or checkpoint.length == len(records):
        return restored
    if not await store.verify_chain():
        raise RuntimeError("durable audit hash chain verification failed")
    for record in records:
        entry = record.get("entry") if isinstance(record, Mapping) else None
        if not isinstance(entry, Mapping):
            raise RuntimeError("durable audit entry is malformed")
        if not _looks_like_saga_chain_entry(entry):
            continue
        restored.append(_audit_entry_from_state(entry))
    return restored


def _looks_like_saga_chain_entry(entry: Mapping[str, Any]) -> bool:
    required = {"seq", "prev_hash", "entry_hash", "principal", "topic", "correlation_id"}
    if required.issubset(entry):
        return True
    if entry.get("action_kind") == "audit.record":
        raise RuntimeError("durable audit entry is malformed")
    return False


def _audit_entry_from_state(entry: Mapping[str, Any]) -> AuditEntry:
    try:
        return AuditEntry(
            seq=int(entry["seq"]),
            prev_hash=str(entry["prev_hash"]),
            entry_hash=str(entry["entry_hash"]),
            principal=str(entry["principal"]),
            topic=str(entry["topic"]),
            correlation_id=str(entry["correlation_id"]),
            payload_digest=str(entry["payload_digest"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("durable audit entry is malformed") from exc


def _entry_hash(
    *,
    seq: int,
    prev_hash: str,
    principal: str,
    topic: str,
    correlation_id: str,
    payload_digest: str,
) -> str:
    return _digest(
        {
            "seq": seq,
            "prev_hash": prev_hash,
            "principal": principal,
            "topic": topic,
            "correlation_id": correlation_id,
            "payload_digest": payload_digest,
        }
    )


@dataclass(frozen=True, slots=True)
class _AuditCheckpoint:
    length: int
    head_hash: str


async def _read_checkpoint(store: StateStore) -> _AuditCheckpoint:
    stored = await store.read_state(_AUDIT_CHECKPOINT_KEY)
    if stored is None:
        return _AuditCheckpoint(length=0, head_hash="0" * 64)
    length = stored.get("length")
    head_hash = stored.get("head_hash")
    if (
        stored.get("schema_version") != "1.0.0"
        or not isinstance(length, int)
        or isinstance(length, bool)
        or length < 0
        or not isinstance(head_hash, str)
        or len(head_hash) != 64
    ):
        raise RuntimeError("durable audit checkpoint is malformed")
    return _AuditCheckpoint(length=length, head_hash=head_hash)


async def _write_checkpoint(store: StateStore, *, length: int, head_hash: str) -> None:
    await store.write_state(
        _AUDIT_CHECKPOINT_KEY,
        {
            "schema_version": "1.0.0",
            "length": length,
            "head_hash": head_hash,
        },
    )


@dataclass
class StateStoreAuditChainAdapter:
    store: StateStore
    entries: list[AuditEntry]
    durable: bool = True

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.entries = []
        self._append_lock = asyncio.Lock()
        self._rehydrated = False
        self._sealed_head_hash = "0" * 64
        self._sealed_length = 0
        self._verified_head_hash = "0" * 64
        self._verified_length = 0
        self._correlation_index: dict[str, list[AuditEntry]] = {}
        self.last_verify_visit_count = 0

    async def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry:
        async with self._append_lock:
            await self._rehydrate_head()
            seq = self._sealed_length
            prev_hash = self._sealed_head_hash
            payload_digest = _digest(payload)
            entry_hash = _entry_hash(
                seq=seq,
                prev_hash=prev_hash,
                principal=principal,
                topic=topic,
                correlation_id=correlation_id,
                payload_digest=payload_digest,
            )
            entry = AuditEntry(
                seq=seq,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
                principal=principal,
                topic=topic,
                correlation_id=correlation_id,
                payload_digest=payload_digest,
            )
            await self.store.append_audit_entry(
                {
                    "actor": "Saga",
                    "action_kind": "audit.record",
                    "seq": seq,
                    "prev_hash": prev_hash,
                    "entry_hash": entry_hash,
                    "principal": principal,
                    "topic": topic,
                    "correlation_id": correlation_id,
                    "payload_digest": payload_digest,
                    "payload": payload,
                }
            )
            self.entries.append(entry)
            self._correlation_index.setdefault(correlation_id, []).append(entry)
            self._sealed_head_hash = entry.entry_hash
            self._sealed_length = seq + 1
            if self._sealed_length % _AUDIT_CHECKPOINT_INTERVAL == 0:
                self.verify()
                await _write_checkpoint(
                    self.store,
                    length=self._verified_length,
                    head_hash=self._verified_head_hash,
                )
            return entry

    async def _rehydrate_head(self) -> None:
        if self._rehydrated:
            return
        self.entries = await rehydrate_audit_entries(self.store)
        checkpoint = await _read_checkpoint(self.store)
        self._sealed_head_hash = (
            self.entries[-1].entry_hash if self.entries else checkpoint.head_hash
        )
        self._sealed_length = checkpoint.length + len(self.entries)
        self._verified_head_hash = checkpoint.head_hash
        self._verified_length = checkpoint.length
        self._correlation_index = {}
        for entry in self.entries:
            self._correlation_index.setdefault(entry.correlation_id, []).append(entry)
        self.verify()
        await _write_checkpoint(
            self.store,
            length=self._verified_length,
            head_hash=self._verified_head_hash,
        )
        self._rehydrated = True

    def verify(self, *, full: bool = False) -> None:
        if full:
            prev = "0" * 64
            expected_seq = 0
        else:
            prev = self._verified_head_hash
            expected_seq = self._verified_length
        visited = 0
        for entry in self.entries:
            if entry.seq < expected_seq:
                continue
            visited += 1
            i = entry.seq
            if entry.seq != i or entry.prev_hash != prev:
                raise AuditChainError(
                    f"chain break at seq {i}: prev={entry.prev_hash!r} expected {prev!r}"
                )
            recomputed = _entry_hash(
                seq=entry.seq,
                prev_hash=entry.prev_hash,
                principal=entry.principal,
                topic=entry.topic,
                correlation_id=entry.correlation_id,
                payload_digest=entry.payload_digest,
            )
            if recomputed != entry.entry_hash:
                raise AuditChainError(f"entry hash mismatch at seq {i}")
            prev = entry.entry_hash
        self.last_verify_visit_count = visited
        actual_length = self.entries[-1].seq + 1 if self.entries else self._verified_length
        if actual_length != self._sealed_length:
            raise AuditChainError(
                f"chain length mismatch: got {actual_length!r}, expected {self._sealed_length!r}"
            )
        if prev != self._sealed_head_hash:
            raise AuditChainError("chain head mismatch")
        self._verified_length = self._sealed_length
        self._verified_head_hash = prev

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return list(self._correlation_index.get(correlation_id, ()))


__all__ = ["StateStoreAuditChainAdapter", "rehydrate_audit_entries"]
