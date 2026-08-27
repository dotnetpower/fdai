"""Authenticated Teams Workflows publication receipt handling."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fdai.core.notifications.delivery import (
    ChannelDeliveryRecord,
    NotificationDeliveryStore,
)
from fdai.shared.providers.state_store import StateStore

_MAX_BODY_BYTES: Final[int] = 4096
_MAX_ID_LENGTH: Final[int] = 256


@dataclass(frozen=True, slots=True)
class TeamsWorkflowReceiptConfig:
    secret: str
    max_skew_seconds: int = 300
    max_body_bytes: int = _MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("Teams Workflow receipt secret MUST be non-empty")
        if self.max_skew_seconds < 1 or self.max_body_bytes < 1:
            raise ValueError("Teams Workflow receipt bounds MUST be positive")


class TeamsWorkflowReceiptHandler:
    """Verify one bounded callback and apply its observed publication result."""

    def __init__(
        self,
        *,
        config: TeamsWorkflowReceiptConfig,
        delivery_store: NotificationDeliveryStore,
        audit_store: StateStore,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._config = config
        self._delivery_store = delivery_store
        self._audit_store = audit_store
        self._clock = clock

    async def handle(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> ChannelDeliveryRecord:
        now = self._clock()
        if now.tzinfo is None:
            raise RuntimeError("Teams Workflow receipt clock MUST be timezone-aware")
        if len(body) > self._config.max_body_bytes:
            raise ValueError("Teams Workflow receipt body exceeds the configured limit")
        normalized = {key.casefold(): value for key, value in headers.items()}
        timestamp = normalized.get("x-fdai-timestamp", "")
        signature = normalized.get("x-fdai-signature", "")
        _verify_signature(
            config=self._config,
            timestamp=timestamp,
            signature=signature,
            body=body,
            now=now,
        )
        receipt = _parse_receipt(body)
        audit_id = receipt["audit_id"]
        channel_id = receipt["channel_id"]
        result = receipt["publication_result"]
        provider_message_id = receipt.get("provider_message_id")
        audit_base = {
            "actor": "fdai.delivery.notifications.teams-workflow-receipt",
            "action_kind": "notification.delivery.observed",
            "audit_id": audit_id,
            "channel_id": channel_id,
            "publication_result": result,
            "provider_message_id": provider_message_id,
            "recorded_at": now.astimezone(UTC).isoformat(),
        }
        await self._audit_store.append_audit_entry(
            {
                **audit_base,
                "phase": "prepared",
                "intended_delivery_state": (
                    "delivered" if result == "published" else "retryable_failed"
                ),
            }
        )
        if result == "published":
            record = await self._delivery_store.confirm_delivered(
                audit_id=audit_id,
                channel_id=channel_id,
                at=now,
                provider_message_id=provider_message_id,
            )
        else:
            record = await self._delivery_store.record_publication_failure(
                audit_id=audit_id,
                channel_id=channel_id,
                at=now,
                error="Teams Workflow reported publication failure",
            )
        await self._audit_store.append_audit_entry(
            {
                **audit_base,
                "phase": "completed",
                "delivery_state": record.state.value,
                "provider_message_id": record.provider_message_id,
            }
        )
        return record


def compute_receipt_signature(*, secret: str, timestamp: str, body: bytes) -> str:
    material = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _verify_signature(
    *,
    config: TeamsWorkflowReceiptConfig,
    timestamp: str,
    signature: str,
    body: bytes,
    now: datetime,
) -> None:
    if not timestamp or not signature.startswith("sha256="):
        raise PermissionError("Teams Workflow receipt signature is missing or malformed")
    try:
        observed_at = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise PermissionError("Teams Workflow receipt timestamp is invalid") from exc
    if observed_at.tzinfo is None:
        raise PermissionError("Teams Workflow receipt timestamp MUST be timezone-aware")
    if abs((now - observed_at).total_seconds()) > config.max_skew_seconds:
        raise PermissionError("Teams Workflow receipt timestamp is outside the allowed window")
    expected = compute_receipt_signature(
        secret=config.secret,
        timestamp=timestamp,
        body=body,
    )
    if not hmac.compare_digest(expected, signature[len("sha256=") :]):
        raise PermissionError("Teams Workflow receipt signature mismatch")


def _parse_receipt(body: bytes) -> dict[str, str]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Teams Workflow receipt body is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Teams Workflow receipt body MUST be an object")
    allowed = {
        "audit_id",
        "channel_id",
        "publication_result",
        "provider_message_id",
    }
    if set(value) - allowed:
        raise ValueError("Teams Workflow receipt body contains unsupported fields")
    result: dict[str, str] = {}
    for field in ("audit_id", "channel_id", "publication_result"):
        item = value.get(field)
        if not isinstance(item, str) or not item or len(item) > _MAX_ID_LENGTH:
            raise ValueError(f"Teams Workflow receipt {field} is invalid")
        result[field] = item
    if result["publication_result"] not in {"published", "failed"}:
        raise ValueError("Teams Workflow publication_result is invalid")
    provider_message_id = value.get("provider_message_id")
    if provider_message_id is not None:
        if (
            not isinstance(provider_message_id, str)
            or not provider_message_id
            or len(provider_message_id) > _MAX_ID_LENGTH
        ):
            raise ValueError("Teams Workflow receipt provider_message_id is invalid")
        result["provider_message_id"] = provider_message_id
    return result


__all__ = [
    "TeamsWorkflowReceiptConfig",
    "TeamsWorkflowReceiptHandler",
    "compute_receipt_signature",
]
