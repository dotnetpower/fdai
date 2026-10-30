"""HTTPS-terminated broker with fixed endpoints, not an arbitrary provider-operation gateway."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import socket
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from scripts.automation.runner_controller.azure import AzureAPI, ManagedIdentityToken
from scripts.automation.runner_controller.broker import Broker
from scripts.automation.runner_controller.config import Settings, policies
from scripts.automation.runner_controller.controller import Controller
from scripts.automation.runner_controller.github import GitHubAPI
from scripts.automation.runner_controller.state import BlobState, LeaseLostError
from scripts.automation.runner_controller.transport import ProviderError
from scripts.automation.runner_controller.workers import Workers

MAX_BODY = 2 * 1024 * 1024
LEASE_HANDOVER_SECONDS = 90.0


class BoundedHTTPServer(ThreadingHTTPServer):
    def __init__(
        self, address: tuple[str, int], request_handler: type[BaseHTTPRequestHandler]
    ) -> None:
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, request_handler)
        self.daemon_threads = True

    def process_request(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        if not isinstance(request, socket.socket):
            raise TypeError("controller HTTP server requires a TCP connection")
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(
        self, request: socket.socket | tuple[bytes, socket.socket], client_address: tuple[str, int]
    ) -> None:
        try:
            if not isinstance(request, socket.socket):
                raise TypeError("controller HTTP server requires a TCP connection")
            request.settimeout(10)
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def verify_webhook(secret: str, signature: str, body: bytes) -> bool:
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


class JSONHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        # Never log paths, queries, tickets, headers or request/response bodies.
        return

    def reply(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UnavailableHandler(JSONHandler):
    """Accept TCP handover probes without exposing broker or provider authority."""

    def do_GET(self) -> None:
        self.reply(503, {"ready": False, "authority": "none", "error": "controller_unavailable"})

    def do_POST(self) -> None:
        self.do_GET()


def acquire_state(state: BlobState, stop: threading.Event) -> bool:
    """Wait only for an unowned lease's expected acquire conflict, never provider outages."""
    deadline = time.monotonic() + LEASE_HANDOVER_SECONDS
    waiting = False
    while not stop.is_set():
        if time.monotonic() >= deadline:
            raise LeaseLostError("controller lease handover deadline exceeded")
        try:
            state.open()
            return not stop.is_set()
        except ProviderError as error:
            if error.status != 409 or state.alive:
                raise
            if not waiting:
                print(
                    json.dumps({"event": "controller_lease_wait", "authority": "none"}), flush=True
                )
                waiting = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LeaseLostError("controller lease handover deadline exceeded") from None
            stop.wait(min(2.0, remaining))
    return False


def handler(
    broker: Broker,
    controller: Controller,
    wake: threading.Event,
    webhook_secret: str,
    stop: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    class Handler(JSONHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self.reply(404, {"error": "unknown_endpoint"})
                return
            last = controller.last_success
            ready = (
                not stop.is_set()
                and last is not None
                and (datetime.now(UTC) - last).total_seconds() <= 60
            )
            self.reply(200 if ready else 503, {"ready": ready, "authority": "ci-pools-only"})

        def do_POST(self) -> None:
            if stop.is_set():
                self.reply(503, {"error": "controller_stopping"})
                return
            if self.path not in {"/bootstrap", "/registered", "/started", "/finished", "/webhook"}:
                self.reply(404, {"error": "unknown_endpoint"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    self.reply(413, {"error": "invalid_body_size"})
                    return
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("incomplete request body")
                if self.path == "/webhook":
                    if not verify_webhook(
                        webhook_secret, self.headers.get("X-Hub-Signature-256", ""), body
                    ):
                        self.reply(401, {"error": "invalid_webhook_signature"})
                        return
                    event = json.loads(body)
                    if (
                        not isinstance(event, dict)
                        or not isinstance(event.get("repository"), dict)
                        or self.headers.get("X-GitHub-Event") != "workflow_job"
                        or event["repository"].get("full_name") != controller.settings.repository
                    ):
                        self.reply(400, {"error": "unexpected_repository_or_event"})
                        return
                    wake.set()
                    self.reply(202, {"accepted": True})
                    return
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise ValueError("request must be an object")
                if self.path == "/bootstrap":
                    identity, ticket = payload["worker_id"], payload["ticket"]
                    if not isinstance(identity, str) or not isinstance(ticket, str):
                        raise ValueError("invalid bootstrap identity")
                    encoded = broker.bootstrap(identity, ticket)
                    self.reply(200, {"encoded_jit_config": encoded})
                else:
                    broker.lifecycle(self.path.removeprefix("/"), payload)
                    wake.set()
                    self.reply(200, {"accepted": True})
            except (ValueError, KeyError, TypeError):
                self.reply(409, {"error": "invalid_or_used_worker_request"})
            except (ProviderError, LeaseLostError, TimeoutError):
                stop.set()
                wake.set()
                self.reply(503, {"error": "controller_provider_or_lease_unavailable"})
            except (BrokenPipeError, ConnectionResetError):
                # The ticket remains claimed; no credential is minted again for a lost response.
                stop.set()
                wake.set()

    return Handler


def main() -> int:
    settings = Settings.load(
        os.environ["CONFIG_JSON"],
        apply=os.environ.get("FDAI_RUNNER_CONTROLLER_APPLY", "0") == "1",
        hostname=os.environ.get("CONTAINER_APP_HOSTNAME", ""),
    )
    token = os.environ.pop("GITHUB_RUNNER_CREDENTIAL", "")
    webhook_secret = os.environ.pop("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret in {"", "unset"}:
        webhook_secret = ""
    wake, stop = threading.Event(), threading.Event()

    def request_stop(_signal: int, _frame: Any) -> None:
        stop.set()
        wake.set()

    previous_signals = {
        number: signal.signal(number, request_stop) for number in (signal.SIGTERM, signal.SIGINT)
    }
    server: BoundedHTTPServer | None = None
    thread: threading.Thread | None = None
    state: BlobState | None = None
    result = 0
    try:
        server = BoundedHTTPServer(
            ("0.0.0.0", 8080),  # noqa: S104 - ACA terminates TLS before the replica port
            UnavailableHandler,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        if token in {"", "unset"}:
            print(
                json.dumps({"event": "controller_unavailable", "reason": "credential_unavailable"}),
                flush=True,
            )
            stop.wait()
        else:
            pool_policies, metadata = policies(Path("config/ci-runner-pools.json"))
            azure = AzureAPI(
                settings.subscription_id, settings.resource_group, ManagedIdentityToken()
            )
            lease_state = BlobState(
                settings.storage_url,
                settings.storage_container,
                settings.storage_blob,
                ManagedIdentityToken(resource="https://storage.azure.com/"),
            )
            state = lease_state
            if acquire_state(lease_state, stop):
                github = GitHubAPI(token, settings.repository)

                def ensure_effects() -> None:
                    if stop.is_set():
                        raise LeaseLostError("controller is stopping")
                    lease_state.renew()

                controller = Controller(
                    settings,
                    pool_policies,
                    metadata,
                    lease_state,
                    github,
                    Workers(settings, azure, ensure_effects),
                    stop=stop,
                )
                controller.verify_scope()
                if not stop.is_set():
                    broker = Broker(lease_state, github, metadata["pools"])
                    server.RequestHandlerClass = handler(
                        broker, controller, wake, webhook_secret, stop
                    )
                while not stop.is_set():
                    started = time.monotonic()
                    lease_state.renew()
                    receipt = controller.reconcile()
                    print(json.dumps({"event": "capacity_reconciled", **receipt}), flush=True)
                    wake.wait(settings.interval_seconds)
                    wake.clear()
                    stop.wait(max(0, 5 - (time.monotonic() - started)))
    except (
        ProviderError,
        LeaseLostError,
        ValueError,
        KeyError,
        TypeError,
        TimeoutError,
        OSError,
    ) as error:
        print(
            json.dumps(
                {
                    "event": "controller_stopped",
                    "failure_class": type(error).__name__,
                    "reason": "provider_unavailable"
                    if isinstance(error, (ProviderError, TimeoutError))
                    else "scope_or_state",
                    "provider_status": error.status if isinstance(error, ProviderError) else None,
                }
            ),
            flush=True,
        )
        result = 1
    finally:
        stop.set()
        wake.set()
        if server is not None:
            server.RequestHandlerClass = UnavailableHandler
            if thread is not None and thread.is_alive():
                server.shutdown()
                thread.join(timeout=5)
            server.server_close()
        if state is not None:
            try:
                state.close()
            except (ProviderError, LeaseLostError, OSError):
                print(json.dumps({"event": "controller_lease_release_failed"}), flush=True)
                result = 1
        for number, previous in previous_signals.items():
            signal.signal(number, previous)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
