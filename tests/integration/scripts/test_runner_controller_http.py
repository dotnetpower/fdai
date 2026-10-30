"""HTTP socket-pair boundary tests; no network, GitHub, Azure or worker is contacted."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import signal
import socket
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scripts.automation.runner_controller import service
from scripts.automation.runner_controller.service import MAX_BODY, handler
from scripts.automation.runner_controller.state import LeaseLostError
from scripts.automation.runner_controller.transport import ProviderError


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


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/health"),
        ("POST", "/bootstrap"),
        ("POST", "/started"),
        ("POST", "/finished"),
        ("POST", "/webhook"),
    ],
)
def test_unavailable_front_has_no_broker_authority(method: str, path: str) -> None:
    status, data = _request((service.UnavailableHandler, None, None), method, path, b"{}")
    assert status == 503
    assert data == {"ready": False, "authority": "none", "error": "controller_unavailable"}


@pytest.fixture
def startup(monkeypatch: pytest.MonkeyPatch):
    calls, handlers, fronts = [], {}, []
    settings = SimpleNamespace(
        subscription_id="example",
        resource_group="workers",
        repository="example/repository",
        storage_url="https://example.blob.core.windows.net/",
        storage_container="state",
        storage_blob="state.json",
        interval_seconds=0,
    )
    monkeypatch.setenv("CONFIG_JSON", "{}")
    monkeypatch.setenv("GITHUB_RUNNER_CREDENTIAL", "synthetic-pat")
    monkeypatch.setattr(service.Settings, "load", lambda *args, **kwargs: settings)
    monkeypatch.setattr(service, "policies", lambda path: ({}, {"pools": {}}))
    for name in ("ManagedIdentityToken", "AzureAPI", "Workers", "GitHubAPI"):
        monkeypatch.setattr(service, name, Mock())

    def unavailable() -> None:
        assert (
            _request((fronts[0].RequestHandlerClass, None, None), "POST", "/bootstrap", b"{}")[0]
            == 503
        )

    class Front:
        def __init__(self, address, request_handler):
            self.RequestHandlerClass = request_handler
            self.done = threading.Event()
            self.thread = None
            fronts.append(self)
            calls.append("front_bound")

        def serve_forever(self):
            self.thread = threading.current_thread()
            self.done.wait(5)

        def shutdown(self):
            calls.append("front_shutdown")
            self.done.set()

        def server_close(self):
            calls.append("front_closed")

    class State:
        alive = False

        def open(self):
            calls.append("lease_acquire")
            unavailable()
            self.alive = True

        def renew(self):
            calls.append("lease_renew")

        def close(self):
            calls.append("lease_closed")
            self.alive = False

    state = State()
    monkeypatch.setattr(service, "BoundedHTTPServer", Front)
    monkeypatch.setattr(service, "BlobState", Mock(return_value=state))

    def capture_signal(number, callback):
        previous = handlers.get(number, signal.SIG_DFL)
        handlers[number] = callback
        return previous

    monkeypatch.setattr(service.signal, "signal", capture_signal)

    class Controller:
        last_success = None

        def __init__(self, *args, stop):
            self.stop = stop
            self.settings = settings
            calls.append("controller_created")

        def verify_scope(self):
            calls.append("scope_verified")
            unavailable()

        def reconcile(self):
            assert not self.stop.is_set()
            assert (
                _request(
                    (fronts[0].RequestHandlerClass, None, None),
                    "POST",
                    "/bootstrap",
                    b'{"worker_id":"owned","ticket":"synthetic-ticket"}',
                )[0]
                == 200
            )
            calls.append("reconciled")
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            assert self.stop.is_set()
            return {}

    broker = SimpleNamespace(
        bootstrap=Mock(return_value="synthetic-jit"),
        lifecycle=Mock(),
    )
    monkeypatch.setattr(service, "Controller", Controller)
    monkeypatch.setattr(service, "Broker", Mock(return_value=broker))
    return SimpleNamespace(
        calls=calls,
        handlers=handlers,
        fronts=fronts,
        state=state,
        broker=broker,
        unavailable=unavailable,
    )


def test_broker_activates_only_after_lease_and_scope_and_closes_threads(startup) -> None:
    assert service.main() == 0
    assert startup.calls.index("front_bound") < startup.calls.index("lease_acquire")
    assert startup.calls.index("lease_acquire") < startup.calls.index("scope_verified")
    assert startup.broker.bootstrap.call_count == 1
    assert startup.calls[-1] == "lease_closed"
    assert "front_closed" in startup.calls
    assert not startup.fronts[0].thread.is_alive()
    startup.unavailable()


def test_wrong_owner_scope_never_exposes_broker(startup, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(self):
        startup.unavailable()
        raise ValueError("synthetic owner mismatch")

    monkeypatch.setattr(service.Controller, "verify_scope", reject)
    assert service.main() == 1
    service.Broker.assert_not_called()
    startup.broker.bootstrap.assert_not_called()
    assert "lease_closed" in startup.calls
    assert not startup.fronts[0].thread.is_alive()


def test_missing_pat_keeps_unavailable_front_without_provider_effects(
    startup,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_RUNNER_CREDENTIAL", "unset")
    real_event = threading.Event
    events = []

    def event_factory():
        event = real_event()
        events.append(event)
        if len(events) == 2:

            def wait(timeout=None):
                if timeout is None:
                    startup.unavailable()
                    startup.handlers[signal.SIGTERM](signal.SIGTERM, None)
                return real_event.wait(event, timeout)

            monkeypatch.setattr(event, "wait", wait)
        return event

    monkeypatch.setattr(service.threading, "Event", event_factory)
    assert service.main() == 0
    service.BlobState.assert_not_called()
    service.GitHubAPI.assert_not_called()
    service.AzureAPI.assert_not_called()
    service.Broker.assert_not_called()
    assert "front_closed" in startup.calls


@pytest.mark.parametrize("cancel", [False, True])
def test_expected_lease_conflict_keeps_front_unavailable_until_handover(
    startup,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    original = startup.state.open
    attempts = []

    def open_state():
        attempts.append(1)
        if len(attempts) == 1:
            startup.unavailable()
            raise ProviderError("http_status", 409)
        original()

    monkeypatch.setattr(startup.state, "open", open_state)
    real_event = threading.Event
    events = []

    def event_factory():
        event = real_event()
        events.append(event)
        if len(events) == 2:

            def wait(timeout=None):
                if timeout == 2.0:
                    if cancel:
                        startup.handlers[signal.SIGTERM](signal.SIGTERM, None)
                    return cancel
                return real_event.wait(event, timeout)

            monkeypatch.setattr(
                event,
                "wait",
                wait,
            )
        return event

    monkeypatch.setattr(service.threading, "Event", event_factory)
    assert service.main() == 0
    assert len(attempts) == (1 if cancel else 2)
    assert startup.broker.bootstrap.call_count == (0 if cancel else 1)


def test_dispatch_timeout_stops_service_and_releases_authority(
    startup,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def timeout(self):
        raise TimeoutError("synthetic-ticket")

    monkeypatch.setattr(service.Controller, "reconcile", timeout)
    assert service.main() == 1
    assert not startup.state.alive
    assert not startup.fronts[0].thread.is_alive()
    startup.broker.bootstrap.assert_not_called()
    output = capsys.readouterr().out
    assert "TimeoutError" in output and "synthetic-ticket" not in output


@pytest.mark.parametrize("status,alive", [(503, False), (403, False), (409, True)])
def test_unexpected_or_owned_lease_errors_do_not_retry(
    startup,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    alive: bool,
) -> None:
    startup.state.alive = alive
    startup.state.open = Mock(side_effect=ProviderError("http_status", status))
    assert service.main() == 1
    assert startup.state.open.call_count == 1
    service.GitHubAPI.assert_not_called()
    service.Broker.assert_not_called()


def test_lease_handover_deadline_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    state = SimpleNamespace(alive=False, open=Mock(side_effect=ProviderError("http_status", 409)))
    stop = Mock()
    stop.is_set.return_value = False
    monkeypatch.setattr(service.time, "monotonic", Mock(side_effect=[0.0, 0.0, 91.0]))
    with pytest.raises(LeaseLostError, match="deadline"):
        service.acquire_state(state, stop)
    assert state.open.call_count == 1
    stop.wait.assert_not_called()
