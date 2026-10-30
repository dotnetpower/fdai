"""HTTP socket-pair boundary tests; no network, GitHub, Azure or worker is contacted."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from scripts.automation.runner_controller.service import MAX_BODY, handler


@pytest.fixture
def endpoint():
    class Broker:
        def bootstrap(self, worker, ticket):
            if worker != "owned" or ticket != "synthetic-ticket":
                raise ValueError("invalid ticket")
            return "synthetic-jit"

        def lifecycle(self, event, payload):
            raise ValueError("invalid lifecycle")

    wake, stop = threading.Event(), threading.Event()
    controller = SimpleNamespace(
        settings=SimpleNamespace(repository="example/repository"), last_success=datetime.now(UTC)
    )
    return handler(Broker(), controller, wake, "synthetic-webhook", stop), wake, stop


def _request(endpoint, method, path, body=b"", headers=None):
    client, server = socket.socketpair()
    client.settimeout(3)
    server.settimeout(3)
    thread = threading.Thread(target=endpoint[0], args=(server, ("127.0.0.1", 0), None))
    thread.start()
    fields = {"Host": "localhost", "Content-Length": str(len(body)), **(headers or {})}
    request = f"{method} {path} HTTP/1.0\r\n"
    request += "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
    try:
        client.sendall(request.encode() + body)
        response = http.client.HTTPResponse(client)
        response.begin()
        return response.status, json.loads(response.read())
    finally:
        client.close()
        server.close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_health_and_shutdown_do_not_claim_worker_readiness(endpoint) -> None:
    status, data = _request(endpoint, "GET", "/health")
    assert status == 200 and data == {"ready": True, "authority": "ci-pools-only"}
    endpoint[2].set()
    assert _request(endpoint, "GET", "/health")[0] == 503
    assert _request(endpoint, "POST", "/bootstrap", b"{}")[0] == 503


def test_ticket_validation_and_response_shape(endpoint) -> None:
    assert (
        _request(endpoint, "POST", "/bootstrap", b'{"worker_id":"unknown","ticket":"x"}')[0] == 409
    )
    status, data = _request(
        endpoint,
        "POST",
        "/bootstrap",
        b'{"worker_id":"owned","ticket":"synthetic-ticket"}',
    )
    assert status == 200 and data == {"encoded_jit_config": "synthetic-jit"}


@pytest.mark.parametrize("body", [b"[]", b"null", b"{bad", b"{}"])
def test_invalid_bootstrap_requests_have_explicit_errors(endpoint, body: bytes) -> None:
    assert _request(endpoint, "POST", "/bootstrap", body)[0] == 409
    assert not endpoint[1].is_set()


def test_oversize_body_is_rejected_without_reading_it(endpoint) -> None:
    assert (
        _request(endpoint, "POST", "/bootstrap", b"{}", {"Content-Length": str(MAX_BODY + 1)})[0]
        == 413
    )


@pytest.mark.parametrize(
    "event", [[], {"repository": []}, {"repository": {"full_name": "other/repo"}}]
)
def test_even_signed_unexpected_webhook_data_never_wakes_controller(endpoint, event) -> None:
    body = json.dumps(event).encode()
    signature = hmac.new(b"synthetic-webhook", body, hashlib.sha256).hexdigest()
    assert (
        _request(
            endpoint,
            "POST",
            "/webhook",
            body,
            {
                "X-Hub-Signature-256": f"sha256={signature}",
                "X-GitHub-Event": "workflow_job",
            },
        )[0]
        == 400
    )
    assert not endpoint[1].is_set()


def test_unsigned_webhook_and_unknown_paths_are_rejected(endpoint) -> None:
    assert _request(endpoint, "POST", "/webhook", b"{}")[0] == 401
    assert _request(endpoint, "POST", "/bootstrap?ticket=synthetic-ticket", b"{}")[0] == 404
    assert not endpoint[1].is_set()
