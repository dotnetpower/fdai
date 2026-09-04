"""Bounded authenticated ingress for notification publication receipts.

A Teams Workflow (or any equivalent publishing automation) reports whether it
actually posted a card. That report is an **observation**: it can only confirm
or fail an already dispatched channel delivery. It carries no approver, no
message body, and no endpoint value, so it never enters the A1 approval path.

Responsibility:
Authenticate one signed provider callback, bound it, deduplicate it, and hand
it to the broker for the Core consumer that owns durable delivery state.

Boundary:
This module never touches notification delivery state directly. Core owns the
`accepted -> delivered | retryable_failed` transition, so a broker failure
leaves the observation unapplied rather than half-applied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from fdai_service_contracts.notification_receipt import (
    DEFAULT_RECEIPT_SKEW_SECONDS,
    MAX_RECEIPT_BODY_BYTES,
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
    NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
    NotificationDeliveryReceipt,
    NotificationReceiptFormatError,
    encode_notification_delivery_receipt,
    parse_receipt_body,
    verify_receipt_signature,
)
from fdai_service_contracts.schema import ContractValidator


class NotificationReceiptStore(Protocol):
    """Durable metadata store that never receives the provider endpoint value."""

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool: ...

    async def read_state(self, key: str) -> dict[str, object] | None: ...

    async def write_state(self, key: str, value: Mapping[str, object]) -> None: ...


class NotificationReceiptPublisher(Protocol):
    """Publish one bounded mapping after its durable ingress record exists."""

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> object: ...


class NotificationReceiptPublicationError(RuntimeError):
    """The broker did not accept the authenticated observation."""


@dataclass(frozen=True, slots=True)
class NotificationReceiptIngressConfig:
    """Deployment-owned callback secret and request ceilings."""

    secret: str = field(repr=False)
    topic: str
    max_skew_seconds: int = DEFAULT_RECEIPT_SKEW_SECONDS
    max_body_bytes: int = MAX_RECEIPT_BODY_BYTES
    publication_lease_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("notification receipt secret MUST be non-empty")
        if not self.topic.strip():
            raise ValueError("notification receipt topic MUST be non-empty")
        if self.max_skew_seconds < 1:
            raise ValueError("notification receipt max_skew_seconds MUST be positive")
        if not 1 <= self.max_body_bytes <= MAX_RECEIPT_BODY_BYTES:
            raise ValueError(
                f"notification receipt max_body_bytes MUST be in [1, {MAX_RECEIPT_BODY_BYTES}]"
            )
        if not 1 <= self.publication_lease_seconds <= self.max_skew_seconds:
            raise ValueError(
                "notification receipt publication_lease_seconds MUST be positive and "
                "no greater than max_skew_seconds"
            )


@dataclass(frozen=True, slots=True)
class NotificationReceiptIngress:
    """Verify, record, and publish one bounded publication observation.

    ``accept`` is idempotent per ``audit_id`` plus ``channel_id`` plus observed
    publication result: a repeated identical callback returns the recorded
    receipt without republishing. A different result is recorded separately so
    Core can arbitrate it against the current durable delivery state.
    """

    config: NotificationReceiptIngressConfig
    store: NotificationReceiptStore
    publisher: NotificationReceiptPublisher
    validator: ContractValidator
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(tz=UTC))

    async def accept(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> NotificationDeliveryReceipt:
        """Authenticate one callback and hand its observation to the broker."""
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("notification receipt clock MUST be timezone-aware")
        if len(body) > self.config.max_body_bytes:
            raise NotificationReceiptFormatError(
                "notification receipt body exceeds the configured limit"
            )
        verify_receipt_signature(
            secret=self.config.secret,
            headers=headers,
            body=body,
            now=now,
            max_skew_seconds=self.config.max_skew_seconds,
        )
        observed_at = now.astimezone(UTC)
        receipt = parse_receipt_body(body, observed_at=observed_at)
        payload = encode_notification_delivery_receipt(receipt)
        self.validator.validate(
            NOTIFICATION_DELIVERY_RECEIPT_SCHEMA,
            payload,
            version=NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
        )
        key = _receipt_key(receipt)
        prepared: dict[str, object] = {
            "kind": "operator.notification-delivery-receipt",
            "receipt_id": receipt.idempotency_key,
            "audit_id": receipt.audit_id,
            "channel_id": receipt.channel_id,
            "publication_result": receipt.publication_result,
            "phase": "prepared",
            "observed_at": observed_at.isoformat(),
            "attempted_at": observed_at.isoformat(),
            "attempt_count": 1,
        }
        if not await self.store.create_state(key, prepared):
            existing = await self._existing(key=key, receipt=receipt)
            outcome = existing.get("outcome")
            if outcome == "published":
                return receipt
            if outcome != "publication_failed":
                attempted_at = _recorded_datetime(existing, "attempted_at")
                if (observed_at - attempted_at).total_seconds() < (
                    self.config.publication_lease_seconds
                ):
                    raise NotificationReceiptPublicationError(
                        "notification receipt publication remains in progress"
                    )
            attempt_count = existing.get("attempt_count", 1)
            if not isinstance(attempt_count, int) or attempt_count < 1:
                raise NotificationReceiptFormatError(
                    "notification receipt publication attempt metadata is invalid"
                )
            prepared["attempt_count"] = attempt_count + 1
            await self.store.write_state(key, prepared)
        await self._publish(
            key=key,
            prepared=prepared,
            receipt=receipt,
            payload=payload,
        )
        return receipt

    async def _publish(
        self,
        *,
        key: str,
        prepared: Mapping[str, object],
        receipt: NotificationDeliveryReceipt,
        payload: dict[str, object],
    ) -> None:
        """Publish a new or previously failed observation and record its outcome."""
        try:
            await self.publisher.publish(self.config.topic, receipt.audit_id, payload)
        except RuntimeError as exc:
            await self.store.write_state(
                key,
                {
                    **prepared,
                    "phase": "completed",
                    "outcome": "publication_failed",
                    "error_type": type(exc).__name__,
                    "completed_at": self.clock().astimezone(UTC).isoformat(),
                },
            )
            raise NotificationReceiptPublicationError(
                "notification receipt was authenticated but not accepted by the broker"
            ) from exc
        await self.store.write_state(
            key,
            {
                **prepared,
                "phase": "completed",
                "outcome": "published",
                "completed_at": self.clock().astimezone(UTC).isoformat(),
            },
        )

    async def _existing(
        self,
        *,
        key: str,
        receipt: NotificationDeliveryReceipt,
    ) -> dict[str, object]:
        """Return a matching recorded receipt or refuse a conflicting re-report."""
        existing = await self.store.read_state(key)
        if (
            existing is None
            or existing.get("audit_id") != receipt.audit_id
            or existing.get("channel_id") != receipt.channel_id
            or existing.get("publication_result") != receipt.publication_result
        ):
            raise NotificationReceiptFormatError(
                "notification receipt conflicts with a recorded observation for this delivery"
            )
        return existing


def _receipt_key(receipt: NotificationDeliveryReceipt) -> str:
    digest = hashlib.sha256(
        f"{receipt.idempotency_key}:{receipt.publication_result}".encode()
    ).hexdigest()
    return f"operator-notification-delivery-receipt:{digest}"


def _recorded_datetime(record: Mapping[str, object], key: str) -> datetime:
    value = record.get(key)
    if not isinstance(value, str):
        raise NotificationReceiptFormatError(
            "notification receipt publication attempt metadata is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise NotificationReceiptFormatError(
            "notification receipt publication attempt metadata is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NotificationReceiptFormatError(
            "notification receipt publication attempt metadata is invalid"
        )
    return parsed.astimezone(UTC)


__all__ = [
    "NotificationReceiptIngress",
    "NotificationReceiptIngressConfig",
    "NotificationReceiptPublicationError",
    "NotificationReceiptPublisher",
    "NotificationReceiptStore",
]
