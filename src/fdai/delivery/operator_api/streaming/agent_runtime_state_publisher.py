"""Publish observed Pantheon health and handler activity across processes."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Mapping, Sequence

from fdai.agents import AgentHandlerPhase
from fdai.delivery.operator_api.streaming.agent_activity_stream import (
    AgentState,
    AgentStateEvent,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import ObservationSource

DEFAULT_RUNTIME_STATE_TOPIC = "aw.pipeline.stages"
DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS = 15.0
DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS = 0.25

_LOGGER = logging.getLogger(__name__)

_ACTIVE_STATE: dict[str, AgentState] = {
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
_SENSING_AGENTS = frozenset({"Huginn", "Heimdall"})


class EventBusPantheonActivityObserver:
    """Publish actual Pantheon handler transitions onto the shared stage topic."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        topic: str = DEFAULT_RUNTIME_STATE_TOPIC,
    ) -> None:
        if not topic:
            raise ValueError("topic MUST be non-empty")
        self._event_bus = event_bus
        self._topic = topic

    async def observe(
        self,
        *,
        agent: str,
        topic: str,
        phase: AgentHandlerPhase,
        payload: Mapping[str, object],
        error_type: str | None = None,
    ) -> None:
        correlation_id = str(payload.get("correlation_id") or "") or None
        if phase is AgentHandlerPhase.STARTED:
            state = _ACTIVE_STATE.get(agent, AgentState.ANALYZING)
            detail = f"Processing {topic}"
        else:
            state = AgentState.WATCHING if agent in _SENSING_AGENTS else AgentState.IDLE
            detail = (
                f"Failed {topic} ({error_type or 'handler error'})"
                if phase is AgentHandlerPhase.FAILED
                else f"Processed {topic}"
            )
            correlation_id = None
        event = AgentStateEvent(
            agent=agent,
            state=state,
            ts=_event_timestamp(payload),
            correlation_id=correlation_id,
            detail=detail,
            source=ObservationSource.RUNTIME_OBSERVED,
        )
        event_payload = event.to_payload()
        event_payload["type"] = "agent.runtime-state"
        await self._event_bus.publish(self._topic, agent, event_payload)


def _event_timestamp(payload: Mapping[str, object]) -> str:
    value = payload.get("ts")
    return value if isinstance(value, str) and value else _iso_ts_utc()


def _iso_ts_utc() -> str:
    from fdai.delivery.operator_api.streaming.sse_protocol import iso_ts_utc

    return iso_ts_utc()


class AgentRuntimeStatePublisher:
    """Project live Pantheon health onto the shared object bus."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        snapshot_factory: Callable[[], Sequence[AgentStateEvent]],
        topic: str = DEFAULT_RUNTIME_STATE_TOPIC,
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
            payload = event.to_payload()
            payload["type"] = "agent.runtime-state"
            await self._event_bus.publish(self._topic, event.agent, payload)
        return len(events)

    async def run(self) -> None:
        """Publish immediately and then refresh until stopped."""
        while not self._stopped.is_set():
            published = 0
            try:
                published = await self.publish_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - telemetry failure must not stop the Pantheon
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
        """Stop the periodic publisher without stopping the shared bus."""
        self._stopped.set()


__all__ = [
    "DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS",
    "DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS",
    "DEFAULT_RUNTIME_STATE_TOPIC",
    "AgentRuntimeStatePublisher",
    "EventBusPantheonActivityObserver",
]
