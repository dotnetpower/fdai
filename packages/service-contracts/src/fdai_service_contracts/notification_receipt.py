"""Operator-to-Core notification publication receipt transport.

A Teams Workflow reports whether it published a card. That report is an
*observation*, never an authority grant: it can only move one already
dispatched channel delivery from ``accepted`` to ``delivered`` or to
``retryable_failed``.

The Operator Service owns the public HTTP ingress and authenticates the
provider callback with a deployment-owned shared secret. Core owns the durable
delivery state and consumes the authenticated observation from the broker. This
module holds the only shared definition of both halves so the two services can
never disagree on the signature material or the wire shape.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

NOTIFICATION_DELIVERY_RECEIPT_TOPIC: Final[str] = "fdai.notifications.delivery-receipts"
"""Auxiliary logical topic carrying authenticated publication observations."""

NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP: Final[str] = "fdai-notification-delivery-receipts"
NOTIFICATION_DELIVERY_RECEIPT_SCHEMA: Final[str] = "notification-delivery-receipt"
NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION: Final[str] = "1.0.0"

RECEIPT_TIMESTAMP_HEADER: Final[str] = "x-fdai-timestamp"
RECEIPT_SIGNATURE_HEADER: Final[str] = "x-fdai-signature"
_SIGNATURE_PREFIX: Final[str] = "sha256="
_SIGNATURE_DIGEST = re.compile(r"^[0-9a-f]{64}$")

MAX_RECEIPT_BODY_BYTES: Final[int] = 4096
MAX_RECEIPT_ID_LENGTH: Final[int] = 256
DEFAULT_RECEIPT_SKEW_SECONDS: Final[int] = 300

PUBLICATION_RESULTS: Final[frozenset[str]] = frozenset({"published", "failed"})
_RECEIPT_FIELDS: Final[frozenset[str]] = frozenset(
    {"audit_id", "channel_id", "publication_result", "provider_message_id"}
)


class NotificationReceiptAuthenticationError(PermissionError):
    """The callback signature, timestamp, or freshness window did not verify."""


class NotificationReceiptFormatError(ValueError):
    """The callback body or broker envelope violated the bounded receipt shape."""


@dataclass(frozen=True, slots=True)
class NotificationDeliveryReceipt:
    """One authenticated publication observation for a single channel delivery.

    ``observed_at`` is the ingress verification time recorded by the Operator
    Service. It is evidence about when FDAI observed the report, not a claim
    about when the provider published the message.
    """

    audit_id: str
    channel_id: str
    publication_result: str
    observed_at: datetime
    provider_message_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("audit_id", self.audit_id), ("channel_id", self.channel_id)):
            if not value or len(value) > MAX_RECEIPT_ID_LENGTH:
                raise NotificationReceiptFormatError(
                    f"notification receipt {name} MUST be a bounded non-empty string"
                )
        if self.publication_result not in PUBLICATION_RESULTS:
            raise NotificationReceiptFormatError(
                "notification receipt publication_result MUST be 'published' or 'failed'"
            )
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise NotificationReceiptFormatError(
                "notification receipt observed_at MUST be timezone-aware"
            )
        if self.provider_message_id is not None and (
            not self.provider_message_id or len(self.provider_message_id) > MAX_RECEIPT_ID_LENGTH
        ):
            raise NotificationReceiptFormatError(
                "notification receipt provider_message_id MUST be bounded and non-empty"
            )

    @property
    def published(self) -> bool:
        """Report whether the provider observed a successful publication."""
        return self.publication_result == "published"

    @property
    def idempotency_key(self) -> str:
        """Return the stable per-delivery key both services deduplicate on."""
        return notification_receipt_key(audit_id=self.audit_id, channel_id=self.channel_id)


def notification_receipt_key(*, audit_id: str, channel_id: str) -> str:
    """Return the stable ``audit_id`` plus ``channel_id`` receipt identity."""
    material = f"{audit_id}\x1f{channel_id}".encode()
    return hashlib.sha256(material).hexdigest()


def compute_receipt_signature(*, secret: str, timestamp: str, body: bytes) -> str:
    """Return the hex HMAC-SHA256 over ``timestamp`` and the exact body bytes."""
    if not secret:
        raise ValueError("notification receipt secret MUST be non-empty")
    material = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def verify_receipt_signature(
    *,
    secret: str,
    headers: Mapping[str, str],
    body: bytes,
    now: datetime,
    max_skew_seconds: int = DEFAULT_RECEIPT_SKEW_SECONDS,
) -> datetime:
    """Verify one bounded signed callback and return its signed timestamp.

    Raises :class:`NotificationReceiptAuthenticationError` when the signature is
    missing, malformed, stale, or does not match. The caller MUST enforce the
    body ceiling before calling this function.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("notification receipt clock MUST be timezone-aware")
    if max_skew_seconds < 1:
        raise ValueError("notification receipt max_skew_seconds MUST be positive")
    normalized = {key.casefold(): value for key, value in headers.items()}
    timestamp = normalized.get(RECEIPT_TIMESTAMP_HEADER, "")
    signature = normalized.get(RECEIPT_SIGNATURE_HEADER, "")
    if not timestamp or not signature.startswith(_SIGNATURE_PREFIX):
        raise NotificationReceiptAuthenticationError(
            "notification receipt signature is missing or malformed"
        )
    try:
        signed_at = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise NotificationReceiptAuthenticationError(
            "notification receipt timestamp is invalid"
        ) from exc
    if signed_at.tzinfo is None or signed_at.utcoffset() is None:
        raise NotificationReceiptAuthenticationError(
            "notification receipt timestamp MUST be timezone-aware"
        )
    if abs((now - signed_at).total_seconds()) > max_skew_seconds:
        raise NotificationReceiptAuthenticationError(
            "notification receipt timestamp is outside the allowed window"
        )
    expected = compute_receipt_signature(secret=secret, timestamp=timestamp, body=body)
    supplied = signature[len(_SIGNATURE_PREFIX) :]
    if _SIGNATURE_DIGEST.fullmatch(supplied) is None or not hmac.compare_digest(
        expected,
        supplied,
    ):
        raise NotificationReceiptAuthenticationError("notification receipt signature mismatch")
    return signed_at


def parse_receipt_body(body: bytes, *, observed_at: datetime) -> NotificationDeliveryReceipt:
    """Parse the closed provider callback body into a bounded receipt."""
    if len(body) > MAX_RECEIPT_BODY_BYTES:
        raise NotificationReceiptFormatError(
            "notification receipt body exceeds the configured limit"
        )
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise NotificationReceiptFormatError("notification receipt body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise NotificationReceiptFormatError("notification receipt body MUST be an object")
    unknown = sorted(set(value) - _RECEIPT_FIELDS)
    if unknown:
        raise NotificationReceiptFormatError(
            f"notification receipt body contains unsupported fields {unknown!r}"
        )
    return NotificationDeliveryReceipt(
        audit_id=_bounded_text(value, "audit_id"),
        channel_id=_bounded_text(value, "channel_id"),
        publication_result=_bounded_text(value, "publication_result"),
        observed_at=observed_at,
        provider_message_id=_optional_bounded_text(value, "provider_message_id"),
    )


def encode_notification_delivery_receipt(
    receipt: NotificationDeliveryReceipt,
) -> dict[str, object]:
    """Return the exact broker envelope both services validate against the schema."""
    payload: dict[str, object] = {
        "schema_version": NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt.idempotency_key,
        "audit_id": receipt.audit_id,
        "channel_id": receipt.channel_id,
        "publication_result": receipt.publication_result,
        "observed_at": receipt.observed_at.astimezone(UTC).isoformat(),
    }
    if receipt.provider_message_id is not None:
        payload["provider_message_id"] = receipt.provider_message_id
    return payload


def decode_notification_delivery_receipt(
    payload: Mapping[str, object],
) -> NotificationDeliveryReceipt:
    """Rebuild one receipt from a broker envelope without trusting extra fields."""
    if not isinstance(payload, Mapping):
        raise NotificationReceiptFormatError("notification receipt envelope MUST be an object")
    version = payload.get("schema_version")
    if version != NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION:
        raise NotificationReceiptFormatError(
            "notification receipt envelope schema_version is unsupported"
        )
    observed_raw = payload.get("observed_at")
    if not isinstance(observed_raw, str):
        raise NotificationReceiptFormatError(
            "notification receipt envelope observed_at MUST be a string"
        )
    try:
        observed_at = datetime.fromisoformat(observed_raw)
    except ValueError as exc:
        raise NotificationReceiptFormatError(
            "notification receipt envelope observed_at is invalid"
        ) from exc
    receipt = NotificationDeliveryReceipt(
        audit_id=_bounded_text(payload, "audit_id"),
        channel_id=_bounded_text(payload, "channel_id"),
        publication_result=_bounded_text(payload, "publication_result"),
        observed_at=observed_at,
        provider_message_id=_optional_bounded_text(payload, "provider_message_id"),
    )
    if payload.get("receipt_id") != receipt.idempotency_key:
        raise NotificationReceiptFormatError(
            "notification receipt envelope receipt_id does not match its delivery identity"
        )
    return receipt


def _bounded_text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item or len(item) > MAX_RECEIPT_ID_LENGTH:
        raise NotificationReceiptFormatError(f"notification receipt {field} is invalid")
    return item


def _optional_bounded_text(value: Mapping[str, object], field: str) -> str | None:
    item = value.get(field)
    if item is None:
        return None
    return _bounded_text(value, field)


__all__ = [
    "DEFAULT_RECEIPT_SKEW_SECONDS",
    "MAX_RECEIPT_BODY_BYTES",
    "MAX_RECEIPT_ID_LENGTH",
    "NOTIFICATION_DELIVERY_RECEIPT_CONSUMER_GROUP",
    "NOTIFICATION_DELIVERY_RECEIPT_SCHEMA",
    "NOTIFICATION_DELIVERY_RECEIPT_SCHEMA_VERSION",
    "NOTIFICATION_DELIVERY_RECEIPT_TOPIC",
    "PUBLICATION_RESULTS",
    "RECEIPT_SIGNATURE_HEADER",
    "RECEIPT_TIMESTAMP_HEADER",
    "NotificationDeliveryReceipt",
    "NotificationReceiptAuthenticationError",
    "NotificationReceiptFormatError",
    "compute_receipt_signature",
    "decode_notification_delivery_receipt",
    "encode_notification_delivery_receipt",
    "notification_receipt_key",
    "parse_receipt_body",
    "verify_receipt_signature",
]
