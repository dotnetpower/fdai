"""Replica-safe Saga audit appends and bounded verified local projections."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from fdai.agents._framework.adapters import AuditChainError, AuditEntry, _digest
from fdai.agents._framework.audit_chain_journal import (
    AUDIT_CHECKPOINT_KEY,
    AuditJournal,
    entry_hash,
    load_journal,
    verify_entries,
)
from fdai.shared.providers.state_store import StateStore

_APPEND_DEADLINE_SECONDS = 2.0


async def rehydrate_audit_entries(store: StateStore) -> list[AuditEntry]:
    """Restore the retained verified window, not complete historical replay."""
    async with asyncio.timeout(2):
        for _ in range(8):
            journal = await load_journal(store)
            if journal is not None:
                return list(journal.entries)
    raise AuditChainError("durable audit initialization contention budget exhausted")


@dataclass
class StateStoreAuditChainAdapter:
    store: StateStore
    entries: list[AuditEntry]
    durable: bool = True

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.entries = []
        self._append_lock = asyncio.Lock()
        self._base_length = 0
        self._base_hash = "0" * 64
        self._sealed_head_hash = "0" * 64
        self._sealed_length = 0
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
        """Atomically append a shared revision before exposing a bounded mirror.

        Eight conflicts or two seconds hold the write without a cached-head
        fallback. The mirror and correlation index cover at most 512 entries.
        """
        snapshot = deepcopy(payload)
        payload_digest = _digest(snapshot)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _APPEND_DEADLINE_SECONDS
        try:
            async with asyncio.timeout(_APPEND_DEADLINE_SECONDS):
                await self._append_lock.acquire()
        except TimeoutError as exc:
            raise AuditChainError("durable audit append deadline exceeded") from exc
        try:
            for _ in range(8):
                if loop.time() >= deadline:
                    raise AuditChainError("durable audit append deadline exceeded")
                journal = await load_journal(self.store)
                if journal is None:
                    continue
                entry = AuditEntry(
                    seq=journal.length,
                    prev_hash=journal.head_hash,
                    entry_hash="",
                    principal=principal,
                    topic=topic,
                    correlation_id=correlation_id,
                    payload_digest=payload_digest,
                )
                entry = replace(entry, entry_hash=entry_hash(entry))
                advanced = journal.advanced(entry)
                if loop.time() >= deadline:
                    raise AuditChainError("durable audit append deadline exceeded")
                committed = await self.store.compare_and_set_state_with_audit(
                    AUDIT_CHECKPOINT_KEY,
                    advanced.encode(),
                    expected_revision=journal.revision,
                    audit_entry={
                        "actor": "Saga",
                        "action_kind": "audit.record",
                        "seq": entry.seq,
                        "prev_hash": entry.prev_hash,
                        "entry_hash": entry.entry_hash,
                        "principal": principal,
                        "topic": topic,
                        "correlation_id": correlation_id,
                        "payload_digest": payload_digest,
                        "payload": snapshot,
                    },
                )
                if committed:
                    self._install(advanced)
                    return entry
        finally:
            self._append_lock.release()
        raise AuditChainError("durable audit append contention budget exhausted")

    def _install(self, journal: AuditJournal) -> None:
        self.entries = list(journal.entries)
        self._base_length, self._base_hash = journal.base_length, journal.base_hash
        self._sealed_length, self._sealed_head_hash = journal.length, journal.head_hash
        self._correlation_index = {}
        for entry in self.entries:
            self._correlation_index.setdefault(entry.correlation_id, []).append(entry)

    def verify(self, *, full: bool = False) -> None:
        if full and self._base_length:
            raise AuditChainError(
                "full audit history is unavailable in the bounded local projection"
            )
        verify_entries(self.entries, base_length=self._base_length, base_hash=self._base_hash)
        self.last_verify_visit_count = len(self.entries)
        if self._base_length + len(self.entries) != self._sealed_length:
            raise AuditChainError("chain length mismatch")
        actual_head = self.entries[-1].entry_hash if self.entries else self._base_hash
        if actual_head != self._sealed_head_hash:
            raise AuditChainError("chain head mismatch")

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        """Return retained correlation entries, not complete historical replay."""
        return list(self._correlation_index.get(correlation_id, ()))


__all__ = ["StateStoreAuditChainAdapter", "rehydrate_audit_entries"]
