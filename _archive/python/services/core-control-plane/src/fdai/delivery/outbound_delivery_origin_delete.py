"""Origin-scoped outbound delivery deletion coordinator with audit receipts and replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from fdai.core.scheduler.continuation_retention import (
    ContinuationDeletionFence,
    ContinuationDeletionFencedError,
    RetentionFenceUnavailableError,
    assert_not_fenced,
)
from fdai.shared.providers.conversation_delivery import (
    ConversationDeliveryStore,
    OriginDeletionResult,
    OutboundDeliveryReadbackError,
)

_MAX_REASON_CHARS = 512
_MAX_ID_CHARS = 256


class OriginDeletionPreconditionError(RuntimeError):
    """Raised when an origin deletion request lacks required fence or identity preconditions."""


@dataclass(frozen=True, slots=True)
class OriginDeletionAuditReceipt:
    """Immutable append-only audit record for one origin- or session-scoped delivery purge."""

    receipt_id: str
    origin_id: str
    session_id: str | None
    actor_id: str
    reason: str
    purged_at: datetime
    deleted_delivery_ids: tuple[str, ...]
    retained_attempts: int
    retained_acknowledgements: int
    idempotent_replay: bool
    fence_verified: bool
    execution_authority: Literal["none"]
    receipt_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "origin_id": self.origin_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "purged_at": self.purged_at.astimezone(UTC).isoformat(),
            "deleted_delivery_ids": list(self.deleted_delivery_ids),
            "retained_attempts": self.retained_attempts,
            "retained_acknowledgements": self.retained_acknowledgements,
            "idempotent_replay": self.idempotent_replay,
            "fence_verified": self.fence_verified,
            "execution_authority": "none",
            "receipt_digest": self.receipt_digest,
        }


class OriginDeletionAuditSink(Protocol):
    """Append-only sink receiving origin-scoped outbound delivery deletion receipts."""

    async def append(self, receipt: OriginDeletionAuditReceipt) -> None: ...


class InMemoryOriginDeletionAuditSink:
    """Deterministic in-memory audit sink for origin-scoped outbound deletion receipts."""

    def __init__(self) -> None:
        self._receipts: list[OriginDeletionAuditReceipt] = []

    @property
    def receipts(self) -> tuple[OriginDeletionAuditReceipt, ...]:
        return tuple(self._receipts)

    async def append(self, receipt: OriginDeletionAuditReceipt) -> None:
        self._receipts.append(receipt)


class OriginScopedOutboundDeliveryDeleter:
    """Coordinate origin- and session-scoped purges over the outbound delivery ledger.

    Deleting a scheduled-continuation anchor or conversation origin purges every
    retained outbound delivery copy bound to that ``origin_id`` or ``session_id``,
    verifies post-delete readback, preserves non-sensitive attempt/acknowledgement
    lineage, and records an append-only audit receipt with idempotent replay.
    """

    def __init__(
        self,
        *,
        store: ConversationDeliveryStore,
        audit: OriginDeletionAuditSink,
        fence: ContinuationDeletionFence | None = None,
        clock: Callable[[], datetime] | None = None,
        snapshot_limit: int = 500,
    ) -> None:
        if isinstance(snapshot_limit, bool) or not 1 <= snapshot_limit <= 500:
            raise ValueError("snapshot_limit MUST be between 1 and 500")
        self._store = store
        self._audit = audit
        self._fence = fence
        self._clock = clock or (lambda: datetime.now(UTC))
        self._snapshot_limit = snapshot_limit
        self._purged_origins: set[str] = set()
        self._purged_sessions: dict[str, tuple[str, ...]] = {}

    async def purge_origin(
        self,
        *,
        origin_id: str,
        actor_id: str,
        reason: str,
        session_id: str | None = None,
        at: datetime | None = None,
        require_fence: bool = False,
    ) -> OriginDeletionAuditReceipt:
        """Purge every retained outbound delivery copy bound to ``origin_id``."""
        normalized_origin = _validate_identifier("origin_id", origin_id)
        normalized_actor = _validate_identifier("actor_id", actor_id)
        normalized_reason = _validate_reason(reason)
        normalized_session = (
            _validate_identifier("session_id", session_id) if session_id is not None else None
        )
        purged_at = _ensure_aware(at or self._clock())

        fence_verified = False
        if require_fence:
            if self._fence is None:
                raise OriginDeletionPreconditionError(
                    "origin purge requires a configured deletion fence"
                )
            await _require_fenced(self._fence, anchor_id=normalized_origin)
            fence_verified = True

        was_already_purged = normalized_origin in self._purged_origins
        deletion_result: OriginDeletionResult = await self._store.delete_by_origin(
            origin_ref=normalized_origin,
            at=purged_at,
        )
        await self._verify_origin_absent(normalized_origin)
        self._purged_origins.add(normalized_origin)

        idempotent_replay = was_already_purged and len(deletion_result.deleted_delivery_ids) == 0
        receipt = _build_receipt(
            origin_id=normalized_origin,
            session_id=normalized_session,
            actor_id=normalized_actor,
            reason=normalized_reason,
            purged_at=purged_at,
            deleted_delivery_ids=deletion_result.deleted_delivery_ids,
            retained_attempts=deletion_result.retained_attempts,
            retained_acknowledgements=deletion_result.retained_acknowledgements,
            idempotent_replay=idempotent_replay,
            fence_verified=fence_verified,
        )
        await self._audit.append(receipt)
        return receipt

    async def purge_session(
        self,
        *,
        session_id: str,
        actor_id: str,
        reason: str,
        at: datetime | None = None,
    ) -> tuple[OriginDeletionAuditReceipt, ...]:
        """Purge every retained outbound delivery copy bound to ``session_id``."""
        normalized_session = _validate_identifier("session_id", session_id)
        normalized_actor = _validate_identifier("actor_id", actor_id)
        normalized_reason = _validate_reason(reason)
        purged_at = _ensure_aware(at or self._clock())

        snapshot = await self._store.snapshot(limit=self._snapshot_limit)
        matching_origins = sorted(
            {
                record.origin_ref
                for record in snapshot.deliveries
                if record.conversation_id == normalized_session
                or record.origin_ref == normalized_session
            }
        )
        if not matching_origins:
            prior_origins = self._purged_sessions.get(normalized_session, (normalized_session,))
            matching_origins = list(prior_origins)

        receipts: list[OriginDeletionAuditReceipt] = []
        for origin_ref in matching_origins:
            receipt = await self.purge_origin(
                origin_id=origin_ref,
                session_id=normalized_session,
                actor_id=normalized_actor,
                reason=normalized_reason,
                at=purged_at,
                require_fence=False,
            )
            receipts.append(receipt)

        await self._verify_session_absent(normalized_session)
        self._purged_sessions[normalized_session] = tuple(matching_origins)
        return tuple(receipts)

    async def _verify_origin_absent(self, origin_id: str) -> None:
        snapshot = await self._store.snapshot(limit=self._snapshot_limit)
        survivors = [
            record.delivery_id for record in snapshot.deliveries if record.origin_ref == origin_id
        ]
        if survivors:
            raise OutboundDeliveryReadbackError(
                f"outbound delivery bodies survived origin purge for {origin_id}"
            )

    async def _verify_session_absent(self, session_id: str) -> None:
        snapshot = await self._store.snapshot(limit=self._snapshot_limit)
        survivors = [
            record.delivery_id
            for record in snapshot.deliveries
            if record.conversation_id == session_id or record.origin_ref == session_id
        ]
        if survivors:
            raise OutboundDeliveryReadbackError(
                f"outbound delivery bodies survived session purge for {session_id}"
            )


async def _require_fenced(fence: ContinuationDeletionFence, *, anchor_id: str) -> None:
    try:
        await assert_not_fenced(fence, anchor_id=anchor_id)
    except ContinuationDeletionFencedError:
        return
    except RetentionFenceUnavailableError:
        raise
    raise OriginDeletionPreconditionError(
        "scheduled continuation origin purge requires a recorded deletion fence"
    )


def _build_receipt(
    *,
    origin_id: str,
    session_id: str | None,
    actor_id: str,
    reason: str,
    purged_at: datetime,
    deleted_delivery_ids: tuple[str, ...],
    retained_attempts: int,
    retained_acknowledgements: int,
    idempotent_replay: bool,
    fence_verified: bool,
) -> OriginDeletionAuditReceipt:
    material = {
        "actor_id": actor_id,
        "deleted_delivery_ids": list(deleted_delivery_ids),
        "execution_authority": "none",
        "fence_verified": fence_verified,
        "idempotent_replay": idempotent_replay,
        "origin_id": origin_id,
        "purged_at": purged_at.astimezone(UTC).isoformat(),
        "reason": reason,
        "retained_acknowledgements": retained_acknowledgements,
        "retained_attempts": retained_attempts,
        "session_id": session_id,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    receipt_id = "origin-purge:" + digest[7:39]
    return OriginDeletionAuditReceipt(
        receipt_id=receipt_id,
        origin_id=origin_id,
        session_id=session_id,
        actor_id=actor_id,
        reason=reason,
        purged_at=purged_at,
        deleted_delivery_ids=deleted_delivery_ids,
        retained_attempts=retained_attempts,
        retained_acknowledgements=retained_acknowledgements,
        idempotent_replay=idempotent_replay,
        fence_verified=fence_verified,
        execution_authority="none",
        receipt_digest=digest,
    )


def _validate_identifier(field_name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} MUST be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_ID_CHARS:
        raise ValueError(f"{field_name} MUST be non-empty and at most {_MAX_ID_CHARS} chars")
    return normalized


def _validate_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise ValueError("reason MUST be a string")
    normalized = reason.strip()
    if not normalized or len(normalized) > _MAX_REASON_CHARS:
        raise ValueError(f"reason MUST be non-empty and at most {_MAX_REASON_CHARS} chars")
    return normalized


def _ensure_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("purge timestamp MUST be timezone-aware")
    return timestamp.astimezone(UTC)


OutboundDeliveryOriginDeleteReceipt = OriginDeletionAuditReceipt

__all__ = [
    "InMemoryOriginDeletionAuditSink",
    "OriginDeletionAuditReceipt",
    "OriginDeletionAuditSink",
    "OriginDeletionPreconditionError",
    "OriginScopedOutboundDeliveryDeleter",
    "OutboundDeliveryOriginDeleteReceipt",
]
