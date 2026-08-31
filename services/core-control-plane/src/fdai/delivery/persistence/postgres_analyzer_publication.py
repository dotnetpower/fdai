"""Durable analyzer publication suppression on the shared idempotency store."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from fdai.delivery.analyzer_tick import (
    AnalyzerPublicationClaim,
    AnalyzerPublicationClaimStatus,
)
from fdai.delivery.persistence.postgres_idempotency import (
    PostgresIdempotencyStore,
    PostgresIdempotencyStoreConfig,
)
from fdai.shared.providers.event_bus import PublishReceipt

_PREFIX = "analyzer-publication:"
_DEFAULT_LEASE_SECONDS = 600


class _ConditionalIdempotencyStore(Protocol):
    async def seen(self, key: str) -> Mapping[str, Any] | None: ...

    async def record(self, key: str, result: Mapping[str, Any]) -> bool: ...

    async def remove_if(self, key: str, expected: Mapping[str, Any]) -> bool: ...

    async def insert_or_replace_if(
        self,
        key: str,
        expected: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> bool: ...


class PostgresAnalyzerPublicationLedger:
    """Suppress repeated same-window publication across process restarts."""

    def __init__(
        self,
        *,
        config: PostgresIdempotencyStoreConfig | None = None,
        store: _ConditionalIdempotencyStore | None = None,
        lease_seconds: int = _DEFAULT_LEASE_SECONDS,
    ) -> None:
        if (config is None) == (store is None):
            raise ValueError("exactly one analyzer publication store binding is required")
        if not 1 <= lease_seconds <= 3_600:
            raise ValueError("analyzer publication lease_seconds MUST be in [1, 3600]")
        self._lease_seconds = lease_seconds
        if store is not None:
            self._store = store
            return
        if config is None:
            raise ValueError("analyzer publication store config is required")
        self._store = PostgresIdempotencyStore(config=config)

    async def claim(self, idempotency_key: str) -> AnalyzerPublicationClaim:
        now = datetime.now(tz=UTC)
        pending = self._new_pending(now)
        key = f"{_PREFIX}{idempotency_key}"
        if await self._store.record(key, pending):
            return _pending_claim(pending, AnalyzerPublicationClaimStatus.NEW)
        return await self._resolve_existing(key, now=now, allow_reclaim=True)

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        pending = _pending_record(claim)
        completed = {
            "state": "completed",
            "topic": receipt.topic,
            "partition": receipt.partition,
            "offset": receipt.offset,
        }
        key = f"{_PREFIX}{idempotency_key}"
        if await self._store.insert_or_replace_if(key, pending, completed):
            return
        if await self._store.seen(key) != completed:
            raise RuntimeError("analyzer publication receipt conflict")

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> None:
        pending = _pending_record(claim)
        key = f"{_PREFIX}{idempotency_key}"
        if await self._store.remove_if(key, pending):
            return
        existing = await self._store.seen(key)
        if existing is not None:
            raise RuntimeError("analyzer publication claim changed before release")

    def _new_pending(self, claimed_at: datetime) -> dict[str, Any]:
        return {
            "state": "pending",
            "token": str(uuid4()),
            "claimed_at": claimed_at.isoformat(),
        }

    async def _resolve_existing(
        self,
        key: str,
        *,
        now: datetime,
        allow_reclaim: bool,
    ) -> AnalyzerPublicationClaim:
        existing = await self._store.seen(key)
        if existing is None:
            raise RuntimeError("analyzer publication claim vanished after conflict")
        state = existing.get("state")
        if state == "completed":
            return AnalyzerPublicationClaim(
                status=AnalyzerPublicationClaimStatus.COMPLETED,
                receipt=_completed_receipt(existing),
            )
        pending = _pending_claim(existing, AnalyzerPublicationClaimStatus.IN_PROGRESS)
        if pending.claimed_at is None:
            raise RuntimeError("analyzer publication pending claim has no timestamp")
        age_seconds = (now - pending.claimed_at).total_seconds()
        if age_seconds < 0:
            raise RuntimeError("analyzer publication pending claim is from the future")
        if age_seconds < self._lease_seconds or not allow_reclaim:
            return pending
        replacement = self._new_pending(now)
        if await self._store.insert_or_replace_if(key, existing, replacement):
            return _pending_claim(replacement, AnalyzerPublicationClaimStatus.NEW)
        return await self._resolve_existing(key, now=now, allow_reclaim=False)


def _pending_claim(
    record: Mapping[str, Any],
    status: AnalyzerPublicationClaimStatus,
) -> AnalyzerPublicationClaim:
    if record.get("state") != "pending":
        raise RuntimeError("analyzer publication claim has an invalid state")
    token = record.get("token")
    claimed_at_raw = record.get("claimed_at")
    if not isinstance(token, str) or not token:
        raise RuntimeError("analyzer publication pending claim has no token")
    if not isinstance(claimed_at_raw, str):
        raise RuntimeError("analyzer publication pending claim has no timestamp")
    try:
        claimed_at = datetime.fromisoformat(claimed_at_raw)
    except ValueError as exc:
        raise RuntimeError("analyzer publication pending timestamp is invalid") from exc
    if claimed_at.tzinfo is None:
        raise RuntimeError("analyzer publication pending timestamp has no timezone")
    return AnalyzerPublicationClaim(
        status=status,
        token=token,
        claimed_at=claimed_at,
    )


def _pending_record(claim: AnalyzerPublicationClaim) -> dict[str, Any]:
    if (
        claim.status is not AnalyzerPublicationClaimStatus.NEW
        or claim.token is None
        or claim.claimed_at is None
    ):
        raise ValueError("analyzer publication completion requires a new token-owned claim")
    return {
        "state": "pending",
        "token": claim.token,
        "claimed_at": claim.claimed_at.isoformat(),
    }


def _completed_receipt(record: Mapping[str, Any]) -> PublishReceipt:
    topic = record.get("topic")
    partition = record.get("partition")
    offset = record.get("offset")
    if not isinstance(topic, str) or not topic:
        raise RuntimeError("completed analyzer publication has no topic")
    if isinstance(partition, bool) or not isinstance(partition, int) or partition < 0:
        raise RuntimeError("completed analyzer publication has an invalid partition")
    if offset is not None and (
        isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
    ):
        raise RuntimeError("completed analyzer publication has an invalid offset")
    return PublishReceipt(topic=topic, partition=partition, offset=offset)


__all__ = ["PostgresAnalyzerPublicationLedger"]
