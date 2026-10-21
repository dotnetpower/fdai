"""End-to-end validation of the Direct Line-compatible example relay."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import httpx
from fdai.core.notifications import (
    ChannelDeliveryState,
    ChannelRegistry,
    InMemoryNotificationDeliveryStore,
    NotificationRouter,
    RouteOutcome,
    load_matrix_from_mapping,
)
from fdai.delivery.notifications import (
    DirectLineConfig,
    DirectLineNotificationChannel,
    NotificationDeliveryReceiptApplier,
    static_direct_line_credential,
)
from fdai.shared.providers.notifications import (
    NotificationChannel,
    NotificationMessage,
    TrustTier,
)
from fdai.shared.providers.testing.notifications import FakeHilEscalationSink
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_operator_service.notification_receipt_ingress import (
    NotificationReceiptIngress,
    NotificationReceiptIngressConfig,
)
from fdai_service_contracts.notification_receipt import (
    NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
    decode_notification_delivery_receipt,
)
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PATH = ROOT / "examples/direct_line_relay/direct_line_relay.py"
NOW = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)
CHANNEL = "direct-line-example"
CONVERSATION = "example-conversation"
BEARER_SECRET = "synthetic-relay-secret"
RECEIPT_SECRET = "synthetic-receipt-secret"


def _load_example() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fdai_direct_line_relay_example",
        EXAMPLE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, object]] = {}

    async def create_state(self, key: str, value: Mapping[str, object]) -> bool:
        if key in self.values:
            return False
        self.values[key] = dict(value)
        return True

    async def read_state(self, key: str) -> dict[str, object] | None:
        value = self.values.get(key)
        return dict(value) if value is not None else None

    async def write_state(self, key: str, value: Mapping[str, object]) -> None:
        self.values[key] = dict(value)


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, object]] = []
        self.ready = threading.Event()

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, object],
    ) -> None:
        assert topic == NOTIFICATION_DELIVERY_RECEIPT_TOPIC
        assert key == "audit-example-relay"
        self.published.append(payload)
        self.ready.set()


class ReceiptServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, ingress: NotificationReceiptIngress) -> None:
        self.ingress = ingress
        super().__init__(("127.0.0.1", 0), ReceiptHandler)


class ReceiptHandler(BaseHTTPRequestHandler):
    server: ReceiptServer

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        headers = {key: value for key, value in self.headers.items()}
        asyncio.run(self.server.ingress.accept(headers=headers, body=body))
        encoded = b'{"accepted":true}'
        self.send_response(HTTPStatus.ACCEPTED)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def _message() -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="incident-example-relay",
        audit_id="audit-example-relay",
        title="Example relay alert",
        body_markdown="The loopback relay validates delivery without a provider environment.",
    )


def _router(
    channel: DirectLineNotificationChannel,
    delivery_store: InMemoryNotificationDeliveryStore,
) -> NotificationRouter:
    return NotificationRouter(
        matrix=load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "operational_alert",
                    "routes": {
                        "operational_alert": {
                            "trust_tier": "a2_operational_alert",
                            "delivery_mode": "fanout",
                            "channels": [CHANNEL],
                        }
                    },
                }
            }
        ),
        registry=ChannelRegistry(
            channels={CHANNEL: cast(NotificationChannel, channel)},
        ),
        audit_store=InMemoryStateStore(),
        hil_sink=FakeHilEscalationSink(),
        delivery_store=delivery_store,
        retry_backoff_seconds=0,
    )


async def test_example_relay_converges_signed_receipt_and_suppresses_replay(
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    ingress = NotificationReceiptIngress(
        config=NotificationReceiptIngressConfig(
            secret=RECEIPT_SECRET,
            topic=NOTIFICATION_DELIVERY_RECEIPT_TOPIC,
        ),
        store=cast(Any, MemoryStore()),
        publisher=cast(Any, publisher),
        validator=JsonSchemaContractValidator(PackageResourceSchemaRegistry()),
    )
    receipt_server = ReceiptServer(ingress)
    receipt_thread = threading.Thread(target=receipt_server.serve_forever, daemon=True)
    receipt_thread.start()
    receipt_port = receipt_server.server_address[1]

    state_file = tmp_path / "relay-state.json"
    relay_process = subprocess.Popen(  # noqa: S603 - fixed local example command.
        [
            sys.executable,
            str(EXAMPLE_PATH),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--conversation-id",
            CONVERSATION,
            "--receipt-url",
            (
                f"http://127.0.0.1:{receipt_port}"
                "/runtime/integrations/notifications/delivery-receipt"
            ),
            "--state-file",
            str(state_file),
        ],
        env={
            **os.environ,
            "FDAI_EXAMPLE_DIRECT_LINE_SECRET": BEARER_SECRET,
            "FDAI_NOTIFICATION_RECEIPT_SECRET": RECEIPT_SECRET,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert relay_process.stdout is not None
    listening = json.loads(relay_process.stdout.readline())
    assert listening["event"] == "listening"
    relay_endpoint = cast(str, listening["endpoint"])

    delivery_store = InMemoryNotificationDeliveryStore()
    events: list[dict[str, object]] = []
    try:
        async with httpx.AsyncClient() as client:
            channel = DirectLineNotificationChannel(
                config=DirectLineConfig(
                    channel_id=CHANNEL,
                    endpoint=relay_endpoint,
                    conversation_id=CONVERSATION,
                    trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
                    allow_insecure_loopback=True,
                ),
                http_client=client,
                credential_provider=static_direct_line_credential(BEARER_SECRET),
                clock=lambda: NOW,
            )
            router = _router(channel, delivery_store)
            accepted = await router.dispatch(_message())

            assert accepted.deliveries[0].state is ChannelDeliveryState.ACCEPTED
            events.append(json.loads(relay_process.stdout.readline()))
            assert publisher.ready.wait(timeout=5)
            events.append(json.loads(relay_process.stdout.readline()))
            duplicate = await channel.send(_message())
            events.append(json.loads(relay_process.stdout.readline()))
            receipt = decode_notification_delivery_receipt(publisher.published[0])
            applied = await NotificationDeliveryReceiptApplier(
                delivery_store=delivery_store,
                audit_store=InMemoryStateStore(),
                clock=lambda: NOW,
            ).apply(receipt)
            replayed = await router.dispatch(_message())
    finally:
        if relay_process.poll() is None:
            relay_process.terminate()
        relay_process.wait(timeout=5)
        receipt_server.shutdown()
        receipt_server.server_close()
        receipt_thread.join(timeout=5)

    assert applied.state is ChannelDeliveryState.DELIVERED
    assert duplicate.provider_message_id == accepted.deliveries[0].provider_message_id
    assert replayed.outcome is RouteOutcome.DELIVERED_ALL
    assert replayed.terminal is True
    assert [event["event"] for event in events] == [
        "activity_accepted",
        "receipt_published",
        "activity_accepted",
    ]
    assert events[-1]["duplicate"] is True
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert len(state) == 1
    assert next(iter(state.values()))["receipt_status"] == "published"
    assert BEARER_SECRET not in json.dumps(state)
    assert RECEIPT_SECRET not in json.dumps(events)


def test_example_relay_rejects_unauthenticated_and_interactive_activity(
    tmp_path: Path,
) -> None:
    example = _load_example()
    config = example.RelayConfig(
        host="127.0.0.1",
        port=0,
        conversation_id=CONVERSATION,
        receipt_url=("http://127.0.0.1:1/runtime/integrations/notifications/delivery-receipt"),
        state_file=tmp_path / "relay-state.json",
    )
    server = example.create_server(
        config,
        bearer_secret=BEARER_SECRET,
        receipt_secret=RECEIPT_SECRET,
        output=io.StringIO(),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/v3/directline/conversations/{CONVERSATION}/activities"
    try:
        with httpx.Client() as client:
            unauthenticated = client.post(url, json={})
            interactive = client.post(
                url,
                headers={"Authorization": f"Bearer {BEARER_SECRET}"},
                json={
                    "type": "message",
                    "textFormat": "markdown",
                    "attachments": [{"contentType": "application/example"}],
                    "channelData": {"fdai": {"read_only": True}},
                },
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert unauthenticated.status_code == HTTPStatus.UNAUTHORIZED
    assert interactive.status_code == HTTPStatus.BAD_REQUEST
    assert not config.state_file.exists()
