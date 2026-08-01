"""Immutable records for durable FDAI Console action dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

_SCHEMA_VERSION: Final[str] = "1.0.0"


class ConsoleActionDispatchConflictError(RuntimeError):
    """Raised when one idempotency key is reused for another intent."""

    def __init__(
        self,
        message: str,
        *,
        dispatch_id: str,
        correlation_id: str,
        accepted_at: datetime,
    ) -> None:
        super().__init__(message)
        self.dispatch_id = dispatch_id
        self.correlation_id = correlation_id
        self.accepted_at = accepted_at


class ConsoleActionDispatchState(StrEnum):
    ABANDONED = "abandoned"
    BLOCKED = "blocked"
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


@dataclass(frozen=True, slots=True)
class ConsoleActionDispatch:
    dispatch_id: str
    idempotency_key: str
    intent_digest: str
    topic: str
    partition_key: str
    payload: Mapping[str, object]
    correlation_id: str
    actor_oid: str
    state: ConsoleActionDispatchState
    revision: int
    attempt_count: int
    available_at: datetime
    accepted_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_until: datetime | None = None
    published_at: datetime | None = None
    last_error: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.dispatch_id,
            self.idempotency_key,
            self.intent_digest,
            self.topic,
            self.partition_key,
            self.correlation_id,
            self.actor_oid,
        )
        if any(not value.strip() for value in required):
            raise ValueError("console action dispatch identifiers MUST be non-empty")
        if self.revision < 1 or self.attempt_count < 0:
            raise ValueError("console action dispatch counters are invalid")
        for value in (
            self.available_at,
            self.accepted_at,
            self.updated_at,
            self.lease_until,
            self.published_at,
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError("console action dispatch timestamps MUST be timezone-aware")
        if self.state is ConsoleActionDispatchState.PUBLISHING and (
            self.lease_owner is None or self.lease_until is None
        ):
            raise ValueError("publishing dispatch MUST carry a lease")
        if self.state is ConsoleActionDispatchState.PUBLISHED and self.published_at is None:
            raise ValueError("published dispatch MUST carry published_at")

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "dispatch_id": self.dispatch_id,
            "idempotency_key": self.idempotency_key,
            "intent_digest": self.intent_digest,
            "topic": self.topic,
            "partition_key": self.partition_key,
            "payload": dict(self.payload),
            "correlation_id": self.correlation_id,
            "actor_oid": self.actor_oid,
            "state": self.state.value,
            "revision": self.revision,
            "attempt_count": self.attempt_count,
            "available_at": self.available_at.isoformat(),
            "accepted_at": self.accepted_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "lease_owner": self.lease_owner,
            "lease_until": _optional_time(self.lease_until),
            "published_at": _optional_time(self.published_at),
            "last_error": self.last_error,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ConsoleActionDispatch:
        if value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported console action dispatch schema")
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("console action dispatch payload MUST be an object")
        return cls(
            dispatch_id=_text(value, "dispatch_id"),
            idempotency_key=_text(value, "idempotency_key"),
            intent_digest=_text(value, "intent_digest"),
            topic=_text(value, "topic"),
            partition_key=_text(value, "partition_key"),
            payload=dict(payload),
            correlation_id=_text(value, "correlation_id"),
            actor_oid=_text(value, "actor_oid"),
            state=ConsoleActionDispatchState(_text(value, "state")),
            revision=_integer(value, "revision"),
            attempt_count=_integer(value, "attempt_count"),
            available_at=_time(value, "available_at"),
            accepted_at=_time(value, "accepted_at"),
            updated_at=_time(value, "updated_at"),
            lease_owner=_optional_text(value.get("lease_owner")),
            lease_until=_optional_time_from(value.get("lease_until")),
            published_at=_optional_time_from(value.get("published_at")),
            last_error=_optional_text(value.get("last_error")),
        )


def _text(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"console action dispatch {key} MUST be non-empty")
    return item


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f"console action dispatch {key} MUST be an integer")
    return item


def _time(value: Mapping[str, object], key: str) -> datetime:
    return _parse_time(_text(value, key))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("console action dispatch timestamp MUST be timezone-aware")
    return parsed


def _optional_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_time_from(value: object) -> datetime | None:
    return _parse_time(value) if isinstance(value, str) and value else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "ConsoleActionDispatch",
    "ConsoleActionDispatchConflictError",
    "ConsoleActionDispatchState",
]
