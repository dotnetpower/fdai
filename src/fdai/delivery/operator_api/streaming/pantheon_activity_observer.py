"""Project actual Pantheon handler execution into agent-activity frames."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.agents import AgentHandlerPhase
from fdai.delivery.agent_activity import project_agent_handler_state
from fdai.delivery.operator_api.streaming.agent_activity_stream import (
    AgentActivityPublisher,
)


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
        await self._publisher.publish(
            project_agent_handler_state(
                agent=agent,
                topic=topic,
                phase=phase,
                payload=payload,
                error_type=error_type,
            )
        )


__all__ = ["PantheonActivityObserver"]
