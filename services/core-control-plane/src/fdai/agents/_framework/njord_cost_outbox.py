"""Durable and in-memory outbox for Njord cost-anomaly publications."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Any, Literal

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bounded import BoundedLruSet
from fdai.shared.providers.cost_governance import CostAnalysisSample
from fdai.shared.providers.state_store import StateStore

COST_ANOMALY_OUTBOX_PREFIX = "pantheon/njord/cost-anomaly-outbox/"
ACCEPTED_COST_SAMPLE_PREFIX = "pantheon/njord/accepted-samples/"
CostAnomalyOutboxState = Literal["pending", "published"]

if TYPE_CHECKING:
    from collections import OrderedDict as OrderedDictType


@dataclass(frozen=True, slots=True)
class CostAnomalyOutboxRecord:
    state: CostAnomalyOutboxState
    sample_key: str
    sample_digest: str
    scope_id: str
    observed_at: str
    pending_since: str
    payload: dict[str, Any]
    revision: int


class CostAnomalyOutbox:
    """Store retryable cost-anomaly publications outside the base proposal FIFO."""

    def __init__(
        self,
        *,
        state_store: StateStore | None,
        max_pending: int,
        retain_published: int,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending MUST be >= 1")
        if retain_published < 1:
            raise ValueError("retain_published MUST be >= 1")
        self._state_store = state_store
        self._max_pending = max_pending
        self._retain_published = retain_published
        self._memory: OrderedDict[str, CostAnomalyOutboxRecord] = OrderedDict()

    async def read(self, sample_key: str) -> CostAnomalyOutboxRecord | None:
        if self._state_store is None:
            record = self._memory.get(sample_key)
            if record is not None:
                self._memory.move_to_end(sample_key)
            return record
        raw = await self._state_store.read_state(cost_anomaly_outbox_key(sample_key))
        return _record_from_mapping(raw) if raw is not None else None

    async def persist_pending(
        self,
        *,
        sample_key: str,
        sample_digest: str,
        scope_id: str,
        observed_at: str,
        pending_since: str,
        payload: Mapping[str, Any],
    ) -> bool:
        existing = await self.read(sample_key)
        if existing is not None:
            return True
        if await self._pending_count() >= self._max_pending:
            return False
        record = CostAnomalyOutboxRecord(
            state="pending",
            sample_key=sample_key,
            sample_digest=sample_digest,
            scope_id=scope_id,
            observed_at=observed_at,
            pending_since=pending_since,
            payload=dict(payload),
            revision=1,
        )
        if self._state_store is None:
            self._memory[sample_key] = record
            return True
        created = await self._state_store.write_state_if_absent(
            cost_anomaly_outbox_key(sample_key),
            _record_to_mapping(record),
        )
        return created or await self.read(sample_key) is not None

    async def pending(self, *, limit: int) -> tuple[CostAnomalyOutboxRecord, ...]:
        if limit < 1:
            raise ValueError("limit MUST be >= 1")
        if self._state_store is None:
            records = tuple(record for record in self._memory.values() if record.state == "pending")
        else:
            rows = await self._state_store.read_states(
                COST_ANOMALY_OUTBOX_PREFIX,
                limit=max(self._max_pending + self._retain_published, limit),
            )
            records = tuple(
                record for row in rows if (record := _record_from_mapping(row)).state == "pending"
            )
        return tuple(sorted(records, key=lambda item: item.pending_since))[:limit]

    async def mark_published(self, record: CostAnomalyOutboxRecord) -> None:
        published = CostAnomalyOutboxRecord(
            state="published",
            sample_key=record.sample_key,
            sample_digest=record.sample_digest,
            scope_id=record.scope_id,
            observed_at=record.observed_at,
            pending_since=record.pending_since,
            payload=dict(record.payload),
            revision=record.revision + 1,
        )
        if self._state_store is None:
            self._memory[record.sample_key] = published
            self._memory.move_to_end(record.sample_key)
            return
        await self._state_store.write_state(
            cost_anomaly_outbox_key(record.sample_key),
            _record_to_mapping(published),
        )

    async def compact_published(self) -> int:
        if self._state_store is None:
            published = [key for key, record in self._memory.items() if record.state == "published"]
            expired = published[: max(0, len(published) - self._retain_published)]
            for key in expired:
                self._memory.pop(key, None)
            return len(expired)
        rows = await self._state_store.read_states(
            COST_ANOMALY_OUTBOX_PREFIX,
            limit=self._max_pending + self._retain_published * 2,
        )
        durable_published = [
            record for row in rows if (record := _record_from_mapping(row)).state == "published"
        ]
        expired_records = durable_published[self._retain_published :]
        deleted = 0
        for record in expired_records:
            if await self._state_store.delete_state(cost_anomaly_outbox_key(record.sample_key)):
                deleted += 1
        return deleted

    async def _pending_count(self) -> int:
        if self._state_store is None:
            return sum(1 for record in self._memory.values() if record.state == "pending")
        rows = await self._state_store.read_states(
            COST_ANOMALY_OUTBOX_PREFIX,
            limit=self._max_pending,
        )
        return sum(1 for row in rows if _record_from_mapping(row).state == "pending")


def cost_anomaly_outbox_key(sample_key: str) -> str:
    return COST_ANOMALY_OUTBOX_PREFIX + hashlib.sha256(sample_key.encode()).hexdigest()


def accepted_cost_sample_key(sample_key: str) -> str:
    return ACCEPTED_COST_SAMPLE_PREFIX + hashlib.sha256(sample_key.encode()).hexdigest()


class CostAnomalyOutboxMixin(Agent):
    """Njord mixin for retrying cost-anomaly publications through its own outbox."""

    _state_store: StateStore | None
    _cost_anomaly_outbox: CostAnomalyOutbox
    _accepted_sample_keys: BoundedLruSet[str]
    _accepted_sample_digests: OrderedDictType[str, str]
    _accepted_sample_retain_limit: int
    _cost_anomaly_outbox_redrive_limit: int

    if TYPE_CHECKING:

        async def _publish_proposal(self, topic: str, payload: dict[str, Any]) -> bool: ...

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def _complete_sample_projection(
        self,
        *,
        sample_key: str,
        sample_digest: str,
        scope_id: str,
        observed_at: str,
    ) -> None:
        if self._state_store is not None:
            await self._state_store.write_state(
                accepted_cost_sample_key(sample_key),
                {
                    "schema_version": "1.0.0",
                    "revision": 2,
                    "state": "completed",
                    "sample_key": sample_key,
                    "sample_digest": sample_digest,
                    "scope_id": scope_id,
                    "observed_at": observed_at,
                },
            )
        self._accepted_sample_keys.add(sample_key)
        self._accepted_sample_digests[sample_key] = sample_digest
        self._accepted_sample_digests.move_to_end(sample_key)
        while len(self._accepted_sample_digests) > self._accepted_sample_retain_limit:
            self._accepted_sample_digests.popitem(last=False)
        if self._state_store is not None:
            await self._state_store.delete_states_beyond(
                ACCEPTED_COST_SAMPLE_PREFIX,
                retain_newest=self._accepted_sample_retain_limit,
            )

    async def _store_pending_cost_anomaly(
        self,
        sample_key: str,
        sample: CostAnalysisSample,
        *,
        sample_digest: str,
        payload: dict[str, Any],
    ) -> None:
        observed_at = sample.observed_at.astimezone(UTC).isoformat()
        stored = await self._cost_anomaly_outbox.persist_pending(
            sample_key=sample_key,
            sample_digest=sample_digest,
            scope_id=sample.scope_id,
            observed_at=observed_at,
            pending_since=observed_at,
            payload=payload,
        )
        self.record_behavior(
            "cost_anomaly:publication_pending" if stored else "cost_anomaly:outbox_full"
        )

    async def maintenance_tick(self) -> None:
        await super().maintenance_tick()
        redriven = await self._redrive_pending_cost_anomalies()
        if redriven:
            self.record_behavior("cost_anomaly:redriven", redriven)

    async def _redrive_pending_cost_anomalies(self) -> int:
        redriven = 0
        for record in await self._cost_anomaly_outbox.pending(
            limit=self._cost_anomaly_outbox_redrive_limit,
        ):
            if not await self._publish_proposal("object.cost-anomaly", dict(record.payload)):
                break
            await self._cost_anomaly_outbox.mark_published(record)
            await self._complete_sample_projection(
                sample_key=record.sample_key,
                sample_digest=record.sample_digest,
                scope_id=record.scope_id,
                observed_at=record.observed_at,
            )
            redriven += 1
        if redriven:
            await self._cost_anomaly_outbox.compact_published()
        return redriven


def _record_to_mapping(record: CostAnomalyOutboxRecord) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": record.revision,
        "state": record.state,
        "sample_key": record.sample_key,
        "sample_digest": record.sample_digest,
        "scope_id": record.scope_id,
        "observed_at": record.observed_at,
        "pending_since": record.pending_since,
        "payload": dict(record.payload),
    }


def _record_from_mapping(raw: Mapping[str, Any]) -> CostAnomalyOutboxRecord:
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Njord cost-anomaly outbox payload is malformed")
    state = raw.get("state")
    if state not in {"pending", "published"}:
        raise ValueError("Njord cost-anomaly outbox state is malformed")
    return CostAnomalyOutboxRecord(
        state=state,
        sample_key=str(raw.get("sample_key") or ""),
        sample_digest=str(raw.get("sample_digest") or ""),
        scope_id=str(raw.get("scope_id") or ""),
        observed_at=str(raw.get("observed_at") or ""),
        pending_since=str(raw.get("pending_since") or ""),
        payload=dict(payload),
        revision=int(raw.get("revision") or 1),
    )


__all__ = [
    "ACCEPTED_COST_SAMPLE_PREFIX",
    "COST_ANOMALY_OUTBOX_PREFIX",
    "CostAnomalyOutbox",
    "CostAnomalyOutboxMixin",
    "CostAnomalyOutboxRecord",
    "accepted_cost_sample_key",
    "cost_anomaly_outbox_key",
]
