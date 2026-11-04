"""Connection defaults, persistence, outbound bounds, and independent catalog trust."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, inspect, select
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.cli import main
from fdai_lifecycle_hub.release_connection import (
    DEFAULT_RELEASE_HUB_ENDPOINT,
    ConnectionStore,
    EndpointChange,
    endpoint_events,
    endpoint_settings,
    normalize_endpoint,
    prepare_connection_schema,
)
from fdai_lifecycle_hub.store import HubStore


@pytest.fixture
def client(store: HubStore, now: datetime, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("FDAI_RELEASE_HUB_ENDPOINT", raising=False)
    prepare_connection_schema(store.engine)
    return TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")


def update(endpoint: str | None, revision: int = 0) -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "revision": revision,
        "reason": "Reviewed read-only catalog source",
        "confirmation": f"connect release hub {endpoint or 'local-default'} {revision}",
    }


def test_default_reads_local_without_writing_settings(client: TestClient, store: HubStore) -> None:
    state = client.get("/v1/release-hub/connection").json()
    assert state == {
        "endpoint": DEFAULT_RELEASE_HUB_ENDPOINT,
        "configured_endpoint": None,
        "revision": 0,
        "source": "local-default",
        "editable": True,
        "requires_migration": False,
    }
    with store.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(endpoint_settings)) == 0
        assert connection.scalar(select(func.count()).select_from(endpoint_events)) == 0


def test_change_reset_and_stale_revision_are_audited(client: TestClient, store: HubStore) -> None:
    response = client.post("/v1/release-hub/connection", json=update("http://localhost:8091"))
    assert response.status_code == 200
    assert response.json()["source"] == "saved"
    assert response.json()["revision"] == 1
    assert client.post("/v1/release-hub/connection", json=update(None)).status_code == 409
    reset = client.post("/v1/release-hub/connection", json=update(None, 1))
    assert reset.status_code == 200
    assert reset.json()["endpoint"] == DEFAULT_RELEASE_HUB_ENDPOINT
    assert reset.json()["revision"] == 2
    with store.engine.connect() as connection:
        events = connection.execute(select(endpoint_events)).mappings().all()
    assert [event["endpoint"] for event in events] == ["http://localhost:8091", None]
    assert all(event["actor"] == "local-operator" for event in events)


def test_saved_setting_survives_new_database_connection(tmp_path: Path, now: datetime) -> None:
    url = f"sqlite:///{tmp_path / 'hub.sqlite'}"
    engine = create_engine(url)
    prepare_connection_schema(engine)
    settings = ConnectionStore(engine)
    settings.change(
        EndpointChange.model_validate(update("https://example.com")),
        actor="local-operator",
        clock=lambda: now,
    )
    engine.dispose()
    reopened = create_engine(url)
    try:
        assert ConnectionStore(reopened).status().endpoint == "https://example.com"
        assert ConnectionStore(reopened).status().revision == 1
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com",
        "http://0.0.0.0:8091",
        "file:///tmp/catalog",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?token=value",
        "https://example.com#fragment",
        "https://example.com\\catalog",
        "https://example.com%2fcatalog",
        "https://example.com:8443",
        "http://localhost:0",
    ],
)
def test_invalid_endpoints_do_not_change_settings(client: TestClient, endpoint: str) -> None:
    response = client.post("/v1/release-hub/connection", json=update(endpoint))
    assert response.status_code == 422
    assert client.get("/v1/release-hub/connection").json()["revision"] == 0


@pytest.mark.parametrize(
    "endpoint, expected",
    [
        ("http://LOCALHOST:8091/", "http://localhost:8091"),
        ("http://[::1]:8091/", "http://[::1]:8091"),
        ("https://example.com:443/", "https://example.com"),
    ],
)
def test_origins_are_canonical(endpoint: str, expected: str) -> None:
    assert normalize_endpoint(endpoint) == expected


def test_wrong_confirmation_and_cross_origin_writes_fail(client: TestClient) -> None:
    body = update("http://localhost:8091")
    body["confirmation"] = "wrong"
    assert client.post("/v1/release-hub/connection", json=body).status_code == 422
    body = update("http://localhost:8091")
    assert (
        client.post(
            "/v1/release-hub/connection", json=body, headers={"Origin": "https://example.com"}
        ).status_code
        == 403
    )
    assert client.get("/v1/release-hub/connection").json()["revision"] == 0


def test_environment_default_and_saved_override(
    store: HubStore, now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FDAI_RELEASE_HUB_ENDPOINT", "http://localhost:8099")
    prepare_connection_schema(store.engine)
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    assert client.get("/v1/release-hub/connection").json()["source"] == "environment"
    assert client.get("/v1/release-hub/connection").json()["endpoint"] == "http://localhost:8099"
    response = client.post("/v1/release-hub/connection", json=update("http://localhost:8091"))
    assert response.status_code == 200
    assert client.get("/v1/release-hub/connection").json()["source"] == "saved"
    assert client.post("/v1/release-hub/connection", json=update(None, 1)).status_code == 200
    assert client.get("/v1/release-hub/connection").json()["endpoint"] == "http://localhost:8099"


def test_deployment_catalog_is_not_redirected_by_saved_settings(
    client: TestClient, store: HubStore, now: datetime
) -> None:
    response = client.post("/v1/release-hub/connection", json=update("http://localhost:8091"))
    assert response.status_code == 200
    locked = TestClient(
        create_app(store, clock=lambda: now, release_hub_endpoint="https://example.com"),
        base_url="http://127.0.0.1:8090",
    )
    state = locked.get("/v1/release-hub/connection").json()
    assert state["source"] == "deployment"
    assert state["endpoint"] == "https://example.com"
    assert state["editable"] is False
    assert locked.post("/v1/release-hub/connection", json=update(None, 1)).status_code == 409


def mock_catalog(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []
    client_class = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **options: client_class(transport=httpx.MockTransport(respond), **options),
    )
    return requests


def test_empty_preview_has_no_synthetic_releases_or_trust(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = mock_catalog(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "revision": 0,
                "mode": "local-development",
                "expired": False,
                "releases": [],
            },
        ),
    )
    response = client.get("/v1/release-hub/catalog")
    assert response.status_code == 200
    assert response.json()["releases"] == []
    assert response.json()["release_count"] == 0
    assert response.json()["trusted"] is False
    assert response.json()["build_verification"] == "not-performed"
    assert len(requests) == 1
    assert str(requests[0].url) == DEFAULT_RELEASE_HUB_ENDPOINT + "/v1/catalog"
    assert "authorization" not in requests[0].headers


def test_preview_uses_exact_saved_source_and_recorded_releases(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = client.post("/v1/release-hub/connection", json=update("http://localhost:8099"))
    assert response.status_code == 200
    requests = mock_catalog(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "revision": 2,
                "mode": "local-development",
                "expired": True,
                "releases": [{"id": "1.0.0", "state": "draft", "manifest": "not returned"}],
            },
        ),
    )
    preview = client.get("/v1/release-hub/catalog").json()
    assert preview["releases"] == [{"id": "1.0.0", "state": "draft"}]
    assert preview["expired"] is True
    assert str(requests[0].url) == "http://localhost:8099/v1/catalog"


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_failed_preview_is_not_empty_or_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    requests = mock_catalog(
        monkeypatch,
        lambda request: httpx.Response(status, headers={"Location": "https://example.com"}),
    )
    response = client.get("/v1/release-hub/catalog")
    assert response.status_code == 503
    assert "releases" not in response.json()
    assert len(requests) == 1


def test_invalid_preview_is_explicit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_catalog(monkeypatch, lambda request: httpx.Response(200, json={"releases": []}))
    assert client.get("/v1/release-hub/catalog").status_code == 502


def test_preview_timeout_is_not_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("bounded test timeout", request=request)

    requests = mock_catalog(monkeypatch, timeout)
    response = client.get("/v1/release-hub/catalog")
    assert response.status_code == 503
    assert len(requests) == 1


def test_preview_total_deadline_cancels_a_slow_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"{"
            await asyncio.sleep(0.3)
            yield b"}"

    monkeypatch.setattr("fdai_lifecycle_hub.release_connection.PREVIEW_TIMEOUT_SECONDS", 0.05)
    requests = mock_catalog(monkeypatch, lambda request: httpx.Response(200, stream=SlowStream()))
    started = time.monotonic()
    response = client.get("/v1/release-hub/catalog")
    assert time.monotonic() - started < 1
    assert response.status_code == 503
    assert response.json()["error"] == "release_hub_catalog_unavailable"
    assert len(requests) == 1


def test_preview_response_size_is_bounded(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("fdai_lifecycle_hub.release_connection.MAX_PREVIEW_BYTES", 10)
    mock_catalog(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 11))
    response = client.get("/v1/release-hub/catalog")
    assert response.json()["error"] == "release_hub_catalog_too_large"


def test_migrate_prepares_connection_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'migrated.sqlite'}"
    monkeypatch.setenv("FDAI_LIFECYCLE_HUB_DATABASE_URL", url)
    assert main(["migrate"]) == 0
    engine = create_engine(url)
    try:
        assert inspect(engine).has_table(endpoint_settings.name)
        assert inspect(engine).has_table(endpoint_events.name)
    finally:
        engine.dispose()


def test_missing_schema_requires_explicit_migration(store: HubStore, now: datetime) -> None:
    client = TestClient(create_app(store, clock=lambda: now), base_url="http://127.0.0.1:8090")
    state = client.get("/v1/release-hub/connection").json()
    assert state["requires_migration"] is True
    assert state["editable"] is False
    assert client.post("/v1/release-hub/connection", json=update(None)).status_code == 503
