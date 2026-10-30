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


def handler(
    broker: Broker,
    controller: Controller,
    wake: threading.Event,
    webhook_secret: str,
    stop: threading.Event,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            # Never include paths, queries, bootstrap tickets, headers or request/response bodies.
            return

        def reply(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
            except (ProviderError, LeaseLostError):
                stop.set()
                wake.set()
                self.reply(503, {"error": "controller_provider_or_lease_unavailable"})
            except (BrokenPipeError, ConnectionResetError):
                # The ticket remains claimed; no credential is minted again for a lost response.
                stop.set()

    return Handler


def main() -> int:
    settings = Settings.load(
        os.environ["CONFIG_JSON"],
        apply=os.environ.get("FDAI_RUNNER_CONTROLLER_APPLY", "0") == "1",
        hostname=os.environ.get("CONTAINER_APP_HOSTNAME", ""),
    )
    token = os.environ.pop("GITHUB_RUNNER_CREDENTIAL", "")
    if token in {"", "unset"}:
        raise ValueError("controller GitHub credential is unavailable; use direct credential setup")
    webhook_secret = os.environ.pop("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret in {"", "unset"}:
        webhook_secret = ""
    pool_policies, metadata = policies(Path("config/ci-runner-pools.json"))
    azure = AzureAPI(settings.subscription_id, settings.resource_group, ManagedIdentityToken())
    state = BlobState(
        settings.storage_url,
        settings.storage_container,
        settings.storage_blob,
        ManagedIdentityToken(resource="https://storage.azure.com/"),
    )
    state.open()
    github = GitHubAPI(token, settings.repository)
    wake, stop = threading.Event(), threading.Event()

    def ensure_effects() -> None:
        if stop.is_set():
            raise LeaseLostError("controller is stopping")
        state.renew()

    controller = Controller(
        settings, pool_policies, metadata, state, github, Workers(settings, azure, ensure_effects)
    )
    broker = Broker(state, github, metadata["pools"])

    def request_stop(_signal: int, _frame: Any) -> None:
        stop.set()
        wake.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    server = BoundedHTTPServer(
        ("0.0.0.0", 8080),  # noqa: S104 - ACA terminates TLS before the replica port
        handler(broker, controller, wake, webhook_secret, stop),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    result = 0
    try:
        controller.verify_scope()
        while not stop.is_set():
            started = time.monotonic()
            state.renew()
            receipt = controller.reconcile()
            print(json.dumps({"event": "capacity_reconciled", **receipt}), flush=True)
            wake.wait(settings.interval_seconds)
            wake.clear()
            stop.wait(max(0, 5 - (time.monotonic() - started)))
    except (ProviderError, LeaseLostError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps(
                {
                    "event": "controller_stopped",
                    "failure_class": type(error).__name__,
                    "reason": str(error) if isinstance(error, ProviderError) else "scope_or_state",
                    "provider_status": error.status if isinstance(error, ProviderError) else None,
                }
            ),
            flush=True,
        )
        result = 1
    finally:
        stop.set()
        server.shutdown()
        state.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
