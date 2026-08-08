"""Neutral agent-activity records and runtime publication services.

Responsibility: project observed Pantheon health and handler transitions into
bounded agent-state records and publish them to the configured event bus.
Authority: observations only; records cannot judge, approve, or execute.
State: one process-local stop event for the periodic publisher. Dependencies:
Pantheon handler phases, the provider-neutral event bus, and shared SSE values.
Deployment role: consumed by the headless runtime and Operator API adapters
without either process importing the other's implementation package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.sse import SseEvent
from fdai.shared.providers.stage_publisher import ObservationSource

DEFAULT_STAGE_TOPIC = "aw.pipeline.stages"
DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS = 15.0
DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS = 0.25

_LOGGER = logging.getLogger(__name__)
_MAX_DETAIL_CHARS = 512
_MAX_IDENTIFIER_CHARS = 1024
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_ACTIVE_STATE: dict[str, AgentState] = {}
_SENSING_AGENTS = frozenset({"Huginn", "Heimdall"})


class AgentHandlerPhaseValue(Protocol):
    """Structural handler-phase value accepted from a Pantheon runtime."""

    @property
    def value(self) -> str: ...


class AgentState(StrEnum):
    """One observed Pantheon agent activity state."""

    IDLE = "idle"
    WATCHING = "watching"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    EXECUTING = "executing"
    APPROVING = "approving"
    AUDITING = "auditing"


_ACTIVE_STATE.update(
    {
        "Odin": AgentState.DECIDING,
        "Thor": AgentState.EXECUTING,
        "Forseti": AgentState.DECIDING,
        "Huginn": AgentState.COLLECTING,
        "Heimdall": AgentState.ANALYZING,
        "Vidar": AgentState.EXECUTING,
        "Var": AgentState.APPROVING,
        "Bragi": AgentState.ANALYZING,
        "Saga": AgentState.AUDITING,
        "Mimir": AgentState.DECIDING,
        "Muninn": AgentState.COLLECTING,
        "Norns": AgentState.ANALYZING,
        "Njord": AgentState.ANALYZING,
        "Freyr": AgentState.ANALYZING,
        "Loki": AgentState.ANALYZING,
    }
)
_PANTHEON_NAMES = frozenset(_ACTIVE_STATE)


@dataclass(frozen=True, slots=True)
class AgentStateEvent:
    """One content-free agent-state observation."""

    agent: str
    state: AgentState
    ts: str
    correlation_id: str | None = None
    detail: str | None = None
    source: ObservationSource = ObservationSource.UNKNOWN

    def to_payload(self) -> dict[str, object]:
        """Return the stable agent-state wire payload."""
        return {
            "type": "agent.state",
            "agent": self.agent,
            "state": self.state.value,
            "ts": self.ts,
            "correlation_id": self.correlation_id,
            "detail": self.detail,
            "source": self.source.value,
        }

    def to_sse_event(self) -> SseEvent:
        """Encode the record as the existing message SSE value."""
        return SseEvent(
            id=None,
            event="message",
            data=json.dumps(self.to_payload()),
        )

    def to_runtime_payload(self) -> dict[str, object]:
        """Return the runtime-state discriminator over the same record fields."""
        payload = self.to_payload()
        payload["type"] = "agent.runtime-state"
        return payload


def runtime_agent_state_snapshot(health: Mapping[str, Any]) -> tuple[AgentStateEvent, ...]:
    """Project initialized healthy Pantheon agents into resting states."""
    if int(health.get("consumers_live") or 0) <= 0:
        return ()
    agent_health = health.get("agent_health")
    if not isinstance(agent_health, Mapping):
        return ()
    unavailable = {
        str(agent) for agent in health.get("unavailable_agents", ()) if isinstance(agent, str)
    }
    timestamp = _iso_ts_utc()
    return tuple(
        AgentStateEvent(
            agent=str(agent),
            state=(AgentState.WATCHING if agent in _SENSING_AGENTS else AgentState.IDLE),
            ts=timestamp,
            detail="Runtime agent initialized",
            source=ObservationSource.RUNTIME_OBSERVED,
        )
        for agent, snapshot in agent_health.items()
        if (
            isinstance(snapshot, Mapping)
            and snapshot.get("status") != "error"
            and agent in _PANTHEON_NAMES
            and agent not in unavailable
        )
    )


class EventBusPantheonActivityObserver:
    """Publish observed Pantheon handler transitions onto the stage topic."""

    def __init__(self, *, event_bus: EventBus, topic: str = DEFAULT_STAGE_TOPIC) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic

    async def observe(
        self,
        *,
        agent: str,
        topic: str,
        phase: AgentHandlerPhaseValue,
        payload: Mapping[str, object],
        error_type: str | None = None,
    ) -> None:
        """Publish one content-free observed handler transition."""
        event = project_agent_handler_state(
            agent=agent,
            topic=topic,
            phase=phase,
            payload=payload,
            error_type=error_type,
        )
        await self._event_bus.publish(self._topic, agent, event.to_runtime_payload())


def project_agent_handler_state(
    *,
    agent: str,
    topic: str,
    phase: AgentHandlerPhaseValue,
    payload: Mapping[str, object],
    error_type: str | None = None,
) -> AgentStateEvent:
    """Project one observed handler transition into a bounded state record."""
    if agent not in _PANTHEON_NAMES:
        raise ValueError(f"unknown Pantheon agent: {agent}")
    correlation_id = _bounded_identifier(payload.get("correlation_id"))
    bounded_topic = topic[:_MAX_DETAIL_CHARS]
    if phase.value == "started":
        state = _ACTIVE_STATE.get(agent, AgentState.ANALYZING)
        detail = f"Processing {bounded_topic}"
    else:
        state = AgentState.WATCHING if agent in _SENSING_AGENTS else AgentState.IDLE
        detail = (
            f"Failed {bounded_topic} ({(error_type or 'handler error')[:128]})"
            if phase.value == "failed"
            else f"Processed {bounded_topic}"
        )
        correlation_id = None
    return AgentStateEvent(
        agent=agent,
        state=state,
        ts=_event_timestamp(payload),
        correlation_id=correlation_id,
        detail=detail[:_MAX_DETAIL_CHARS],
        source=ObservationSource.RUNTIME_OBSERVED,
    )


def _bounded_identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_CHARS:
        return None
    return value


def _event_timestamp(payload: Mapping[str, object]) -> str:
    value = payload.get("ts")
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None and parsed <= datetime.now(UTC) + _MAX_FUTURE_SKEW:
                return value
    return _iso_ts_utc()


def _iso_ts_utc() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class AgentRuntimeStatePublisher:
    """Periodically publish live Pantheon health onto the shared stage topic."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        snapshot_factory: Callable[[], Sequence[AgentStateEvent]],
        topic: str = DEFAULT_STAGE_TOPIC,
        interval_seconds: float = DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS,
    ) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("interval_seconds MUST be finite and positive")
        self._event_bus = event_bus
        self._snapshot_factory = snapshot_factory
        self._topic = topic
        self._interval_seconds = interval_seconds
        self._stopped = asyncio.Event()

    async def publish_once(self) -> int:
        """Publish one current health snapshot and return its agent count."""
        events = tuple(self._snapshot_factory())
        for event in events:
            await self._event_bus.publish(
                self._topic,
                event.agent,
                event.to_runtime_payload(),
            )
        return len(events)

    async def run(self) -> None:
        """Publish immediately and refresh until stopped."""
        while not self._stopped.is_set():
            published = 0
            try:
                published = await self.publish_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - observation must not stop Pantheon
                _LOGGER.warning(
                    "agent_runtime_state_publish_failed",
                    extra={"topic": self._topic},
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=(
                        self._interval_seconds
                        if published > 0
                        else min(
                            self._interval_seconds,
                            DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS,
                        )
                    ),
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        """Stop publication without stopping the shared bus."""
        self._stopped.set()


__all__ = [
    "DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS",
    "DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS",
    "DEFAULT_STAGE_TOPIC",
    "AgentRuntimeStatePublisher",
    "AgentState",
    "AgentStateEvent",
    "EventBusPantheonActivityObserver",
    "project_agent_handler_state",
    "runtime_agent_state_snapshot",
]
