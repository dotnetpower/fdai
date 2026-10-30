from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from fdai_lifecycle_hub import setup_api

ORIGIN = "http://127.0.0.1:8099"
LAUNCH_TOKEN = "test-launch-" + "a" * 40


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<h1>Lifecycle Hub</h1>")
    (assets / "setup.js").write_text("console.log('test fixture');")
    (assets / "setup.css").write_text("body { color: black; }")
    monkeypatch.setattr(
        setup_api, "read_status", lambda root: {"phase": "idle", "deployment_ready": False}
    )
    app = setup_api.create_setup_app(
        tmp_path, origin=ORIGIN, launch_token=LAUNCH_TOKEN, assets=assets
    )
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as http:
        yield http


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/setup/api/session", json={"token": LAUNCH_TOKEN}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/setup" in cookie
    return client.get("/setup/api/status").json()["csrf_token"]


def test_setup_needs_no_runtime_database_and_never_exposes_launch_token(client):
    response = client.get("/setup")
    assert response.status_code == 200
    assert LAUNCH_TOKEN not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/setup/api/status").status_code == 401
    authenticate(client)
    assert client.get("/setup/api/status").json()["deployment_ready"] is False


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_setup_rejects_rebinding_and_cross_site_requests(client, headers):
    assert client.get("/setup", headers=headers).status_code == 403


def test_remote_client_is_denied(tmp_path):
    app = setup_api.create_setup_app(tmp_path, origin=ORIGIN, launch_token=LAUNCH_TOKEN)
    with TestClient(app, base_url=ORIGIN, client=("192.0.2.1", 50000)) as client:
        assert client.get("/setup").status_code == 403


@pytest.mark.parametrize("token", ["wrong", "잘못된 토큰", None, 42])
def test_launch_token_rejected_without_internal_error(client, token):
    response = client.post("/setup/api/session", json={"token": token}, headers={"Origin": ORIGIN})
    assert response.status_code == 401


def test_launch_exchange_is_single_use_and_exact_shape(client):
    assert client.post("/setup/api/session", json={"token": LAUNCH_TOKEN}).status_code == 403
    assert (
        client.post(
            "/setup/api/session",
            json={"token": LAUNCH_TOKEN, "extra": True},
            headers={"Origin": ORIGIN},
        ).status_code
        == 401
    )
    authenticate(client)
    assert (
        client.post(
            "/setup/api/session", json={"token": LAUNCH_TOKEN}, headers={"Origin": ORIGIN}
        ).status_code
        == 401
    )


def test_mutations_require_session_origin_and_csrf(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        setup_api,
        "submit_request",
        lambda *args: calls.append(args) or {"phase": "working"},
    )
    body = {"action": "accounts", "payload": {}}
    assert client.post("/setup/api/actions", json=body).status_code == 401
    csrf = authenticate(client)
    assert (
        client.post("/setup/api/actions", json=body, headers={"Origin": ORIGIN}).status_code == 403
    )
    assert (
        client.post("/setup/api/actions", json=body, headers={"X-FDAI-CSRF": csrf}).status_code
        == 403
    )
    assert not calls
    response = client.post(
        "/setup/api/actions",
        json=body,
        headers={"Origin": ORIGIN, "X-FDAI-CSRF": csrf},
    )
    assert response.status_code == 202
    assert calls[0][1:] == ("accounts", {})


@pytest.mark.parametrize(
    "body", [[], {"action": 1, "payload": {}}, {"action": "accounts", "payload": [], "extra": 1}]
)
def test_malformed_action_is_not_submitted(client, body):
    csrf = authenticate(client)
    response = client.post(
        "/setup/api/actions",
        json=body,
        headers={"Origin": ORIGIN, "X-FDAI-CSRF": csrf},
    )
    assert response.status_code == 409


def test_request_size_and_content_type_are_bounded(client):
    csrf = authenticate(client)
    headers = {"Origin": ORIGIN, "X-FDAI-CSRF": csrf}
    assert client.post("/setup/api/actions", content="{}", headers=headers).status_code == 409
    response = client.post(
        "/setup/api/actions",
        json={"action": "install", "payload": {"oversized": "x" * setup_api.MAX_BODY_BYTES}},
        headers=headers,
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "content",
    [
        '{"action":"accounts","action":"install","payload":{}}',
        '{"action":"install","payload":{"monthly_cost_ceiling":NaN}}',
        '{"action":"install","payload":{"monthly_cost_ceiling":1e999}}',
        "[" * 2000 + "]" * 2000,
    ],
)
def test_ambiguous_or_nonfinite_json_is_rejected(client, content):
    csrf = authenticate(client)
    response = client.post(
        "/setup/api/actions",
        content=content,
        headers={
            "Origin": ORIGIN,
            "X-FDAI-CSRF": csrf,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 409
    assert "JSON" in response.json()["error"]


def test_exact_decision_rejection_is_visible(client, monkeypatch):
    def stale(*args):
        raise ValueError("The current review changed; refresh before deciding.")

    monkeypatch.setattr(setup_api, "submit_decision", stale)
    csrf = authenticate(client)
    response = client.post(
        "/setup/api/decisions",
        json={"review_id": "stale"},
        headers={"Origin": ORIGIN, "X-FDAI-CSRF": csrf},
    )
    assert response.status_code == 409
    assert "review changed" in response.json()["error"]


def test_state_storage_failure_is_not_empty_success(client, monkeypatch):
    def unavailable(*args):
        raise OSError("private diagnostic detail")

    monkeypatch.setattr(setup_api, "read_status", unavailable)
    authenticate_response = client.post(
        "/setup/api/session", json={"token": LAUNCH_TOKEN}, headers={"Origin": ORIGIN}
    )
    assert authenticate_response.status_code == 200
    response = client.get("/setup/api/status")
    assert response.status_code == 409
    assert "private diagnostic detail" not in response.text


def test_assets_are_allowlisted(client):
    assert client.get("/setup/setup.js").status_code == 200
    assert client.get("/setup/setup.css").status_code == 200
    assert client.get("/setup/state.json").status_code == 404
    assert client.get("/setup/executor/azure").status_code == 404


def test_expired_session_cannot_submit(client, monkeypatch):
    authenticate(client)
    monkeypatch.setattr(setup_api.time, "monotonic", lambda: float("inf"))
    assert client.get("/setup/api/status").status_code == 401


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:8099", "http://0.0.0.0:8099", "http://127.0.0.1:8099/evil"],
)
def test_noncanonical_server_binding_is_rejected(tmp_path, origin):
    with pytest.raises(ValueError, match="loopback"):
        setup_api.create_setup_app(tmp_path, origin=origin, launch_token=LAUNCH_TOKEN)
