"""Tests for :mod:`fdai.delivery.read_api.provision_stream`.

Covers:

- ``TestProvisionEvent`` - validation + wire payload shape (``type`` field,
  omitted ``None`` fields, ``event="message"`` so a bare ``EventSource``
  receives it).
- ``TestSseProvisionPublisher`` - publishes onto the configured channel.
- ``TestProvisionStreamConfig`` - dataclass validation.
- ``TestProvisionRoute`` - Starlette wiring: opt-in registration, path
  collisions, read-only invariant (GET only), auth gate.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.read_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.provision_stream import (
    DEFAULT_CHANNEL,
    ProvisionEvent,
    ProvisionPhase,
    ProvisionStreamConfig,
    SseProvisionPublisher,
)
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.testing.sse import InMemorySseSink

_DEV_MODE_ENV = "FDAI_READ_API_DEV_MODE"


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


def _build_dev_app(*, provision_stream: ProvisionStreamConfig | None = None) -> Starlette:
    resolver = RoleResolver(group_mapping=_mapping())
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=resolver,
    )
    return build_app(
        authenticator=authenticator,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, provision_stream=provision_stream),
    )


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(_DEV_MODE_ENV, "1")
    yield


# ---------------------------------------------------------------------------
# ProvisionEvent
# ---------------------------------------------------------------------------


class TestProvisionEvent:
    def test_wire_type_prefixes_provision(self) -> None:
        evt = ProvisionEvent(phase=ProvisionPhase.DONE)
        assert evt.wire_type == "provision.done"

    def test_payload_carries_type_and_ts(self) -> None:
        evt = ProvisionEvent(phase=ProvisionPhase.DONE, ts="2026-07-10T00:00:00.000Z")
        payload = evt.to_payload()
        assert payload["type"] == "provision.done"
        assert payload["ts"] == "2026-07-10T00:00:00.000Z"

    def test_payload_omits_none_fields(self) -> None:
        evt = ProvisionEvent(phase=ProvisionPhase.DONE)
        payload = evt.to_payload()
        assert "fraction" not in payload
        assert "node" not in payload
        assert "reason" not in payload
        assert "console_url" not in payload

    def test_payload_includes_set_fields(self) -> None:
        evt = ProvisionEvent(
            phase=ProvisionPhase.DONE,
            fraction=1.0,
            console_url="https://console.example.com",
        )
        payload = evt.to_payload()
        assert payload["fraction"] == 1.0
        assert payload["console_url"] == "https://console.example.com"

    def test_sse_event_uses_message_name(self) -> None:
        # `event="message"` is what makes a bare EventSource.onmessage fire.
        evt = ProvisionEvent(phase=ProvisionPhase.PROGRESS, fraction=0.5)
        sse = evt.to_sse_event()
        assert sse.event == "message"
        data = json.loads(sse.data)
        assert data["type"] == "provision.progress"
        assert data["fraction"] == 0.5

    def test_sse_event_id_is_correlation_id(self) -> None:
        evt = ProvisionEvent(phase=ProvisionPhase.DONE, correlation_id="corr-1")
        assert evt.to_sse_event().id == "corr-1"

    def test_fraction_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="fraction MUST be in"):
            ProvisionEvent(phase=ProvisionPhase.PROGRESS, fraction=1.5)

    def test_waiting_requires_node(self) -> None:
        with pytest.raises(ValueError, match="MUST carry a node"):
            ProvisionEvent(phase=ProvisionPhase.WAITING)

    def test_failed_requires_node(self) -> None:
        with pytest.raises(ValueError, match="MUST carry a node"):
            ProvisionEvent(phase=ProvisionPhase.FAILED, reason="boom")


# ---------------------------------------------------------------------------
# SseProvisionPublisher
# ---------------------------------------------------------------------------


class TestSseProvisionPublisher:
    async def test_emit_publishes_on_channel(self) -> None:
        sink = InMemorySseSink()
        publisher = SseProvisionPublisher(sink=sink, channel=DEFAULT_CHANNEL)
        received: list[str] = []

        async def _reader() -> None:
            async for event in sink.subscribe(DEFAULT_CHANNEL):
                received.append(event.data)
                break

        import asyncio

        task = asyncio.create_task(_reader())
        await asyncio.sleep(0)  # let the subscriber attach
        await publisher.emit(
            ProvisionEvent(phase=ProvisionPhase.DONE, console_url="https://c.example.com")
        )
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 1
        payload = json.loads(received[0])
        assert payload["type"] == "provision.done"
        assert payload["console_url"] == "https://c.example.com"


# ---------------------------------------------------------------------------
# ProvisionStreamConfig
# ---------------------------------------------------------------------------


class TestProvisionStreamConfig:
    def test_defaults_are_sane(self) -> None:
        cfg = ProvisionStreamConfig()
        assert cfg.path == "/provision/stream"
        assert cfg.channel == DEFAULT_CHANNEL
        assert cfg.keepalive_seconds > 0
        assert cfg.sink is None

    def test_path_must_start_with_slash(self) -> None:
        with pytest.raises(ValueError, match=r"MUST start with '/'"):
            ProvisionStreamConfig(path="provision/stream")

    def test_channel_must_not_be_empty(self) -> None:
        with pytest.raises(ValueError, match="channel MUST be non-empty"):
            ProvisionStreamConfig(channel="")

    def test_keepalive_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="keepalive"):
            ProvisionStreamConfig(keepalive_seconds=0)


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class TestProvisionRoute:
    def test_route_absent_when_config_none(self, dev_env: None) -> None:
        app = _build_dev_app(provision_stream=None)
        paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
        assert "/provision/stream" not in paths

    def test_route_registered_when_config_set(self, dev_env: None) -> None:
        app = _build_dev_app(provision_stream=ProvisionStreamConfig())
        paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
        assert "/provision/stream" in paths

    def test_route_is_get_only(self, dev_env: None) -> None:
        app = _build_dev_app(provision_stream=ProvisionStreamConfig(sink=InMemorySseSink()))
        client = TestClient(app)
        resp = client.post("/provision/stream")
        assert resp.status_code == 405

    def test_path_collision_with_core_route_rejected(self, dev_env: None) -> None:
        with pytest.raises(ValueError, match="collides with a core route"):
            _build_dev_app(provision_stream=ProvisionStreamConfig(path="/kpi"))
