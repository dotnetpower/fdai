"""SSE route registration and producer lifecycle wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

from starlette.requests import Request
from starlette.routing import BaseRoute

from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.streaming.agent_activity_emitter import (
    SyntheticAgentActivityEmitter,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityProducer,
    SseAgentActivityPublisher,
    make_agent_activity_stream_route,
)
from fdai.delivery.read_api.streaming.live_stream import (
    LiveEmitter,
    LiveStageProducer,
    SyntheticLiveEmitter,
    make_live_stream_route,
)
from fdai.delivery.read_api.streaming.provision_stream import make_provision_stream_route
from fdai.shared.providers.testing.sse import InMemorySseSink
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher


@dataclass(frozen=True, slots=True)
class StreamLifecycles:
    live_emitter: LiveEmitter | None = None
    live_broadcaster: LiveStageProducer | None = None
    agent_emitter: SyntheticAgentActivityEmitter | None = None
    agent_broadcaster: AgentActivityProducer | None = None


def append_stream_routes(
    routes: list[BaseRoute],
    *,
    config: ReadApiConfig,
    authorize: Callable[[Request], Awaitable[str]],
    core_paths: Collection[str],
    panel_paths: Collection[str],
) -> StreamLifecycles:
    """Append configured SSE routes in live, provision, agent order."""
    live_emitter: LiveEmitter | None = None
    live_broadcaster: LiveStageProducer | None = None
    if config.live_stream is not None:
        live_cfg = config.live_stream
        _ensure_available(live_cfg.path, "live_stream.path", core_paths, panel_paths)
        live_sink = live_cfg.sink if live_cfg.sink is not None else InMemorySseSink()
        if live_cfg.broadcaster_factory is not None:
            live_broadcaster = live_cfg.broadcaster_factory(
                SseSinkStagePublisher(live_sink, channel=live_cfg.channel)
            )
        elif live_cfg.emitter_factory is not None:
            live_emitter = live_cfg.emitter_factory(live_sink, live_cfg.channel)
        elif live_cfg.sink is None:
            live_emitter = SyntheticLiveEmitter(sink=live_sink, channel=live_cfg.channel)
        routes.append(
            make_live_stream_route(
                sink=live_sink,
                channel=live_cfg.channel,
                path=live_cfg.path,
                keepalive_seconds=live_cfg.keepalive_seconds,
                authorize=authorize,
            )
        )

    if config.provision_stream is not None:
        provision_cfg = config.provision_stream
        _ensure_available(provision_cfg.path, "provision_stream.path", core_paths, panel_paths)
        if config.live_stream is not None and provision_cfg.path == config.live_stream.path:
            raise ValueError(
                f"provision_stream.path {provision_cfg.path!r} collides with the live-stream route"
            )
        provision_sink = provision_cfg.sink if provision_cfg.sink is not None else InMemorySseSink()
        routes.append(
            make_provision_stream_route(
                sink=provision_sink,
                channel=provision_cfg.channel,
                path=provision_cfg.path,
                keepalive_seconds=provision_cfg.keepalive_seconds,
                authorize=authorize,
            )
        )

    agent_emitter: SyntheticAgentActivityEmitter | None = None
    agent_broadcaster: AgentActivityProducer | None = None
    if config.agent_activity is not None:
        agent_cfg = config.agent_activity
        _ensure_available(agent_cfg.path, "agent_activity.path", core_paths, panel_paths)
        for other in (config.live_stream, config.provision_stream):
            if other is not None and agent_cfg.path == other.path:
                raise ValueError(
                    f"agent_activity.path {agent_cfg.path!r} collides with another SSE route"
                )
        agent_sink = agent_cfg.sink if agent_cfg.sink is not None else InMemorySseSink()
        if agent_cfg.broadcaster_factory is not None:
            agent_broadcaster = agent_cfg.broadcaster_factory(
                SseAgentActivityPublisher(sink=agent_sink, channel=agent_cfg.channel)
            )
        elif agent_cfg.emitter_factory is not None:
            agent_emitter = agent_cfg.emitter_factory(agent_sink)
        elif agent_cfg.sink is None:
            agent_emitter = SyntheticAgentActivityEmitter(
                sink=agent_sink, channel=agent_cfg.channel
            )
        routes.append(
            make_agent_activity_stream_route(
                sink=agent_sink,
                channel=agent_cfg.channel,
                path=agent_cfg.path,
                keepalive_seconds=agent_cfg.keepalive_seconds,
                authorize=authorize,
                snapshot_factory=agent_cfg.snapshot_factory,
            )
        )

    return StreamLifecycles(
        live_emitter=live_emitter,
        live_broadcaster=live_broadcaster,
        agent_emitter=agent_emitter,
        agent_broadcaster=agent_broadcaster,
    )


def _ensure_available(
    path: str,
    field: str,
    core_paths: Collection[str],
    panel_paths: Collection[str],
) -> None:
    if path in core_paths:
        raise ValueError(f"{field} {path!r} collides with a core route")
    if path in panel_paths:
        raise ValueError(f"{field} {path!r} collides with a panel path")


__all__ = ["StreamLifecycles", "append_stream_routes"]
