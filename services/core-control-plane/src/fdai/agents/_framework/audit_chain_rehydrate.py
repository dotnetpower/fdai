"""Restart helpers for provider-backed Saga audit chains."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.shared.providers.state_store import StateStore


async def rehydrate_audit_entries(store: StateStore) -> list[AuditEntry]:
    """Return Saga adapter entries restored from a verified durable chain."""

    if not await store.verify_chain():
        raise RuntimeError("durable audit hash chain verification failed")
    audit_entries = getattr(store, "audit_entries", None)
    if audit_entries is None:
        return []
    restored: list[AuditEntry] = []
    for record in audit_entries:
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
            seq = len(self.entries)
            prev_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
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
            self._sealed_head_hash = entry.entry_hash
            self._sealed_length = len(self.entries)
            return entry

    async def _rehydrate_head(self) -> None:
        if self._rehydrated:
            return
        self.entries = await rehydrate_audit_entries(self.store)
        self._sealed_head_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
        self._sealed_length = len(self.entries)
        self.verify()
        self._rehydrated = True

    def verify(self) -> None:
        prev = "0" * 64
        for i, entry in enumerate(self.entries):
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
        if len(self.entries) != self._sealed_length:
            raise AuditChainError(
                f"chain length mismatch: got {len(self.entries)!r}, "
                f"expected {self._sealed_length!r}"
            )
        if prev != self._sealed_head_hash:
            raise AuditChainError("chain head mismatch")

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.correlation_id == correlation_id]


__all__ = ["StateStoreAuditChainAdapter", "rehydrate_audit_entries"]
