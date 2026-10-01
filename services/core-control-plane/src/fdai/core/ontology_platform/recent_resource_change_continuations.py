"""Core-owned opaque continuations for recent Resource change pages."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from fdai_service_contracts.ontology_query import canonical_json
from fdai_service_contracts.reasoning_handles import (
    KeysetCursor,
    OrderingTerm,
    QueryContinuation,
    SortDirection,
)

from fdai.core.ontology_platform.functions import FunctionInvocationContext

_EXPIRY_SECONDS = 15 * 60
_ORDERING = (
    OrderingTerm(field_name="effective_at", direction=SortDirection.DESC),
    OrderingTerm(field_name="subject_ref", direction=SortDirection.ASC),
)


class ContinuationInvalidError(Exception):
    """The opaque continuation cannot authorize a next page."""


@dataclass(frozen=True, slots=True)
class ContinuationBinding:
    """Stable request fields that must match every continuation page read."""

    deployment_scope_digest: str
    conversation_id: str
    admitted_goal_digest: str
    plan_digest: str
    manifest_digest: str
    purpose: str = "operations-review"


@dataclass(frozen=True, slots=True)
class StoredRecentResourceChangeContinuation:
    """Core-only continuation record plus the raw seek key kept from clients."""

    continuation_ref: str
    continuation: QueryContinuation
    cursor_subject_ref: str


@dataclass(frozen=True, slots=True)
class RecentResourceChangeContinuationRequest:
    """Validated page-read state resolved from an opaque reference."""

    continuation_ref: str
    continuation: QueryContinuation
    cursor_subject_ref: str
    cursor_effective_at: datetime
    page_size: int
    context: FunctionInvocationContext
    issuer: RecentResourceChangeContinuationIssuer


class RecentResourceChangeContinuationStore(Protocol):
    """Persist and resolve Core-only recent-change continuations."""

    async def put(self, record: StoredRecentResourceChangeContinuation) -> None: ...

    async def get(self, continuation_ref: str) -> StoredRecentResourceChangeContinuation | None: ...

    async def delete(self, continuation_ref: str) -> None: ...


class InMemoryRecentResourceChangeContinuationStore:
    """Process-local continuation store for tests and single-process development."""

    def __init__(self) -> None:
        self._records: dict[str, StoredRecentResourceChangeContinuation] = {}

    async def put(self, record: StoredRecentResourceChangeContinuation) -> None:
        self._records[record.continuation_ref] = record

    async def get(self, continuation_ref: str) -> StoredRecentResourceChangeContinuation | None:
        return self._records.get(continuation_ref)

    async def delete(self, continuation_ref: str) -> None:
        self._records.pop(continuation_ref, None)


class RecentResourceChangeContinuationIssuer:
    """Issue, validate, and advance recent-change page continuations."""

    def __init__(
        self,
        *,
        store: RecentResourceChangeContinuationStore,
        binding: ContinuationBinding,
        clock: Any | None = None,
    ) -> None:
        self._store = store
        self._binding = binding
        self._clock = clock or (lambda: datetime.now(UTC))

    async def issue(
        self,
        *,
        context: FunctionInvocationContext,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        query_version_digest: str,
        page_size: int,
        cursor: Any,
        remaining_rows: int,
    ) -> str:
        now = _aware_utc(self._clock())
        continuation_ref = _opaque_ref()
        continuation = self._continuation(
            context=context,
            start_at=start_at,
            end_at=end_at,
            known_at=known_at,
            query_version_digest=query_version_digest,
            page_size=page_size,
            cursor=cursor,
            remaining_rows=remaining_rows,
            expires_at=now + timedelta(seconds=_EXPIRY_SECONDS),
        )
        await self._store.put(
            StoredRecentResourceChangeContinuation(
                continuation_ref=continuation_ref,
                continuation=continuation,
                cursor_subject_ref=str(cursor.last_subject_ref),
            )
        )
        return continuation_ref

    async def request(
        self,
        *,
        continuation_ref: str,
        context: FunctionInvocationContext,
        page_size: int | None,
        query_version_digest: str,
    ) -> RecentResourceChangeContinuationRequest:
        record = await self._store.get(continuation_ref)
        if record is None:
            raise ContinuationInvalidError
        continuation = record.continuation
        if _aware_utc(self._clock()) >= continuation.expires_at:
            raise ContinuationInvalidError
        if (
            continuation.query_version_digest != query_version_digest
            or continuation.deployment_scope_digest != self._binding.deployment_scope_digest
            or continuation.conversation_id != self._binding.conversation_id
            or continuation.purpose != self._binding.purpose
            or continuation.admitted_goal_digest != self._binding.admitted_goal_digest
            or continuation.plan_digest != self._binding.plan_digest
            or continuation.manifest_digest != self._binding.manifest_digest
            or continuation.principal_digest != _principal_digest(context)
        ):
            raise ContinuationInvalidError
        requested_size = continuation.page_size if page_size is None else page_size
        if not 1 <= requested_size <= 20:
            raise ContinuationInvalidError
        effective_at = continuation.keyset_cursor.last_effective_at
        if effective_at is None:
            raise ContinuationInvalidError
        return RecentResourceChangeContinuationRequest(
            continuation_ref=continuation_ref,
            continuation=continuation,
            cursor_subject_ref=record.cursor_subject_ref,
            cursor_effective_at=effective_at,
            page_size=requested_size,
            context=context,
            issuer=self,
        )

    async def advance(
        self,
        *,
        previous_ref: str,
        context: FunctionInvocationContext,
        continuation: QueryContinuation,
        cursor: Any,
        remaining_rows: int,
        page_size: int,
    ) -> str:
        self._validate_context(context, continuation)
        continuation_ref = _opaque_ref()
        next_continuation = continuation.model_copy(
            update={
                "keyset_cursor": _keyset_cursor(cursor),
                "page_size": page_size,
                "remaining_rows": remaining_rows,
            }
        )
        await self._store.put(
            StoredRecentResourceChangeContinuation(
                continuation_ref=continuation_ref,
                continuation=next_continuation,
                cursor_subject_ref=str(cursor.last_subject_ref),
            )
        )
        await self._store.delete(previous_ref)
        return continuation_ref

    def _continuation(
        self,
        *,
        context: FunctionInvocationContext,
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        query_version_digest: str,
        page_size: int,
        cursor: Any,
        remaining_rows: int,
        expires_at: datetime,
    ) -> QueryContinuation:
        return QueryContinuation(
            deployment_scope_digest=self._binding.deployment_scope_digest,
            principal_digest=_principal_digest(context),
            conversation_id=self._binding.conversation_id,
            purpose=self._binding.purpose,
            admitted_goal_digest=self._binding.admitted_goal_digest,
            plan_digest=self._binding.plan_digest,
            manifest_digest=self._binding.manifest_digest,
            query_version_digest=query_version_digest,
            window_start=start_at,
            window_end=end_at,
            cutoff=known_at,
            ordering=_ORDERING,
            keyset_cursor=_keyset_cursor(cursor),
            page_size=page_size,
            expires_at=expires_at,
            remaining_rows=remaining_rows,
        )

    def _validate_context(
        self,
        context: FunctionInvocationContext,
        continuation: QueryContinuation,
    ) -> None:
        if continuation.principal_digest != _principal_digest(context):
            raise ContinuationInvalidError


def _principal_digest(context: FunctionInvocationContext) -> str:
    if context.principal_scope_digest is not None:
        return cast(str, context.principal_scope_digest)
    return _digest({"principal_ref": context.principal_ref, "purposes": context.purposes})


def _keyset_cursor(cursor: Any) -> KeysetCursor:
    subject_ref = str(cursor.last_subject_ref)
    effective_at = _aware_utc(cursor.last_effective_at)
    return KeysetCursor(
        cursor_digest=_digest(
            {"last_effective_at": effective_at.isoformat(), "last_subject_ref": subject_ref}
        ),
        last_effective_at=effective_at,
        last_subject_digest=_digest(subject_ref),
    )


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _opaque_ref() -> str:
    return secrets.token_urlsafe(32)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("continuation time MUST be timezone-aware")
    return value.astimezone(UTC)


def encode_stored_continuation(record: StoredRecentResourceChangeContinuation) -> str:
    """Return canonical JSON for a continuation store record."""

    return cast(
        str,
        canonical_json(
            {
                "continuation_ref": record.continuation_ref,
                "continuation": record.continuation.model_dump(mode="json"),
                "cursor_subject_ref": record.cursor_subject_ref,
            }
        ),
    )


def decode_stored_continuation(payload: str) -> StoredRecentResourceChangeContinuation:
    """Decode a continuation store record."""

    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("continuation store record MUST be an object")
    return StoredRecentResourceChangeContinuation(
        continuation_ref=str(raw["continuation_ref"]),
        continuation=QueryContinuation.model_validate(raw["continuation"]),
        cursor_subject_ref=str(raw["cursor_subject_ref"]),
    )


__all__ = [
    "ContinuationBinding",
    "ContinuationInvalidError",
    "InMemoryRecentResourceChangeContinuationStore",
    "RecentResourceChangeContinuationIssuer",
    "RecentResourceChangeContinuationRequest",
    "RecentResourceChangeContinuationStore",
    "StoredRecentResourceChangeContinuation",
    "decode_stored_continuation",
    "encode_stored_continuation",
]
