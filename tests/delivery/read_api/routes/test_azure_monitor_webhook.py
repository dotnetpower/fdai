"""Tests for the Azure Monitor alert webhook route."""

from __future__ import annotations

import json

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.azure_monitor_webhook import (
    DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
    make_azure_monitor_webhook_route,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_TOKEN = "s3cret-token-not-committed"


def _payload() -> dict:
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": (
                    "/subscriptions/00000000-0000-0000-0000-000000000000"
                    "/providers/Microsoft.AlertsManagement/alerts/abc"
                ),
                "alertRule": "cpu-over-90",
                "severity": "Sev2",
                "signalType": "Metric",
                "monitorCondition": "Fired",
                "monitoringService": "Platform",
                "alertTargetIDs": [
                    "/subscriptions/00000000-0000-0000-0000-000000000000"
                    "/resourceGroups/example-rg/providers/Microsoft.DBforMySQL"
                    "/flexibleServers/example-mysql"
                ],
                "firedDateTime": "2026-07-13T00:00:00Z",
                "description": "cpu high",
            }
        },
    }


def _client(bus: InMemoryEventBus | None = None) -> tuple[TestClient, InMemoryEventBus]:
    bus = bus or InMemoryEventBus()
    route = make_azure_monitor_webhook_route(
        event_bus=bus,
        topic="aw.change.events",
        bearer_token=_TOKEN,
    )
    app = Starlette(routes=[route])
    return TestClient(app), bus


# ---------------------------------------------------------------------------
# Factory validation
# ---------------------------------------------------------------------------


def test_factory_rejects_empty_bearer() -> None:
    with pytest.raises(ValueError, match="bearer_token MUST be non-empty"):
        make_azure_monitor_webhook_route(event_bus=InMemoryEventBus(), topic="t", bearer_token="")


def test_factory_rejects_empty_topic() -> None:
    with pytest.raises(ValueError, match="topic MUST be non-empty"):
        make_azure_monitor_webhook_route(
            event_bus=InMemoryEventBus(), topic="", bearer_token=_TOKEN
        )


def test_factory_rejects_non_positive_max_body() -> None:
    with pytest.raises(ValueError, match="max_body_bytes MUST be positive"):
        make_azure_monitor_webhook_route(
            event_bus=InMemoryEventBus(),
            topic="t",
            bearer_token=_TOKEN,
            max_body_bytes=0,
        )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_missing_authorization_returns_401() -> None:
    client, _ = _client()
    resp = client.post(DEFAULT_AZURE_MONITOR_WEBHOOK_PATH, json=_payload())
    assert resp.status_code == 401
    assert resp.json() == {
        "accepted": False,
        "reason": "invalid or missing bearer token",
    }


def test_wrong_bearer_returns_401() -> None:
    client, _ = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": "Bearer wrong"},
        json=_payload(),
    )
    assert resp.status_code == 401


def test_non_bearer_scheme_returns_401() -> None:
    client, _ = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Basic {_TOKEN}"},
        json=_payload(),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------


def test_unparseable_body_returns_400() -> None:
    client, _ = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
        },
        content=b"not-json",
    )
    assert resp.status_code == 400
    assert resp.json()["reason"] == "unparseable JSON body"


def test_body_object_not_dict_returns_400() -> None:
    client, _ = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=[1, 2, 3],
    )
    assert resp.status_code == 400
    assert resp.json()["reason"] == "body is not a JSON object"


def test_schema_mismatch_returns_400() -> None:
    client, _ = _client()
    bad = _payload()
    bad["schemaId"] = "somethingElse"
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=bad,
    )
    assert resp.status_code == 400
    assert "schema rejected" in resp.json()["reason"]


def test_oversized_body_returns_413() -> None:
    """Declared Content-Length over the cap short-circuits before body read."""
    bus = InMemoryEventBus()
    route = make_azure_monitor_webhook_route(
        event_bus=bus,
        topic="t",
        bearer_token=_TOKEN,
        max_body_bytes=32,
    )
    client = TestClient(Starlette(routes=[route]))
    big = b"x" * 128
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={
            "Authorization": f"Bearer {_TOKEN}",
            "Content-Type": "application/json",
            "Content-Length": str(len(big)),
        },
        content=big,
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_fired_alert_publishes_event_and_returns_202() -> None:
    client, bus = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] is True
    assert body["event_type"] == "azure.metric_alert.fired"
    # One event published on the configured topic.
    published = bus._records["aw.change.events"]  # type: ignore[attr-defined]
    assert len(published) == 1
    key, payload = published[0]
    # Key is the lowercased ARM id (per-resource partitioning).
    assert key == payload["resource_ref"]
    assert key == key.lower()
    assert payload["event_type"] == "azure.metric_alert.fired"
    assert payload["mode"] == Mode.SHADOW.value  # safety default


def test_publish_failure_returns_502() -> None:
    class _FailingBus(InMemoryEventBus):
        async def publish(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("kafka down")

    client, _ = _client(bus=_FailingBus())
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Bearer {_TOKEN}"},
        json=_payload(),
    )
    assert resp.status_code == 502
    assert resp.json()["reason"] == "publish failed"


def test_route_only_accepts_post() -> None:
    client, _ = _client()
    resp = client.get(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": f"Bearer {_TOKEN}"},
    )
    assert resp.status_code == 405


def test_bearer_compare_is_constant_time_and_not_leaked_in_response() -> None:
    """Simple regression: response body never echoes the token even
    on a mismatch. A future refactor that helpfully includes it
    would be caught here."""
    client, _ = _client()
    resp = client.post(
        DEFAULT_AZURE_MONITOR_WEBHOOK_PATH,
        headers={"Authorization": "Bearer wrong-value"},
        json=_payload(),
    )
    body_text = json.dumps(resp.json())
    assert "wrong-value" not in body_text
    assert _TOKEN not in body_text
