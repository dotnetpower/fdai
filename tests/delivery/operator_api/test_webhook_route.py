"""End-to-end tests for the opt-in inbound webhook POST route (P2-7).

- Valid HMAC signature -> 202 + the event is published on the ingest topic.
- Bad / missing signature -> 401 and nothing is published.
- Oversized body -> 413; unparseable body -> 400.
- The route is absent by default (Operator API stays GET-only).
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from starlette.testclient import TestClient

from fdai.delivery.operator_api.auth import build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.webhook.ingress import (
    WEBHOOK_EVENT_TOPIC,
    WebhookConfig,
    WebhookIngress,
)
from fdai.shared.providers.testing import InMemoryEventBus

SECRET = "webhook-shared-secret"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _client(bus: InMemoryEventBus, *, max_body_bytes: int = 256 * 1024) -> TestClient:
    ingress = WebhookIngress(
        config=WebhookConfig(max_body_bytes=max_body_bytes),
        signing_secret=SECRET,
        event_bus=bus,
    )
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(webhook_ingress=ingress),
    )
    return TestClient(app)


def _published(bus: InMemoryEventBus) -> list:
    return bus._records.get(WEBHOOK_EVENT_TOPIC, [])  # noqa: SLF001 - test introspection


def test_valid_signature_returns_202_and_publishes() -> None:
    bus = InMemoryEventBus()
    client = _client(bus)
    body = json.dumps({"event_type": "deploy.completed", "resource_ref": "rg/vm-a"}).encode()

    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-FDAI-Signature": _sign(SECRET, body)},
    )

    assert resp.status_code == 202
    payload = resp.json()
    assert payload["accepted"] is True
    assert payload["event_id"]
    # published exactly once onto the ingest topic
    assert len(_published(bus)) == 1


def test_bad_signature_returns_401_and_does_not_publish() -> None:
    bus = InMemoryEventBus()
    client = _client(bus)
    body = json.dumps({"event_type": "deploy.completed"}).encode()

    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-FDAI-Signature": "sha256=deadbeef"},
    )

    assert resp.status_code == 401
    assert resp.json()["accepted"] is False
    assert _published(bus) == []


def test_missing_signature_returns_401() -> None:
    bus = InMemoryEventBus()
    client = _client(bus)
    body = json.dumps({"event_type": "x"}).encode()

    resp = client.post("/webhook", content=body)

    assert resp.status_code == 401
    assert _published(bus) == []


def test_oversized_content_length_returns_413() -> None:
    bus = InMemoryEventBus()
    client = _client(bus, max_body_bytes=16)
    body = json.dumps({"event_type": "x", "big": "y" * 100}).encode()

    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-FDAI-Signature": _sign(SECRET, body)},
    )

    assert resp.status_code == 413
    assert _published(bus) == []


def test_oversized_chunked_body_returns_413() -> None:
    # A chunked request (streaming content, no Content-Length) must still be
    # capped: the streaming reader aborts past max_body before buffering it.
    bus = InMemoryEventBus()
    client = _client(bus, max_body_bytes=16)
    payload = ("y" * 100).encode()

    def _chunks():
        # Yielding an iterator makes httpx use chunked transfer encoding
        # (no Content-Length header), exercising the streaming cap path.
        yield payload

    resp = client.post(
        "/webhook",
        content=_chunks(),
        headers={"X-FDAI-Signature": _sign(SECRET, payload)},
    )

    assert resp.status_code == 413
    assert _published(bus) == []


def test_unparseable_body_returns_400() -> None:
    bus = InMemoryEventBus()
    client = _client(bus)
    body = b"{not json"

    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-FDAI-Signature": _sign(SECRET, body)},
    )

    assert resp.status_code == 400
    assert _published(bus) == []


def test_non_object_body_returns_400() -> None:
    bus = InMemoryEventBus()
    client = _client(bus)
    body = b"[1, 2, 3]"

    resp = client.post(
        "/webhook",
        content=body,
        headers={"X-FDAI-Signature": _sign(SECRET, body)},
    )

    assert resp.status_code == 400
    assert _published(bus) == []


def test_webhook_route_absent_by_default() -> None:
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(),
    )
    client = TestClient(app)
    body = json.dumps({"event_type": "x"}).encode()

    resp = client.post("/webhook", content=body, headers={"X-FDAI-Signature": _sign(SECRET, body)})

    # No POST surface when the ingress is not wired -> 404/405.
    assert resp.status_code in (404, 405)


def test_webhook_path_collision_with_core_route_fails_fast() -> None:
    bus = InMemoryEventBus()
    ingress = WebhookIngress(config=WebhookConfig(), signing_secret=SECRET, event_bus=bus)
    auth = build_authenticator(verifier=lambda t: {"oid": "u"}, resolver=lambda claims: None)
    with pytest.raises(ValueError, match="collides with a core route"):
        build_app(
            authenticator=auth,
            read_model=InMemoryConsoleReadModel(),
            config=OperatorApiConfig(webhook_ingress=ingress, webhook_path="/audit"),
        )
