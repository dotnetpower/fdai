"""Durable outbox for Njord-owned optimization candidate publication."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fdai.shared.providers.state_store import StateStore

OPTIMIZATION_OUTBOX_PREFIX = "pantheon/njord/optimization-outbox/"
OptimizationOutboxState = Literal["pending", "published"]


@dataclass(frozen=True, slots=True)
class OptimizationOutboxRecord:
    state: OptimizationOutboxState
    candidate_key: str
    candidate_digest: str
    pending_since: str
    payload: dict[str, Any]
    revision: int


class OptimizationCandidateOutbox:
    def __init__(
        self,
        *,
        state_store: StateStore | None,
        max_pending: int = 512,
        retain_published: int = 512,
    ) -> None:
        self._state_store = state_store
        self._max_pending = max_pending
        self._retain_published = retain_published
        self._memory: OrderedDict[str, OptimizationOutboxRecord] = OrderedDict()

    async def claim(
        self,
        *,
        candidate_key: str,
        pending_since: str,
        payload: Mapping[str, Any],
    ) -> OptimizationOutboxRecord | None:
        digest = _payload_digest(payload)
        existing = await self.read(candidate_key)
        if existing is not None:
            if existing.candidate_digest != digest:
                raise ValueError("optimization candidate idempotency conflict")
            return existing
        if len(await self.pending(limit=self._max_pending)) >= self._max_pending:
            return None
        record = OptimizationOutboxRecord(
            state="pending",
            candidate_key=candidate_key,
            candidate_digest=digest,
            pending_since=pending_since,
            payload=dict(payload),
            revision=1,
        )
        if self._state_store is None:
            self._memory[candidate_key] = record
            return record
        created = await self._state_store.write_state_if_absent(
            _outbox_key(candidate_key),
            _mapping(record),
        )
        if created:
            return record
        winner = await self.read(candidate_key)
        if winner is None or winner.candidate_digest != digest:
            raise ValueError("optimization candidate idempotency conflict")
        return winner

    async def read(self, candidate_key: str) -> OptimizationOutboxRecord | None:
        if self._state_store is None:
            return self._memory.get(candidate_key)
        raw = await self._state_store.read_state(_outbox_key(candidate_key))
        return _record(raw) if raw is not None else None

    async def pending(self, *, limit: int) -> tuple[OptimizationOutboxRecord, ...]:
        if self._state_store is None:
            values = tuple(item for item in self._memory.values() if item.state == "pending")
        else:
            rows = await self._state_store.read_states(
                OPTIMIZATION_OUTBOX_PREFIX,
                limit=self._max_pending + self._retain_published,
            )
            values = tuple(item for row in rows if (item := _record(row)).state == "pending")
        return tuple(sorted(values, key=lambda item: item.pending_since))[:limit]

    async def mark_published(self, record: OptimizationOutboxRecord) -> None:
        published = OptimizationOutboxRecord(
            state="published",
            candidate_key=record.candidate_key,
            candidate_digest=record.candidate_digest,
            pending_since=record.pending_since,
            payload=dict(record.payload),
            revision=record.revision + 1,
        )
        if self._state_store is None:
            self._memory[record.candidate_key] = published
            self._memory.move_to_end(record.candidate_key)
            while len(self._memory) > self._retain_published:
                self._memory.popitem(last=False)
            return
        await self._state_store.write_state(_outbox_key(record.candidate_key), _mapping(published))
        await self._state_store.delete_states_beyond(
            OPTIMIZATION_OUTBOX_PREFIX,
            retain_newest=self._max_pending + self._retain_published,
        )


def _payload_digest(payload: Mapping[str, Any]) -> str:
    material = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(material).hexdigest()}"


def _outbox_key(candidate_key: str) -> str:
    return OPTIMIZATION_OUTBOX_PREFIX + hashlib.sha256(candidate_key.encode()).hexdigest()


def _mapping(record: OptimizationOutboxRecord) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": record.revision,
        "state": record.state,
        "candidate_key": record.candidate_key,
        "candidate_digest": record.candidate_digest,
        "pending_since": record.pending_since,
        "payload": dict(record.payload),
    }


def _record(raw: Mapping[str, Any]) -> OptimizationOutboxRecord:
    state = raw.get("state")
    payload = raw.get("payload")
    if state not in {"pending", "published"} or not isinstance(payload, dict):
        raise ValueError("Njord optimization outbox record is malformed")
    return OptimizationOutboxRecord(
        state=state,
        candidate_key=str(raw.get("candidate_key") or ""),
        candidate_digest=str(raw.get("candidate_digest") or ""),
        pending_since=str(raw.get("pending_since") or ""),
        payload=dict(payload),
        revision=int(raw.get("revision") or 1),
    )


__all__ = [
    "OPTIMIZATION_OUTBOX_PREFIX",
    "OptimizationCandidateOutbox",
    "OptimizationOutboxRecord",
]
