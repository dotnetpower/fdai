"""Tests for the webhook ingress adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

import pytest

from fdai.delivery.webhook.ingress import (
    WebhookConfig,
    WebhookIngress,
    verify_signature,
)
from fdai.shared.providers.event_bus import PublishReceipt

_SECRET = "shared-webhook-secret"  # noqa: S105 - test literal, not a real secret


class _RecordingBus:
    def __init__(self, fail: bool = False) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []
        self._fail = fail

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        if self._fail:
            raise RuntimeError("broker down")
        self.published.append((topic, key, dict(payload)))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))

    def subscribe(self, topic: str, group_id: str):  # pragma: no cover
        raise NotImplementedError

    async def dead_letter(self, topic, key, payload, reason) -> None:  # pragma: no cover
        raise NotImplementedError


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _ingress(bus: _RecordingBus | None = None) -> tuple[WebhookIngress, _RecordingBus]:
    bus = bus or _RecordingBus()
    ingress = WebhookIngress(config=WebhookConfig(), signing_secret=_SECRET, event_bus=bus)
    return ingress, bus


def test_verify_signature_valid_and_invalid() -> None:
    body = b'{"a":1}'
    assert verify_signature(secret=_SECRET, body=body, provided=_sign(body)) is True
    assert verify_signature(secret=_SECRET, body=body, provided="sha256=deadbeef") is False
    assert verify_signature(secret=_SECRET, body=body, provided=None) is False


@pytest.mark.asyncio
async def test_valid_request_is_accepted_and_published() -> None:
    ingress, bus = _ingress()
    body = json.dumps({"event_type": "alert.fired", "resource_ref": "vm-a", "sev": 2}).encode()
    result = await ingress.handle(
        headers={"X-FDAI-Signature": _sign(body), "X-FDAI-Delivery": "d-123"},
        body=body,
    )
    assert result.accepted is True
    assert result.idempotency_key == "d-123"
    topic, key, payload = bus.published[0]
    assert key == "vm-a"
    assert payload["event_type"] == "alert.fired"
    assert payload["payload"]["webhook"]["sev"] == 2


@pytest.mark.asyncio
async def test_bad_signature_rejected_without_publish() -> None:
    ingress, bus = _ingress()
    body = b'{"event_type":"x"}'
    result = await ingress.handle(headers={"X-FDAI-Signature": "sha256=bad"}, body=body)
    assert result.accepted is False
    assert result.reason == "invalid signature"
    assert bus.published == []


@pytest.mark.asyncio
async def test_oversized_body_rejected() -> None:
    bus = _RecordingBus()
    ingress = WebhookIngress(
        config=WebhookConfig(max_body_bytes=10), signing_secret=_SECRET, event_bus=bus
    )
    body = b"x" * 50
    result = await ingress.handle(headers={"X-FDAI-Signature": _sign(body)}, body=body)
    assert result.accepted is False
    assert result.reason == "body too large"
    assert bus.published == []


@pytest.mark.asyncio
async def test_unparseable_body_rejected() -> None:
    ingress, bus = _ingress()
    body = b"not json"
    result = await ingress.handle(headers={"X-FDAI-Signature": _sign(body)}, body=body)
    assert result.accepted is False
    assert result.reason == "unparseable JSON body"


@pytest.mark.asyncio
async def test_default_event_type_and_body_hash_idempotency() -> None:
    ingress, bus = _ingress()
    body = json.dumps({"no_type_here": True}).encode()
    result = await ingress.handle(headers={"X-FDAI-Signature": _sign(body)}, body=body)
    assert result.accepted is True
    assert result.idempotency_key.startswith("webhook:")
    assert bus.published[0][2]["event_type"] == "webhook.trigger"


@pytest.mark.asyncio
async def test_publish_failure_reported() -> None:
    ingress, bus = _ingress(_RecordingBus(fail=True))
    body = json.dumps({"event_type": "x"}).encode()
    result = await ingress.handle(headers={"X-FDAI-Signature": _sign(body)}, body=body)
    assert result.accepted is False
    assert result.reason == "publish failed"


def test_empty_secret_rejected() -> None:
    with pytest.raises(ValueError, match="signing_secret"):
        WebhookIngress(config=WebhookConfig(), signing_secret="", event_bus=_RecordingBus())
