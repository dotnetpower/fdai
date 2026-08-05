"""Agent-activity SSE surface - the ``agent.*`` / ``incident.*`` read-only stream.

This is the fifth read-only surface on the console API (after audit, KPI,
HIL queue, the live cockpit, and provisioning). Where the live cockpit
(:mod:`fdai.delivery.operator_api.streaming.live_stream`) is **action-centric**
(one tile per control-plane action flowing through the pipeline), this
surface is **agent-centric**: it streams what each pantheon agent is doing
right now, the incident tickets they open while collaborating, and the
agent-to-agent conversation turns they exchange on the conversational port.

It powers the ``Now > Agents`` console panel - a constellation of the 15
agents with live status, that lights up the involved agents when an
incident (e.g. a chaos experiment) fires and renders the collaboration
(detect -> ticket -> RCA -> resolve) as it happens.

Contract
--------

- **Read-only.** ``GET`` only; no mutating verb. The console renders agent
  activity, it never executes (``app-shape.instructions.md`` - the console
  is a read surface, the executor holds the only privileged identity).
- **Same auth gate + fan-out plumbing.** Reuses
  :func:`~fdai.delivery.operator_api.streaming.live_stream.make_live_stream_route`
  (identical keepalive / disconnect / backpressure handling); only the
  channel and path differ.
- **Opt-in.** :func:`~fdai.delivery.operator_api.main.build_app` registers this
  route only when an :class:`AgentActivityStreamConfig` is supplied. Upstream
  default is *off*.

Wire format
-----------

Every frame is one :class:`~fdai.shared.providers.sse.SseEvent` with the SSE
``event`` name ``"message"`` (so a bare ``EventSource.onmessage`` receives
it) and a JSON ``data`` payload whose ``type`` field carries the semantic
kind - ``agent.state`` / ``incident.ticket`` / ``conversation.turn``. The
console demultiplexes on ``payload.type``.

Producers
---------

- **Dev / demo path.**
  :class:`~fdai.delivery.operator_api.streaming.agent_activity_emitter.SyntheticAgentActivityEmitter`
  publishes an idle/watching heartbeat plus a periodic incident narrative,
  so the local console shows the collaboration alive without the real
  pantheon driving the hot path.
- **Real path.**
  :class:`~fdai.delivery.operator_api.streaming.agent_activity_relay.ControlLoopAgentActivityRelay`
  tees a real *in-process* :class:`~fdai.core.control_loop.ControlLoop`'s stage
  frames onto this same channel (via the deterministic
  :mod:`fdai.delivery.operator_api.streaming.agent_activity_projection`), so the
  panel reflects the actual pipeline. The dev harness opts in with
  ``FDAI_AGENTS_REAL_RELAY=1``. Across replicas, where the Operator API pod does
  not run the pipeline,
  :class:`~fdai.delivery.operator_api.streaming.agent_activity_broadcaster.AgentActivityBroadcaster`
  consumes the ``aw.pipeline.stages`` Kafka topic and drives the same channel
  through the same projection. Both paths use the identical wire contract here.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from starlette.requests import Request
from starlette.routing import Route

from fdai.delivery.agent_activity import (
    AgentState,
    AgentStateEvent,
    runtime_agent_state_snapshot,
)
from fdai.delivery.operator_api.streaming.live_stream import make_live_stream_route
from fdai.shared.providers.sse import SseEvent, SseSink
from fdai.shared.providers.stage_publisher import ObservationSource

# The channel agent-activity publishers fan out on. A relay / emitter MUST
# publish onto this same channel for its events to reach the console.
DEFAULT_CHANNEL = "fdai.agents.events"
DEFAULT_ROUTE_PATH = "/agents/stream"

# SSE `event:` name. Kept as the default ("message") so a bare
# `EventSource.onmessage` receives every frame; the semantic kind is carried
# inside the JSON payload's `type` field.
_SSE_EVENT_NAME = "message"


class TicketStatus(StrEnum):
    """Lifecycle of an incident ticket the agents collaborate on."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class TurnKind(StrEnum):
    """The role of one agent-to-agent conversational-port turn."""

    QUESTION = "question"
    ANSWER = "answer"
    HANDOFF = "handoff"


def _sse(payload: dict[str, Any]) -> SseEvent:
    """Encode a semantic payload as one SSE frame (event name ``message``)."""

    return SseEvent(id=None, event=_SSE_EVENT_NAME, data=json.dumps(payload))


@dataclass(frozen=True, slots=True)
class IncidentTicketEvent:
    """An incident ticket the agents open / advance. Wire ``type = "incident.ticket"``."""

    ticket_id: str
    correlation_id: str
    status: TicketStatus
    title: str
    severity: str
    involved_agents: Sequence[str]
    ts: str
    rca: str | None = None
    source: ObservationSource = ObservationSource.UNKNOWN

    def to_sse_event(self) -> SseEvent:
        return _sse(
            {
                "type": "incident.ticket",
                "ticket_id": self.ticket_id,
                "correlation_id": self.correlation_id,
                "status": self.status.value,
                "title": self.title,
                "severity": self.severity,
                "involved_agents": list(self.involved_agents),
                "rca": self.rca,
                "ts": self.ts,
                "source": self.source.value,
            }
        )


@dataclass(frozen=True, slots=True)
class ConversationTurnEvent:
    """One agent-to-agent conversational-port turn. Wire ``type = "conversation.turn"``."""

    correlation_id: str
    from_agent: str
    to_agent: str
    kind: TurnKind
    text: str
    ts: str
    source: ObservationSource = ObservationSource.UNKNOWN

    def to_sse_event(self) -> SseEvent:
        return _sse(
            {
                "type": "conversation.turn",
                "correlation_id": self.correlation_id,
                "from_agent": self.from_agent,
                "to_agent": self.to_agent,
                "kind": self.kind.value,
                "text": self.text,
                "ts": self.ts,
                "source": self.source.value,
            }
        )


#: An agent-activity event is any of the three semantic kinds.
AgentActivityEvent = AgentStateEvent | IncidentTicketEvent | ConversationTurnEvent


@runtime_checkable
class AgentActivityPublisher(Protocol):
    """Publish one agent-activity event to every stream subscriber."""

    async def publish(self, event: AgentActivityEvent) -> None: ...


@runtime_checkable
class AgentActivityProducer(Protocol):
    """A background producer that drives the agent-activity channel.

    Both the synthetic emitter and the production
    :class:`~fdai.delivery.operator_api.streaming.agent_activity_broadcaster.AgentActivityBroadcaster`
    satisfy this run/stop lifecycle so :func:`~fdai.delivery.operator_api.main.build_app`
    starts and stops either one uniformly in the app lifespan.
    """

    async def run(self) -> None: ...

    async def stop(self) -> None: ...


class SseAgentActivityPublisher:
    """Fan an agent-activity event out over an :class:`SseSink` channel."""

    def __init__(self, *, sink: SseSink, channel: str = DEFAULT_CHANNEL) -> None:
        self._sink = sink
        self._channel = channel

    async def publish(self, event: AgentActivityEvent) -> None:
        await self._sink.publish(self._channel, event.to_sse_event())


@dataclass(frozen=True, slots=True)
class AgentActivityStreamConfig:
    """Composition-root configuration for the agent-activity SSE surface.

    Mirrors :class:`~fdai.delivery.operator_api.streaming.live_stream.LiveStreamConfig`:
    a fork typically leaves ``sink`` / ``emitter_factory`` unset, so the
    Operator API creates an in-memory sink and starts the synthetic emitter for
    the local dev harness. Production sets ``sink`` to the shared sink the
    real pantheon relay writes to and leaves ``emitter_factory`` unset.

    ``broadcaster_factory`` is the production seam: given the sink's
    :class:`AgentActivityPublisher`, it returns an :class:`AgentActivityProducer`
    (typically an
    :class:`~fdai.delivery.operator_api.streaming.agent_activity_broadcaster.AgentActivityBroadcaster`
    consuming the ``aw.pipeline.stages`` Kafka topic). When set, ``build_app``
    starts it in the app lifespan and does NOT stack a synthetic emitter - the
    real pipeline drives the panel.
    """

    path: str = DEFAULT_ROUTE_PATH
    channel: str = DEFAULT_CHANNEL
    keepalive_seconds: float = 15.0
    sink: SseSink | None = None
    emitter_factory: Callable[[SseSink], Any] | None = None
    broadcaster_factory: Callable[[AgentActivityPublisher], AgentActivityProducer] | None = None
    snapshot_factory: Callable[[], Sequence[AgentActivityEvent]] | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("AgentActivityStreamConfig.path MUST start with '/'")
        if not self.channel:
            raise ValueError("AgentActivityStreamConfig.channel MUST be non-empty")
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds MUST be positive")
        if self.emitter_factory is not None and self.broadcaster_factory is not None:
            raise ValueError(
                "AgentActivityStreamConfig: set at most one of emitter_factory "
                "(synthetic) or broadcaster_factory (production) - not both"
            )


def make_agent_activity_stream_route(
    *,
    sink: SseSink,
    channel: str,
    path: str,
    keepalive_seconds: float,
    authorize: Callable[[Request], Awaitable[str]],
    snapshot_factory: Callable[[], Sequence[AgentActivityEvent]] | None = None,
) -> Route:
    """Return the ``GET`` agent-activity SSE Route.

    Delegates to the generic live-stream plumbing - fan-out, keepalive, and
    disconnect handling are identical; only the channel and path differ.
    ``authorize`` is the same coroutine the snapshot routes use.
    """

    return make_live_stream_route(
        sink=sink,
        channel=channel,
        path=path,
        keepalive_seconds=keepalive_seconds,
        authorize=authorize,
        initial_events=(
            (lambda: (event.to_sse_event() for event in snapshot_factory()))
            if snapshot_factory is not None
            else None
        ),
    )


__all__ = [
    "DEFAULT_CHANNEL",
    "DEFAULT_ROUTE_PATH",
    "AgentActivityEvent",
    "AgentActivityPublisher",
    "AgentActivityStreamConfig",
    "AgentState",
    "AgentStateEvent",
    "ConversationTurnEvent",
    "IncidentTicketEvent",
    "SseAgentActivityPublisher",
    "TicketStatus",
    "TurnKind",
    "make_agent_activity_stream_route",
    "runtime_agent_state_snapshot",
]
