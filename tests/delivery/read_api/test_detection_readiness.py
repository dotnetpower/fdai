from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from fdai.core.readiness import (
    DetectionObservationStatus,
    DetectionReadinessDimension,
    DetectionReadinessObservation,
    detection_readiness_state_key,
    reduce_detection_readiness,
)
from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 7, 24, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


def _client(reader: InMemoryStateStore | None) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, detection_readiness_reader=reader),
    )
    return TestClient(app)


def _snapshot() -> dict[str, object]:
    observation = DetectionReadinessObservation(
        resource_ref="cluster/example",
        dimension=DetectionReadinessDimension.DISCOVERED,
        status=DetectionObservationStatus.PASSED,
        observed_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(minutes=4),
        source="azure.monitor",
        evidence_digest="a" * 64,
    )
    return reduce_detection_readiness(
        (observation,),
        resource_ref="cluster/example",
        generated_at=_NOW,
    ).model_dump(mode="json")


def test_route_projects_agent_owned_snapshot_without_recomputing_decision() -> None:
    store = InMemoryStateStore()
    record = _snapshot()
    asyncio.run(
        store.write_state(
            detection_readiness_state_key("cluster/example"),
            {"kind": "detection_readiness", **record},
        )
    )

    response = _client(store).get("/detection-readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "muninn-state-snapshot"
    assert body["target_count"] == 1
    assert body["counts"]["partial"] == 1
    assert body["targets"][0]["decision"] == "partial"


def test_route_rejects_malformed_persisted_snapshot() -> None:
    store = InMemoryStateStore()
    asyncio.run(
        store.write_state(
            detection_readiness_state_key("cluster/example"),
            {"decision": "ready"},
        )
    )

    response = _client(store).get("/detection-readiness")

    assert response.status_code == 500
    assert "invalid snapshot" in response.json()["error"]["message"]


def test_route_is_opt_in_and_get_only() -> None:
    assert _client(None).get("/detection-readiness").status_code == 404
    assert _client(InMemoryStateStore()).post("/detection-readiness").status_code == 405
