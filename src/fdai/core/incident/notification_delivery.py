"""Atomic delivery claims for durable incident notifications."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import uuid4


class NotificationClaimStatus(StrEnum):
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    SENT = "sent"


@dataclass(frozen=True, slots=True)
class NotificationDeliveryClaim:
    status: NotificationClaimStatus
    token: str | None = None


@runtime_checkable
class IncidentNotificationDeliveryStore(Protocol):
    async def claim(
        self,
        *,
        audit_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> NotificationDeliveryClaim: ...

    async def complete(self, *, audit_id: str, token: str, at: datetime) -> None: ...

    async def release(self, *, audit_id: str, token: str) -> None: ...


class InMemoryIncidentNotificationDeliveryStore:
    """Lock-backed delivery claims for local development and tests."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, object]] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        *,
        audit_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> NotificationDeliveryClaim:
        _validate_claim_input(audit_id, now, lease_seconds)
        async with self._lock:
            record = self._records.get(audit_id)
            if record is not None and record.get("status") == "sent":
                return NotificationDeliveryClaim(NotificationClaimStatus.SENT)
            if record is not None and record.get("status") == "sending":
                lease_until = record.get("lease_until")
                if isinstance(lease_until, datetime) and lease_until > now:
                    return NotificationDeliveryClaim(NotificationClaimStatus.IN_PROGRESS)
            token = str(uuid4())
            self._records[audit_id] = {
                "status": "sending",
                "token": token,
                "lease_until": now + timedelta(seconds=lease_seconds),
            }
            return NotificationDeliveryClaim(NotificationClaimStatus.CLAIMED, token)

    async def complete(self, *, audit_id: str, token: str, at: datetime) -> None:
        if not token:
            raise ValueError("incident notification claim token MUST be non-empty")
        if at.tzinfo is None:
            raise ValueError("incident notification completion time MUST be timezone-aware")
        async with self._lock:
            record = self._records.get(audit_id)
            if record is None or record.get("token") != token:
                raise RuntimeError("incident notification claim token mismatch")
            self._records[audit_id] = {"status": "sent", "sent_at": at}

    async def release(self, *, audit_id: str, token: str) -> None:
        async with self._lock:
            record = self._records.get(audit_id)
            if record is not None and record.get("token") == token:
                self._records.pop(audit_id, None)


def _validate_claim_input(audit_id: str, now: datetime, lease_seconds: int) -> None:
    if not audit_id:
        raise ValueError("incident notification audit_id MUST be non-empty")
    if now.tzinfo is None:
        raise ValueError("incident notification claim time MUST be timezone-aware")
    if lease_seconds < 1:
        raise ValueError("incident notification lease_seconds MUST be >= 1")


__all__ = [
    "IncidentNotificationDeliveryStore",
    "InMemoryIncidentNotificationDeliveryStore",
    "NotificationClaimStatus",
    "NotificationDeliveryClaim",
]
