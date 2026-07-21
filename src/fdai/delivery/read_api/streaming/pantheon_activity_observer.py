"""Project actual Pantheon handler execution into agent-activity frames."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.agents import AgentHandlerPhase
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityPublisher,
    AgentState,
    AgentStateEvent,
)
from fdai.delivery.read_api.streaming.sse_protocol import iso_ts_utc
from fdai.shared.providers.stage_publisher import ObservationSource

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


class PantheonActivityObserver:
    """Publish state transitions around real typed-message handlers."""

    def __init__(self, *, publisher: AgentActivityPublisher) -> None:
        self._publisher = publisher

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
        await self._publisher.publish(
            AgentStateEvent(
                agent=agent,
                state=state,
                ts=iso_ts_utc(),
                correlation_id=correlation_id,
                detail=detail,
                source=ObservationSource.RUNTIME_OBSERVED,
            )
        )


__all__ = ["PantheonActivityObserver"]
