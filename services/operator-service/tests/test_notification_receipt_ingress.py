"""Bounded authenticated notification publication receipt ingress."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai_operator_service.environment import (
    NOTIFICATION_RECEIPT_SECRET_ENV,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.families.iam import IamFamilyBindings, make_iam_family_routes
from fdai_operator_service.iam_composition import build_notification_receipt_ingress
from fdai_operator_service.notification_receipt_ingress import (
    NotificationReceiptIngress,
    NotificationReceiptIngressConfig,
    NotificationReceiptPublicationError,
)
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
    NotificationReceiptAuthenticationError,
    NotificationReceiptFormatError,
    compute_receipt_signature,
)
from fdai_service_contracts.operator import OperatorPrincipal, OperatorRole
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 4, 7, 0, tzinfo=UTC)
SECRET = "synthetic-receipt-secret"  # noqa: S105 - test fixture, not a credential


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        stored = self.values.get(key)
        return dict(stored) if stored is not None else None

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        self.values[key] = dict(value)


class RecordingPublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, str, dict[str, object]]] = []
        self._fail = fail

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> object:
        if self._fail:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))
        return None


def _body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "audit_id": "audit-1",
        "channel_id": "teams-ops",
        "publication_result": "published",
        "provider_message_id": "run-1",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode()


def _headers(body: bytes, *, at: datetime = NOW) -> dict[str, str]:
    timestamp = at.isoformat()
    signature = compute_receipt_signature(secret=SECRET, timestamp=timestamp, body=body)
    return {
        "X-FDAI-Timestamp": timestamp,
        "X-FDAI-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }


def _ingress(
    *,
    store: MemoryStore | None = None,
    publisher: RecordingPublisher | None = None,
) -> NotificationReceiptIngress:
    return NotificationReceiptIngress(
        config=NotificationReceiptIngressConfig(
            secret=SECRET,
            topic=NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        ),
        store=store or MemoryStore(),
        publisher=publisher or RecordingPublisher(),
        validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
        clock=lambda: NOW,
    )


def test_ingress_binding_requires_canonical_topic_and_physical_topic() -> None:
    store = cast(Any, MemoryStore())
    publisher = cast(Any, RecordingPublisher())
    missing_physical = SimpleNamespace(
        values={NOTIFICATION_RECEIPT_SECRET_ENV: SECRET},
        notification_receipt_topic=NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        semantic_physical_topic=None,
    )
    with pytest.raises(OperatorServiceConfigurationError, match="PHYSICAL_TOPIC"):
        build_notification_receipt_ingress(
            environment=cast(Any, missing_physical),
            store=store,
            semantic_bus=publisher,
        )

    noncanonical = SimpleNamespace(
        values={NOTIFICATION_RECEIPT_SECRET_ENV: SECRET},
        notification_receipt_topic="fdai.notifications.delivery-receipts-prod",
        semantic_physical_topic="fdai.pantheon.objects",
    )
    with pytest.raises(OperatorServiceConfigurationError, match="canonical logical topic"):
        build_notification_receipt_ingress(
            environment=cast(Any, noncanonical),
            store=store,
            semantic_bus=publisher,
        )


async def test_authenticated_receipt_is_published_without_endpoint_material() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher()
    ingress = _ingress(store=store, publisher=publisher)
    body = _body()

    receipt = await ingress.accept(headers=_headers(body), body=body)

    assert receipt.published is True
    topic, key, payload = publisher.published[0]
    assert topic == NOTIFICATION_DELIVERY_RECEIPT_TOPIC
    assert key == "audit-1"
    assert set(payload) == {
        "schema_version",
        "receipt_id",
        "audit_id",
        "channel_id",
        "publication_result",
        "observed_at",
        "provider_message_id",
    }
    assert "webhook_url" not in repr(store.values)


async def test_repeated_identical_receipt_does_not_republish() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher()
    ingress = _ingress(store=store, publisher=publisher)
    body = _body()

    await ingress.accept(headers=_headers(body), body=body)
    await ingress.accept(headers=_headers(body), body=body)

    assert len(publisher.published) == 1


async def test_a_different_result_is_a_separate_observation_core_arbitrates() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher()
    ingress = _ingress(store=store, publisher=publisher)
    published = _body()
    failed = _body(publication_result="failed")

    await ingress.accept(headers=_headers(published), body=published)
    await ingress.accept(headers=_headers(failed), body=failed)

    # The ingress never decides which observation wins: it records both under
    # distinct keys and lets Core apply the authoritative delivery transition.
    assert len(publisher.published) == 2
    assert len(store.values) == 2


async def test_a_replayed_key_with_a_different_delivery_is_refused() -> None:
    store = MemoryStore()
    ingress = _ingress(store=store)
    body = _body()
    await ingress.accept(headers=_headers(body), body=body)
    recorded_key = next(iter(store.values))
    store.values[recorded_key]["channel_id"] = "teams-other"

    with pytest.raises(NotificationReceiptFormatError, match="conflicts"):
        await ingress.accept(headers=_headers(body), body=body)


async def test_unauthenticated_oversized_and_malformed_receipts_are_refused() -> None:
    ingress = _ingress()
    body = _body()

    tampered = _headers(body)
    tampered["X-FDAI-Signature"] = "sha256=deadbeef"
    with pytest.raises(NotificationReceiptAuthenticationError):
        await ingress.accept(headers=tampered, body=body)

    stale = _headers(body, at=NOW - timedelta(hours=1))
    with pytest.raises(NotificationReceiptAuthenticationError):
        await ingress.accept(headers=stale, body=body)

    oversized = b"x" * 5000
    with pytest.raises(NotificationReceiptFormatError, match="limit"):
        await ingress.accept(headers=_headers(oversized), body=oversized)

    forbidden = _body(message="must not be carried")
    with pytest.raises(NotificationReceiptFormatError, match="unsupported fields"):
        await ingress.accept(headers=_headers(forbidden), body=forbidden)


async def test_broker_failure_is_recorded_and_retried() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher(fail=True)
    ingress = _ingress(store=store, publisher=publisher)
    body = _body()

    with pytest.raises(NotificationReceiptPublicationError):
        await ingress.accept(headers=_headers(body), body=body)

    record = next(iter(store.values.values()))
    assert record["outcome"] == "publication_failed"

    publisher._fail = False
    await ingress.accept(headers=_headers(body), body=body)

    assert len(publisher.published) == 1
    assert next(iter(store.values.values()))["outcome"] == "published"


async def test_stale_prepared_publication_is_retried_after_the_lease() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher()
    ingress = _ingress(store=store, publisher=publisher)
    body = _body()
    receipt = await ingress.accept(headers=_headers(body), body=body)
    key = next(iter(store.values))
    store.values[key] = {
        "kind": "operator.notification-delivery-receipt",
        "receipt_id": receipt.idempotency_key,
        "audit_id": receipt.audit_id,
        "channel_id": receipt.channel_id,
        "publication_result": receipt.publication_result,
        "phase": "prepared",
        "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "attempted_at": (NOW - timedelta(minutes=1)).isoformat(),
        "attempt_count": 1,
    }
    publisher.published.clear()

    await ingress.accept(headers=_headers(body), body=body)

    assert len(publisher.published) == 1
    assert store.values[key]["outcome"] == "published"
    assert store.values[key]["attempt_count"] == 2


async def test_recent_prepared_publication_remains_leased() -> None:
    store = MemoryStore()
    publisher = RecordingPublisher()
    ingress = _ingress(store=store, publisher=publisher)
    body = _body()
    receipt = await ingress.accept(headers=_headers(body), body=body)
    key = next(iter(store.values))
    store.values[key] = {
        "kind": "operator.notification-delivery-receipt",
        "receipt_id": receipt.idempotency_key,
        "audit_id": receipt.audit_id,
        "channel_id": receipt.channel_id,
        "publication_result": receipt.publication_result,
        "phase": "prepared",
        "observed_at": NOW.isoformat(),
        "attempted_at": NOW.isoformat(),
        "attempt_count": 1,
    }
    publisher.published.clear()

    with pytest.raises(NotificationReceiptPublicationError, match="in progress"):
        await ingress.accept(headers=_headers(body), body=body)

    assert publisher.published == []


def _routes(ingress: NotificationReceiptIngress | None) -> Starlette:
    async def authorize(request: Request) -> OperatorPrincipal:
        del request
        return OperatorPrincipal(subject_id="owner-1", roles=frozenset({OperatorRole.OWNER}))

    bindings = IamFamilyBindings(
        authorize=authorize,
        authenticate=authorize,
        notification_receipt_ingress=ingress,
    )
    return Starlette(routes=list(make_iam_family_routes(bindings)))


def test_route_accepts_a_signed_receipt_and_fails_closed_without_a_binding() -> None:
    publisher = RecordingPublisher()
    body = _body()
    with TestClient(_routes(_ingress(publisher=publisher))) as client:
        accepted = client.post(
            "/runtime/integrations/notifications/delivery-receipt",
            content=body,
            headers=_headers(body),
        )
    assert accepted.status_code == 202
    assert accepted.json()["accepted"] is True
    assert "webhook_url" not in accepted.text
    assert len(publisher.published) == 1

    with TestClient(_routes(None)) as client:
        unavailable = client.post(
            "/runtime/integrations/notifications/delivery-receipt",
            content=body,
            headers=_headers(body),
        )
    assert unavailable.status_code == 503


def test_route_rejects_an_unsigned_receipt_with_401() -> None:
    body = _body()
    with TestClient(_routes(_ingress())) as client:
        response = client.post(
            "/runtime/integrations/notifications/delivery-receipt",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 401


def test_ingress_config_rejects_unbounded_or_missing_inputs() -> None:
    with pytest.raises(ValueError, match="secret"):
        NotificationReceiptIngressConfig(secret="", topic="t")
    with pytest.raises(ValueError, match="topic"):
        NotificationReceiptIngressConfig(secret=SECRET, topic="  ")
    with pytest.raises(ValueError, match="max_body_bytes"):
        NotificationReceiptIngressConfig(secret=SECRET, topic="t", max_body_bytes=99_999)
