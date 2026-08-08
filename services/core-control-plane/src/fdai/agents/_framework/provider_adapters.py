"""Provider-backed adapters for pantheon agents.

Wave 2 shipped in-memory adapters
(:mod:`fdai.agents.adapters`) so tests could exercise agent behavior
without touching any backend. Real deployments wire the same agent
classes against the persistent provider Protocols in
:mod:`fdai.shared.providers`:

- :class:`StateStoreAuditChainAdapter` - lets Saga append to the real
  ``StateStore`` (Postgres in production, in-memory in tests).
- :class:`StateStoreKvAdapter` - lets Muninn read / write context on
  the same Protocol.

These adapters preserve the pantheon in-memory adapter's method shape
so agent code does not branch on backend.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.adapters import AuditEntry, _digest
from fdai.agents.thor import ActionRun
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)

# Distinctive one-key envelope used to round-trip a non-dict value through
# the Mapping-only StateStore contract. Using a reserved sentinel key (not
# a plausible user key like "value") lets ``get`` unwrap unambiguously.
_SCALAR_ENVELOPE_KEY = "__fdai_scalar__"


@dataclass
class StateStoreAuditChainAdapter:
    """Saga's audit chain, backed by ``StateStore.append_audit_entry``.

    The hash-linked chain contract stays identical to the in-memory
    version: ``seq``, ``prev_hash``, and ``entry_hash`` are computed
    the same way and the record is a plain dict handed to the Protocol.

    ``entries`` is a local snapshot cache used to compute the next
    ``prev_hash`` without a round-trip; a fork can override this class
    if the backing store already computes hash chains server-side.
    """

    store: StateStore
    entries: list[AuditEntry]
    durable: bool = True

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.entries = []

    async def append(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> AuditEntry:
        seq = len(self.entries)
        prev_hash = self.entries[-1].entry_hash if self.entries else "0" * 64
        payload_digest = _digest(payload)
        entry_hash = _digest(
            {
                "seq": seq,
                "prev_hash": prev_hash,
                "principal": principal,
                "topic": topic,
                "correlation_id": correlation_id,
                "payload_digest": payload_digest,
            }
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
        self.entries.append(entry)
        # Hand the concrete record to the provider; the Protocol only
        # cares about the mapping shape.
        await self.store.append_audit_entry(
            {
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
        return entry

    def verify(self) -> None:
        """Local chain verification (equivalent to in-memory adapter)."""
        prev = "0" * 64
        for i, entry in enumerate(self.entries):
            if entry.seq != i or entry.prev_hash != prev:
                from fdai.agents._framework.adapters import AuditChainError

                raise AuditChainError(
                    f"chain break at seq {i}: prev={entry.prev_hash!r} expected {prev!r}"
                )
            prev = entry.entry_hash

    def entries_for_correlation(self, correlation_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.correlation_id == correlation_id]


@dataclass
class StateStoreKvAdapter:
    """Muninn's context store, backed by ``StateStore.read_state`` /
    ``write_state``. Bucket + key are joined with ``|`` to form the
    Protocol key.
    """

    store: StateStore

    async def get(self, bucket: str, key: str) -> Any | None:
        value = await self.store.read_state(f"{bucket}|{key}")
        # Symmetric unwrap: a scalar written via ``put`` was wrapped in a
        # reserved one-key envelope; return the original scalar so the
        # round-trip is value-preserving (a dict written as-is is returned
        # unchanged because it lacks the sentinel key).
        if isinstance(value, Mapping) and set(value.keys()) == {_SCALAR_ENVELOPE_KEY}:
            return value[_SCALAR_ENVELOPE_KEY]
        return value

    async def put(self, bucket: str, key: str, value: Any) -> None:
        # StateStore expects a Mapping; wrap a non-dict in a reserved
        # one-key envelope so ``get`` can unwrap it back to the original
        # scalar (see :meth:`get`).
        stored: Mapping[str, Any]
        if isinstance(value, Mapping):
            stored = value
        else:
            stored = {_SCALAR_ENVELOPE_KEY: value}
        await self.store.write_state(f"{bucket}|{key}", stored)


@dataclass
class StateStoreActionRunStore:
    """Thor's ActionRun store, backed by ``StateStore.read_state`` /
    ``write_state``.

    ``StateStore`` exposes no key enumeration, so an index key tracks the
    set of in-flight correlation ids. Each run is stored under
    ``thor:run|<cid>``; the index under ``thor:active-index``. Terminal
    runs are removed from the index (the row may linger harmlessly).
    """

    store: StateStore
    index_key: str = "thor:active-index"
    run_prefix: str = "thor:run|"
    # Serializes the index read-modify-write so two concurrent save/delete
    # calls cannot lose an update (which would orphan an in-flight run so
    # it is never rehydrated after a restart). Single-replica correctness;
    # a multi-replica deployment needs store-level atomicity.
    _index_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def _read_index(self) -> list[str]:
        raw = await self.store.read_state(self.index_key)
        if not raw:
            return []
        ids = raw.get("ids", [])
        return [str(i) for i in ids]

    async def _write_index(self, ids: list[str]) -> None:
        await self.store.write_state(self.index_key, {"ids": ids})

    async def save(self, run: ActionRun) -> None:
        await self.store.write_state(f"{self.run_prefix}{run.correlation_id}", run.to_dict())
        async with self._index_lock:
            ids = await self._read_index()
            if run.correlation_id not in ids:
                ids.append(run.correlation_id)
                await self._write_index(ids)

    async def load_active(self) -> list[ActionRun]:
        runs: list[ActionRun] = []
        for cid in await self._read_index():
            raw = await self.store.read_state(f"{self.run_prefix}{cid}")
            if not raw:
                continue
            try:
                runs.append(ActionRun.from_dict(dict(raw)))
            except (KeyError, ValueError, TypeError):
                # A single corrupt / schema-drifted row MUST NOT abort the
                # whole rehydration (which would leave every in-flight run
                # unrecovered). Skip and log it; the rest still restore.
                _LOG.exception(
                    "action_run_rehydrate_skip_corrupt",
                    extra={"correlation_id": cid},
                )
        return runs

    async def delete(self, correlation_id: str) -> None:
        async with self._index_lock:
            ids = await self._read_index()
            if correlation_id in ids:
                ids.remove(correlation_id)
                await self._write_index(ids)


__all__ = [
    "StateStoreAuditChainAdapter",
    "StateStoreKvAdapter",
    "StateStoreActionRunStore",
]
