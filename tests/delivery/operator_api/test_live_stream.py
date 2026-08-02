"""Tests for :mod:`fdai.delivery.operator_api.live_stream`.

The route is now a thin SSE bridge on top of the existing
:class:`~fdai.shared.providers.sse.SseSink` seam - no bespoke hub. Tests
split by concern:

- ``TestLiveStreamConfig`` - dataclass validation.
- ``TestSyntheticLiveEmitter`` - deterministic distribution + publishes
  through :class:`InMemorySseSink` on the configured channel.
- ``TestLiveRoute*`` - Starlette wiring: opt-in registration, path
  collisions, read-only invariant, auth gate.
- ``TestFrameEncoding`` - wire format for one :class:`SseEvent`.

The streaming *body* over an HTTP connection is not asserted here -
Starlette's ``TestClient`` runs the app in a worker thread which makes
mid-stream cancellation flaky. The wire contract is exercised
end-to-end with ``curl`` against the dev server (see the manual
verification section in ``docs/roadmap/rules-and-detection/observability-and-detection.md``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.delivery.operator_api.auth import UnsafeClaimsExtractor, build_authenticator
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fdai.delivery.operator_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.operator_api.streaming.live_stream import (
    LiveEmitter,
    LiveStreamConfig,
    SyntheticLiveEmitter,
    _encode_sse_event,
)
from fdai.shared.providers.sse import SseEvent
from fdai.shared.providers.testing.sse import InMemorySseSink

_DEV_MODE_ENV = "FDAI_OPERATOR_API_DEV_MODE"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _mapping() -> GroupMapping:
    return GroupMapping(
        reader_group_id="reader-group",
        contributor_group_id="contributor-group",
        approver_group_id="approver-group",
        owner_group_id="owner-group",
        break_glass_group_id="break-glass-group",
    )


class _NullEmitter(LiveEmitter):
    """No-op emitter for HTTP tests that must never publish."""

    async def start(self) -> None:  # pragma: no cover - trivial
        return None

    async def stop(self) -> None:  # pragma: no cover - trivial
        return None


def _build_dev_app(*, live_stream: LiveStreamConfig | None = None) -> Starlette:
    resolver = RoleResolver(group_mapping=_mapping())
    authenticator = build_authenticator(
        verifier=UnsafeClaimsExtractor(),
        resolver=resolver,
    )
    return build_app(
        authenticator=authenticator,
        read_model=InMemoryConsoleReadModel(),
        config=OperatorApiConfig(dev_mode=True, live_stream=live_stream),
    )


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(_DEV_MODE_ENV, "1")
    yield


# ---------------------------------------------------------------------------
# LiveStreamConfig validation
# ---------------------------------------------------------------------------


class TestLiveStreamConfig:
    def test_defaults_are_sane(self) -> None:
        cfg = LiveStreamConfig()
        assert cfg.path == "/live/stream"
        assert cfg.channel == "aw.pipeline.stages"
        assert cfg.keepalive_seconds > 0
        assert cfg.sink is None
        assert cfg.emitter_factory is None
        assert cfg.broadcaster_factory is None

    def test_path_must_start_with_slash(self) -> None:
        with pytest.raises(ValueError, match=r"MUST start with '/'"):
            LiveStreamConfig(path="live/stream")

    def test_channel_must_not_be_empty(self) -> None:
        with pytest.raises(ValueError, match="channel MUST be non-empty"):
            LiveStreamConfig(channel="")

    def test_keepalive_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="keepalive"):
            LiveStreamConfig(keepalive_seconds=0)

    def test_synthetic_and_production_factories_are_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match="at most one"):
            LiveStreamConfig(
                emitter_factory=lambda sink, channel: _NullEmitter(),
                broadcaster_factory=lambda publisher: _RecordingBroadcaster(),
            )


# ---------------------------------------------------------------------------
# Frame encoding
# ---------------------------------------------------------------------------


class TestFrameEncoding:
    def test_frame_has_id_event_data_lines(self) -> None:
        evt = SseEvent(id="abc", event="stage", data=json.dumps({"tier": "t0"}))
        wire = _encode_sse_event(evt).decode()
        lines = wire.split("\n")
        assert lines[0] == "id: abc"
        assert lines[1] == "event: stage"
        assert lines[2].startswith("data: ")
        assert json.loads(lines[2].removeprefix("data: ")) == {"tier": "t0"}
        # Blank-line terminator.
        assert lines[-1] == ""
        assert lines[-2] == ""

    def test_frame_without_id_omits_id_line(self) -> None:
        evt = SseEvent(id=None, event="stage", data="{}")
        wire = _encode_sse_event(evt).decode()
        assert not wire.startswith("id:")
        assert wire.startswith("event: stage")

    def test_frame_retry_line_included_when_present(self) -> None:
        evt = SseEvent(id="1", event="stage", data="{}", retry_ms=2000)
        wire = _encode_sse_event(evt).decode()
        assert "retry: 2000" in wire


# ---------------------------------------------------------------------------
# SyntheticLiveEmitter
# ---------------------------------------------------------------------------


class TestSyntheticLiveEmitter:
    def test_rejects_bad_config(self) -> None:
        sink = InMemorySseSink()
        with pytest.raises(ValueError):
            SyntheticLiveEmitter(sink=sink, events_per_second=0)
        with pytest.raises(ValueError):
            SyntheticLiveEmitter(
                sink=sink,
                tier_weights={"t0": 0.5, "t1": 0.5, "t2": 0.5},  # sums to 1.5
            )
        with pytest.raises(ValueError):
            SyntheticLiveEmitter(sink=sink, catalog=())

    async def test_publishes_stage_events_on_channel(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticLiveEmitter(
            sink=sink,
            channel="aw.pipeline.stages",
            events_per_second=200,
            rng_seed=1,
        )
        subscription = sink.subscribe("aw.pipeline.stages")
        await emitter.start()
        try:
            # A single control-loop pass emits several stage events; collect
            # the first few and verify the shape.
            frames = []
            for _ in range(3):
                frames.append(await asyncio.wait_for(subscription.__anext__(), timeout=1.0))
        finally:
            await emitter.stop()
            aclose = getattr(subscription, "aclose", None)
            if aclose is not None:
                await aclose()

        # Each frame carries a full StageEvent payload with the expected keys.
        for frame in frames:
            body = json.loads(frame.data)
            assert set(body.keys()) >= {"event_id", "correlation_id", "stage", "phase", "ts"}
            assert body["phase"] == "done"

    async def test_publishes_ingest_then_route_then_audit(self) -> None:
        sink = InMemorySseSink()
        emitter = SyntheticLiveEmitter(
            sink=sink,
            channel="ch-test",
            events_per_second=500,
            rng_seed=42,
        )
        subscription = sink.subscribe("ch-test")
        await emitter.start()
        try:
            first_event_id: str | None = None
            stages: list[str] = []
            for _ in range(6):
                frame = await asyncio.wait_for(subscription.__anext__(), timeout=1.0)
                body = json.loads(frame.data)
                if first_event_id is None:
                    first_event_id = body["event_id"]
                if body["event_id"] == first_event_id:
                    stages.append(body["stage"])
        finally:
            await emitter.stop()
            aclose = getattr(subscription, "aclose", None)
            if aclose is not None:
                await aclose()

        # The first stage emitted for any control-loop pass is always ingest,
        # and audit always closes it. Route always comes between them.
        assert stages[0] == "ingest"
        assert "route" in stages
        assert stages[-1] == "audit"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class TestLiveRouteRegistration:
    def test_route_not_registered_by_default(self, dev_env: None) -> None:
        del dev_env
        app = _build_dev_app(live_stream=None)
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/live/stream" not in paths

    def test_route_registered_when_configured(self, dev_env: None) -> None:
        del dev_env
        app = _build_dev_app(live_stream=LiveStreamConfig())
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/live/stream" in paths

    def test_path_collision_with_core_route_fails_fast(self, dev_env: None) -> None:
        del dev_env
        with pytest.raises(ValueError, match="collides with a core route"):
            _build_dev_app(live_stream=LiveStreamConfig(path="/audit"))

    def test_core_routes_survive_when_live_enabled(self, dev_env: None) -> None:
        del dev_env
        app = _build_dev_app(live_stream=LiveStreamConfig())
        paths = {getattr(r, "path", None) for r in app.routes}
        for core in ("/audit", "/kpi", "/hil-queue", "/healthz", "/live/stream"):
            assert core in paths, f"missing route {core}"


class TestLiveRouteReadOnly:
    """The SSE route MUST NOT expose a mutating verb."""

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_mutating_verbs_return_405(self, dev_env: None, method: str) -> None:
        del dev_env
        # NullEmitter keeps no background task alive; we only need HTTP verb
        # rejection behaviour here.
        app = _build_dev_app(
            live_stream=LiveStreamConfig(emitter_factory=lambda sink, channel: _NullEmitter())
        )
        with TestClient(app) as client:
            response = client.request(method, "/live/stream")
        assert response.status_code == 405


class TestLiveRouteAuth:
    def test_prod_mode_without_auth_returns_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_DEV_MODE_ENV, raising=False)
        resolver = RoleResolver(group_mapping=_mapping())
        authenticator = build_authenticator(
            verifier=UnsafeClaimsExtractor(),
            resolver=resolver,
        )
        app = build_app(
            authenticator=authenticator,
            read_model=InMemoryConsoleReadModel(),
            config=OperatorApiConfig(
                dev_mode=False,
                live_stream=LiveStreamConfig(emitter_factory=lambda sink, channel: _NullEmitter()),
            ),
        )
        with TestClient(app) as client:
            response = client.get("/live/stream")
        assert response.status_code == 401


class TestExternalSinkPath:
    """When a fork passes its own sink, the synthetic emitter MUST NOT be
    started (real publishers own the channel)."""

    def test_external_sink_disables_default_synthetic_emitter(self, dev_env: None) -> None:
        del dev_env
        external_sink = InMemorySseSink()
        app = _build_dev_app(live_stream=LiveStreamConfig(sink=external_sink))
        # Bring up the app so lifespan runs.
        with TestClient(app):
            # No synthetic emitter is started, so nothing is on the channel.
            assert external_sink.subscriber_count("aw.pipeline.stages") == 0


class _RecordingBroadcaster:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def run(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class TestProductionBroadcasterPath:
    def test_broadcaster_runs_and_stops_with_app_lifespan(self, dev_env: None) -> None:
        del dev_env
        broadcaster = _RecordingBroadcaster()
        app = _build_dev_app(
            live_stream=LiveStreamConfig(
                broadcaster_factory=lambda publisher: broadcaster,
            )
        )

        with TestClient(app):
            assert broadcaster.started is True
            assert broadcaster.stopped is False

        assert broadcaster.stopped is True
