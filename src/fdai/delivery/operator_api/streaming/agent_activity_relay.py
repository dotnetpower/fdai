"""Real-path relay: tee control-loop stage frames onto the agent-activity channel.

Wraps a :class:`~fdai.shared.providers.stage_publisher.StagePublisher` so every
:class:`~fdai.shared.providers.stage_publisher.StageEvent` a real
:class:`~fdai.core.control_loop.ControlLoop` emits is (1) forwarded to the inner
publisher unchanged (the live cockpit still works) and (2) folded through
:func:`~fdai.delivery.operator_api.streaming.agent_activity_projection.project_stage`
and fanned out onto the ``Now > Agents`` channel as ``agent.state`` /
``incident.ticket`` frames.

This is the production-shaped counterpart of the dev
:class:`~fdai.delivery.operator_api.streaming.agent_activity_emitter.SyntheticAgentActivityEmitter`:
the panel is driven by the actual pipeline, not a canned narrative. It lives in
the delivery layer and touches no ``agents/**`` code.

Safety
------

- **Never breaks the pipeline.** The :class:`StagePublisher` contract says a
  publisher MUST NOT raise on a slow / disconnected downstream. A failure to tee
  to the inner publisher or to fan out an agent-activity frame is logged and
  swallowed - the stage that emitted still completes its work.
- **Bounded state.** The projection is capped at ``max_incidents`` (oldest
  first-seen incidents evicted) so a long-running loop cannot grow it without
  limit.
- **Serialized.** Projection updates are guarded by a lock so concurrent emits
  fold in a well-defined order.
"""

from __future__ import annotations

import asyncio
import logging

from fdai.delivery.operator_api.streaming.agent_activity_projection import (
    AgentActivityProjection,
    bound_projection,
    project_stage,
)
from fdai.delivery.operator_api.streaming.agent_activity_stream import (
    AgentActivityPublisher,
)
from fdai.shared.providers.stage_publisher import StageEvent, StagePublisher

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_INCIDENTS = 256


class ControlLoopAgentActivityRelay:
    """A :class:`StagePublisher` that also drives the agent-activity channel.

    ``inner`` (optional) receives every stage frame unchanged - pass the live
    cockpit's stage publisher to keep it working. ``publisher`` is the
    agent-activity fan-out the projected ``agent.state`` / ``incident.ticket``
    frames are published to.
    """

    def __init__(
        self,
        *,
        publisher: AgentActivityPublisher,
        inner: StagePublisher | None = None,
        max_incidents: int = DEFAULT_MAX_INCIDENTS,
    ) -> None:
        if max_incidents <= 0:
            raise ValueError("max_incidents MUST be positive")
        self._publisher = publisher
        self._inner = inner
        self._max_incidents = max_incidents
        self._projection = AgentActivityProjection()
        self._lock = asyncio.Lock()

    async def emit(self, event: StageEvent) -> None:
        # 1. Tee to the inner publisher (live cockpit) first, best-effort - a
        #    downstream failure there must not stop the agent-activity relay or
        #    the pipeline.
        if self._inner is not None:
            try:
                await self._inner.emit(event)
            except Exception:  # noqa: BLE001 - StagePublisher MUST NOT raise upstream
                _LOGGER.warning(
                    "agent_activity_relay_inner_emit_failed",
                    extra={"stage": event.stage.value, "correlation_id": event.correlation_id},
                    exc_info=True,
                )

        # 2. Fold through the projection under the lock, then publish outside it
        #    so a slow sink does not serialize projection updates.
        async with self._lock:
            result = project_stage(self._projection, event)
            self._projection = bound_projection(result.projection, self._max_incidents)
            activity_events = list(result.events)

        for activity_event in activity_events:
            try:
                await self._publisher.publish(activity_event)
            except Exception:  # noqa: BLE001 - fan-out is best-effort, never fatal
                _LOGGER.warning(
                    "agent_activity_relay_publish_failed",
                    extra={"correlation_id": event.correlation_id},
                    exc_info=True,
                )


__all__ = ["ControlLoopAgentActivityRelay", "DEFAULT_MAX_INCIDENTS"]
