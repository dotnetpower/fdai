"""Webhook ingress - normalize authenticated external HTTP triggers to events.

Design contract: ``docs/roadmap/app-shape.instructions.md`` (event-driven,
scale-to-zero; no always-on polling) and the Azure SRE Agent parity note in
``docs/internals/sre-agent-gap-analysis.md`` (P2-7). The console read API is
read-only; ingestion is otherwise Kafka-only. This adapter adds an inbound
webhook path: it authenticates a raw HTTP request, normalizes the JSON body
into an :class:`Event`, and publishes it onto the event-ingest topic, so the
standard trust-router + risk-gate govern anything autonomous. The webhook
never executes a change - it only injects an event.

Transport-agnostic
------------------

This module takes raw ``(headers, body: bytes)`` and returns a
:class:`WebhookResult`; it does not import a web framework. The composition
root mounts it behind whatever ingress the deployment uses (Container Apps
ingress, FastAPI route). That keeps it unit-testable without a server.

Security (OWASP)
----------------

- **Signature verification**: every request MUST carry an HMAC-SHA256
  signature over the raw body, verified with a constant-time compare
  (:func:`hmac.compare_digest`). A missing / bad signature is rejected
  before the body is parsed. The signing secret is injected (read from a
  ``SecretProvider`` at the composition root), never hard-coded.
- **Bounded body**: a body over ``max_body_bytes`` is rejected to bound
  memory and parse cost.
- **Fail-closed**: an unverified signature, oversized body, or unparseable
  JSON is rejected and nothing is published. No partial ingestion.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)

WEBHOOK_EVENT_TOPIC = "aw.webhook.events"
_SOURCE = "fdai.delivery.webhook"
_DEFAULT_MAX_BODY_BYTES: Final[int] = 256 * 1024


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    """Configuration for the webhook ingress.

    ``event_type_field`` / ``resource_field`` name JSON keys read from the
    body; when the key is absent, ``default_event_type`` / ``None`` apply.
    ``delivery_id_header`` supplies a stable idempotency key from the
    sender (e.g. GitHub ``X-GitHub-Delivery``); absent it, a hash of the
    body is used.
    """

    signature_header: str = "X-FDAI-Signature"
    delivery_id_header: str = "X-FDAI-Delivery"
    event_type_field: str = "event_type"
    resource_field: str = "resource_ref"
    default_event_type: str = "webhook.trigger"
    topic: str = WEBHOOK_EVENT_TOPIC
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    mode: Mode = Mode.SHADOW

    def __post_init__(self) -> None:
        if self.max_body_bytes <= 0:
            raise ValueError("WebhookConfig.max_body_bytes MUST be positive")


@dataclass(frozen=True, slots=True)
class WebhookResult:
    """Outcome of one ingress attempt."""

    accepted: bool
    reason: str
    event_id: str | None = None
    idempotency_key: str | None = None


def _lower_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def verify_signature(*, secret: str, body: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA256 verification of ``body``.

    Accepts an optional ``sha256=`` prefix (GitHub-style). Returns False on
    a missing or malformed signature - never raises.
    """
    if not provided:
        return False
    candidate = provided.split("=", 1)[1] if provided.startswith("sha256=") else provided
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate, expected)


class WebhookIngress:
    """Authenticate, normalize, and publish an inbound webhook request."""

    def __init__(
        self,
        *,
        config: WebhookConfig,
        signing_secret: str,
        event_bus: EventBus,
    ) -> None:
        if not signing_secret:
            raise ValueError("WebhookIngress.signing_secret MUST be non-empty")
        self._config: Final[WebhookConfig] = config
        self._secret: Final[str] = signing_secret
        self._bus: Final[EventBus] = event_bus

    async def handle(self, *, headers: dict[str, str], body: bytes) -> WebhookResult:
        if len(body) > self._config.max_body_bytes:
            return WebhookResult(accepted=False, reason="body too large")

        low = _lower_headers(headers)
        signature = low.get(self._config.signature_header.lower())
        if not verify_signature(secret=self._secret, body=body, provided=signature):
            return WebhookResult(accepted=False, reason="invalid signature")

        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return WebhookResult(accepted=False, reason="unparseable JSON body")
        if not isinstance(parsed, dict):
            return WebhookResult(accepted=False, reason="body is not a JSON object")

        idempotency_key = low.get(self._config.delivery_id_header.lower()) or (
            "webhook:" + hashlib.sha256(body).hexdigest()
        )
        event = self._build_event(parsed, idempotency_key)
        key = event.resource_ref or idempotency_key
        try:
            await self._bus.publish(self._config.topic, key, event.model_dump(mode="json"))
        except Exception as exc:  # noqa: BLE001 - surface a clean rejection, no partial state
            _LOGGER.warning("webhook_publish_failed", extra={"error": str(exc)})
            return WebhookResult(accepted=False, reason="publish failed")

        return WebhookResult(
            accepted=True,
            reason="accepted",
            event_id=str(event.event_id),
            idempotency_key=idempotency_key,
        )

    def _build_event(self, parsed: dict[str, Any], idempotency_key: str) -> Event:
        now = datetime.now(tz=UTC)
        event_type = parsed.get(self._config.event_type_field)
        resource_ref = parsed.get(self._config.resource_field)
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=idempotency_key,
            source=_SOURCE,
            event_type=str(event_type) if event_type else self._config.default_event_type,
            resource_ref=str(resource_ref) if resource_ref else None,
            payload={"webhook": parsed},
            detected_at=now,
            ingested_at=now,
            mode=self._config.mode,
        )


__all__ = [
    "WEBHOOK_EVENT_TOPIC",
    "WebhookConfig",
    "WebhookIngress",
    "WebhookResult",
    "verify_signature",
]
