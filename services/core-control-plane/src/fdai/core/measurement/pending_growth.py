"""Bounded, non-authoritative retry outbox for deferred pattern evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fdai.core.measurement.pattern_growth import OutcomeRecord
from fdai.shared.providers.state_store import StateStore

_KEY = "measurement:pattern_growth:pending:v1"


def record_key(record: OutcomeRecord) -> str:
    return hashlib.sha256(
        json.dumps(_encode(record), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _encode(record: OutcomeRecord) -> dict[str, Any]:
    return {**asdict(record), "observed_at": record.observed_at.isoformat()}


class PendingPatternGrowth:
    """Persist only source references, never embeddings or reusable action payloads.

    The bounded index and its audit change together through StateStore CAS. A
    writer in a different database is idempotent, not part of this transaction.
    """

    def __init__(self, store: StateStore, *, capacity: int = 1_000) -> None:
        if capacity < 1 or capacity > 1_000:
            raise ValueError("pending growth capacity MUST be between 1 and 1000")
        self._store = store
        self._capacity = capacity

    async def records(self) -> tuple[OutcomeRecord, ...]:
        stored = await self._store.read_state(_KEY)
        state = stored or {}
        work = state.get("work", {})
        return tuple(
            OutcomeRecord(
                **{
                    **raw["record"],
                    "observed_at": datetime.fromisoformat(raw["record"]["observed_at"]),
                }
            )
            for _, raw in sorted(
                work.items(),
                key=lambda item: (
                    item[1].get("attempt_revision", 0),
                    item[1]["last_attempt_at"],
                    item[0],
                ),
            )
        )

    async def defer(self, record: OutcomeRecord, audit: Mapping[str, Any]) -> None:
        await self._change(record, audit, remove=False)

    async def finish(self, record: OutcomeRecord, audit: Mapping[str, Any]) -> None:
        await self._change(record, audit, remove=True)

    async def _change(
        self,
        record: OutcomeRecord,
        audit: Mapping[str, Any],
        *,
        remove: bool,
    ) -> None:
        key = record_key(record)
        for _ in range(8):
            stored = await self._store.read_state(_KEY)
            state = stored or {}
            revision = int(state.get("revision", 0))
            work = dict(state.get("work", {}))
            if remove:
                if key not in work:
                    await self._store.append_audit_entry(audit)
                    return
                del work[key]
            else:
                if key not in work and len(work) >= self._capacity:
                    raise RuntimeError(
                        "pending pattern growth capacity reached; source unacknowledged"
                    )
                work[key] = {
                    "record": _encode(record),
                    "last_attempt_at": audit["recorded_at"],
                    "attempt_revision": revision + 1,
                }
            value = {"revision": revision + 1, "work": work}
            applied = (
                await self._store.write_state_with_audit_if_absent(_KEY, value, audit)
                if stored is None
                else await self._store.compare_and_set_state_with_audit(
                    _KEY, value, expected_revision=revision, audit_entry=audit
                )
            )
            if applied:
                return
        raise RuntimeError("pending pattern growth revision conflict; source unacknowledged")
