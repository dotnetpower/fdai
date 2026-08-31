"""Durable analyzer publication suppression on the shared idempotency store.

The ledger records four states for one publication key. ``pending`` means a
tick owns the key and has attempted no send, so an expired lease is safely
reclaimable. ``sending`` means a send was attempted before any outcome was
known, so an expired lease resolves to ``uncertain`` instead of a fresh claim:
republishing it would duplicate a record the broker may already hold.
``uncertain`` requires reconciliation before any retry, and ``completed``
carries the durable broker receipt that suppresses every later attempt.
"""

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
_MAX_REASON_CHARS = 512
_LEASE_EXPIRED_AFTER_SEND = "lease_expired_after_send_attempt"
_OWNED_STATES = frozenset({"pending", "sending", "uncertain"})


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
            return _owned_claim(pending, AnalyzerPublicationClaimStatus.NEW)
        return await self._resolve_existing(key, now=now, allow_reclaim=True)

    async def mark_sending(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
    ) -> AnalyzerPublicationClaim:
        expected = _owned_record(claim, {"pending", "uncertain"})
        sending = {
            "state": "sending",
            "token": expected["token"],
            "claimed_at": expected["claimed_at"],
        }
        key = f"{_PREFIX}{idempotency_key}"
        if not await self._store.insert_or_replace_if(key, expected, sending):
            raise RuntimeError("analyzer publication claim changed before send")
        return _owned_claim(sending, AnalyzerPublicationClaimStatus.SENDING)

    async def mark_uncertain(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        reason: str,
    ) -> AnalyzerPublicationClaim:
        expected = _owned_record(claim, {"pending", "sending"})
        uncertain = {
            "state": "uncertain",
            "token": expected["token"],
            "claimed_at": expected["claimed_at"],
            "reason": reason[:_MAX_REASON_CHARS],
        }
        key = f"{_PREFIX}{idempotency_key}"
        if not await self._store.insert_or_replace_if(key, expected, uncertain):
            raise RuntimeError("analyzer publication claim changed before uncertainty")
        return _owned_claim(uncertain, AnalyzerPublicationClaimStatus.UNCERTAIN)

    async def complete(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        receipt: PublishReceipt,
    ) -> None:
        expected = _owned_record(claim, {"pending", "sending", "uncertain"})
        completed = {
            "state": "completed",
            "topic": receipt.topic,
            "partition": receipt.partition,
            "offset": receipt.offset,
        }
        key = f"{_PREFIX}{idempotency_key}"
        if await self._store.insert_or_replace_if(key, expected, completed):
            return
        if await self._store.seen(key) != completed:
            raise RuntimeError("analyzer publication receipt conflict")

    async def release(
        self,
        idempotency_key: str,
        claim: AnalyzerPublicationClaim,
        *,
        provably_unsent: bool = False,
    ) -> None:
        allowed = {"pending", "uncertain"} | ({"sending"} if provably_unsent else set())
        expected = _owned_record(claim, allowed)
        key = f"{_PREFIX}{idempotency_key}"
        if await self._store.remove_if(key, expected):
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
                record=dict(existing),
            )
        if state == "uncertain":
            return _owned_claim(existing, AnalyzerPublicationClaimStatus.UNCERTAIN)
        if state not in {"pending", "sending"}:
            raise RuntimeError("analyzer publication claim has an invalid state")
        active = _owned_claim(existing, AnalyzerPublicationClaimStatus.IN_PROGRESS)
        if active.claimed_at is None:
            raise RuntimeError("analyzer publication claim has no timestamp")
        age_seconds = (now - active.claimed_at).total_seconds()
        if age_seconds < 0:
            raise RuntimeError("analyzer publication claim is from the future")
        if age_seconds < self._lease_seconds or not allow_reclaim:
            return active
        if state == "sending":
            expired = {
                "state": "uncertain",
                "token": existing["token"],
                "claimed_at": existing["claimed_at"],
                "reason": _LEASE_EXPIRED_AFTER_SEND,
            }
            if await self._store.insert_or_replace_if(key, existing, expired):
                return _owned_claim(expired, AnalyzerPublicationClaimStatus.UNCERTAIN)
            return await self._resolve_existing(key, now=now, allow_reclaim=False)
        replacement = self._new_pending(now)
        if await self._store.insert_or_replace_if(key, existing, replacement):
            return _owned_claim(replacement, AnalyzerPublicationClaimStatus.NEW)
        return await self._resolve_existing(key, now=now, allow_reclaim=False)


def _owned_claim(
    record: Mapping[str, Any],
    status: AnalyzerPublicationClaimStatus,
) -> AnalyzerPublicationClaim:
    if record.get("state") not in _OWNED_STATES:
        raise RuntimeError("analyzer publication claim has an invalid state")
    token = record.get("token")
    claimed_at_raw = record.get("claimed_at")
    if not isinstance(token, str) or not token:
        raise RuntimeError("analyzer publication claim has no token")
    if not isinstance(claimed_at_raw, str):
        raise RuntimeError("analyzer publication claim has no timestamp")
    try:
        claimed_at = datetime.fromisoformat(claimed_at_raw)
    except ValueError as exc:
        raise RuntimeError("analyzer publication timestamp is invalid") from exc
    if claimed_at.tzinfo is None:
        raise RuntimeError("analyzer publication timestamp has no timezone")
    return AnalyzerPublicationClaim(
        status=status,
        token=token,
        claimed_at=claimed_at,
        record=dict(record),
    )


def _owned_record(
    claim: AnalyzerPublicationClaim,
    allowed_states: set[str],
) -> dict[str, Any]:
    """Return the exact record this tick observed, for a compare-and-set."""

    record = claim.record
    if record is None:
        raise ValueError("analyzer publication transition requires an observed claim record")
    state = record.get("state")
    if state not in allowed_states:
        raise ValueError(f"analyzer publication transition rejects claim state {state!r}")
    token = record.get("token")
    claimed_at = record.get("claimed_at")
    if not isinstance(token, str) or not token or not isinstance(claimed_at, str):
        raise ValueError("analyzer publication transition requires a token-owned claim")
    if claim.token != token:
        raise ValueError("analyzer publication claim token does not match its record")
    return dict(record)


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
