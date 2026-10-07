"""Leased continuations for collection metric reads that stopped before every member (P3).

A collection metric read that stops on its read budget or on an unavailable provider keeps
one terminal row for every member: a value, a typed unknown, or pending. When a store is
bound, the stop also issues an opaque reference. The reference binds the principal scope,
role, purpose, the exact ordered member manifest, the metric concepts and selection, and the
pinned window; the raw cursor stays in Core. Claiming leases the reference, and only a
successful page completes it and issues the successor, so a failed page keeps its reference
and two concurrent claims never both advance one cursor.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import content_digest

from .functions import FunctionInvocationContext

CONTINUATION_PREFIX = "metric-collection-continuation:"
_EXPIRY_SECONDS = 15 * 60
_LEASE_SECONDS = 120
_SELECTION_KEYS = (
    "metric_concepts",
    "window_seconds",
    "comparator",
    "threshold",
    "threshold_unit",
    "order_direction",
    "order_limit",
    "list_unknown",
)


class MetricContinuationInvalidError(Exception):
    """The reference cannot authorize another page of the same collection read."""


@dataclass(frozen=True, slots=True)
class MetricCollectionContinuation:
    """Core-only state of one stopped collection metric read."""

    continuation_ref: str
    binding_digest: str
    members_digest: str
    selection_digest: str
    window_start: datetime
    window_end: datetime
    cursor: int
    member_count: int
    expires_at: datetime
    leased_until: datetime | None = None


class MetricCollectionContinuationStore(Protocol):
    async def put(self, record: MetricCollectionContinuation) -> None: ...

    async def lease(
        self, continuation_ref: str, *, now: datetime
    ) -> MetricCollectionContinuation | None: ...

    async def complete(
        self, continuation_ref: str, successor: MetricCollectionContinuation | None
    ) -> None: ...

    async def release(self, continuation_ref: str) -> None: ...


class InMemoryMetricCollectionContinuationStore:
    """Process-local leased store for tests and single-process development."""

    def __init__(self) -> None:
        self._records: dict[str, MetricCollectionContinuation] = {}
        self._lock = asyncio.Lock()

    async def put(self, record: MetricCollectionContinuation) -> None:
        async with self._lock:
            self._records[record.continuation_ref] = record

    async def lease(
        self, continuation_ref: str, *, now: datetime
    ) -> MetricCollectionContinuation | None:
        async with self._lock:
            record = self._records.get(continuation_ref)
            if record is None or (record.leased_until is not None and record.leased_until > now):
                return None
            leased = replace(record, leased_until=now + timedelta(seconds=_LEASE_SECONDS))
            self._records[continuation_ref] = leased
            return leased

    async def complete(
        self, continuation_ref: str, successor: MetricCollectionContinuation | None
    ) -> None:
        async with self._lock:
            self._records.pop(continuation_ref, None)
            if successor is not None:
                self._records[successor.continuation_ref] = successor

    async def release(self, continuation_ref: str) -> None:
        async with self._lock:
            record = self._records.get(continuation_ref)
            if record is not None:
                self._records[continuation_ref] = replace(record, leased_until=None)


@dataclass(frozen=True, slots=True)
class MetricContinuationPage:
    """A leased page: the members after the cursor and the pinned window to read them in."""

    record: MetricCollectionContinuation
    start: datetime
    end: datetime


class MetricCollectionContinuations:
    """Issue, lease, and advance collection metric read continuations."""

    def __init__(self, store: MetricCollectionContinuationStore, *, clock: Any = None) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    async def issue(
        self,
        *,
        context: FunctionInvocationContext,
        arguments: Mapping[str, Any],
        member_ids: Sequence[str],
        cursor: int,
        start: datetime,
        end: datetime,
    ) -> str:
        record = MetricCollectionContinuation(
            continuation_ref=_opaque_ref(),
            binding_digest=_binding_digest(context),
            members_digest=members_digest(member_ids),
            selection_digest=_selection_digest(arguments),
            window_start=start,
            window_end=end,
            cursor=cursor,
            member_count=len(member_ids),
            expires_at=self._now() + timedelta(seconds=_EXPIRY_SECONDS),
        )
        await self._store.put(record)
        return record.continuation_ref

    async def lease(
        self,
        continuation_ref: str,
        *,
        context: FunctionInvocationContext,
        arguments: Mapping[str, Any],
        member_ids: Sequence[str],
    ) -> MetricContinuationPage:
        now = self._now()
        record = await self._store.lease(continuation_ref, now=now)
        if record is None:
            raise MetricContinuationInvalidError
        if (
            now >= record.expires_at
            or record.binding_digest != _binding_digest(context)
            or record.members_digest != members_digest(member_ids)
            or record.selection_digest != _selection_digest(arguments)
            or record.member_count != len(member_ids)
            or not 0 < record.cursor < record.member_count
        ):
            await self._store.release(continuation_ref)
            raise MetricContinuationInvalidError
        return MetricContinuationPage(
            record=record, start=record.window_start, end=record.window_end
        )

    async def complete(self, page: MetricContinuationPage, *, cursor: int | None) -> str | None:
        """Consume the leased reference and issue its successor when members remain."""

        successor = (
            replace(
                page.record,
                continuation_ref=_opaque_ref(),
                cursor=cursor,
                leased_until=None,
                expires_at=self._now() + timedelta(seconds=_EXPIRY_SECONDS),
            )
            if cursor is not None and cursor < page.record.member_count
            else None
        )
        await self._store.complete(page.record.continuation_ref, successor)
        return successor.continuation_ref if successor is not None else None

    async def release(self, page: MetricContinuationPage) -> None:
        await self._store.release(page.record.continuation_ref)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("metric continuation clock MUST be timezone-aware")
        return value.astimezone(UTC)


def members_digest(member_ids: Sequence[str]) -> str:
    digest = hashlib.sha256(b"fdai.metric-collection-members.v1\n")
    for member_id in member_ids:
        encoded = member_id.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


def _binding_digest(context: FunctionInvocationContext) -> str:
    return content_digest(
        {
            "principal_scope_digest": context.principal_scope_digest,
            "caller_role": str(context.caller_role),
            "purposes": list(context.purposes),
        }
    )


def _selection_digest(arguments: Mapping[str, Any]) -> str:
    return content_digest({key: arguments.get(key) for key in _SELECTION_KEYS})


def _opaque_ref() -> str:
    return secrets.token_urlsafe(32)


__all__ = [
    "CONTINUATION_PREFIX",
    "InMemoryMetricCollectionContinuationStore",
    "MetricCollectionContinuation",
    "MetricCollectionContinuationStore",
    "MetricCollectionContinuations",
    "MetricContinuationInvalidError",
    "MetricContinuationPage",
    "members_digest",
]
