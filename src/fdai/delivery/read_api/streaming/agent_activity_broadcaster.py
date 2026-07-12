"""Production-path relay: a Kafka stage topic drives the agent-activity channel.

In production the read-API pod does not run the pipeline; the real
:class:`~fdai.core.control_loop.ControlLoop` publishes stage frames onto the
``aw.pipeline.stages`` Kafka topic via
:class:`~fdai.shared.streaming.stage_publisher.EventBusStagePublisher`, and
:class:`~fdai.shared.streaming.broadcaster.SseBroadcaster` fans them out to the
live cockpit. This module is the agent-centric counterpart: it consumes the
same topic, reconstructs each :class:`StageEvent` from its wire form, folds it
through :func:`~fdai.delivery.read_api.streaming.agent_activity_projection.project_stage`,
and publishes the resulting ``agent.state`` / ``incident.ticket`` /
``conversation.turn`` frames onto the ``Now > Agents`` channel.

Where :class:`~fdai.delivery.read_api.streaming.agent_activity_relay.ControlLoopAgentActivityRelay`
tees an in-process ControlLoop (the dev harness), this broadcaster is the
cross-replica path: it needs only the shared event bus and the agent-activity
publisher, so the composition root binds it to the real Kafka bus + SSE sink.

Safety
------

- **Untrusted input.** Kafka payloads are untrusted at this boundary, so
  :func:`parse_stage_event` is fail-closed: a malformed / unparseable frame is
  dropped (never crashes the relay, never fabricates a StageEvent).
- **Resilient consume loop.** A transient bus error is logged and retried after
  a bounded backoff (mirroring :class:`SseBroadcaster`); cancellation via
  :meth:`stop` breaks the loop cleanly.
- **Bounded + serialized.** The projection is capped and folds under a lock.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from fdai.delivery.read_api.streaming.agent_activity_projection import (
    AgentActivityProjection,
    bound_projection,
    project_stage,
)
from fdai.delivery.read_api.streaming.agent_activity_stream import (
    AgentActivityPublisher,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import StageEvent, StageName, StagePhase

_LOGGER = logging.getLogger(__name__)

DEFAULT_STAGE_TOPIC = "aw.pipeline.stages"
DEFAULT_GROUP_ID = "fdai-agent-activity"
DEFAULT_MAX_INCIDENTS = 256
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0


def parse_stage_event(payload: Mapping[str, Any]) -> StageEvent | None:
    """Reconstruct a :class:`StageEvent` from its ``to_dict`` wire form.

    The inverse of :meth:`StageEvent.to_dict`. Fail-closed: any missing /
    wrong-typed field, an unknown stage/phase token, a non-ISO timestamp, or a
    payload that violates the ``error`` iff ``FAILED`` invariant returns
    ``None`` so the caller can drop it. Kafka payloads are untrusted here.
    """
    try:
        event_id = payload["event_id"]
        correlation_id = payload["correlation_id"]
        ts_raw = payload["ts"]
        if not (
            isinstance(event_id, str)
            and isinstance(correlation_id, str)
            and isinstance(ts_raw, str)
        ):
            return None
        stage = StageName(payload["stage"])
        phase = StagePhase(payload["phase"])
        ts = datetime.fromisoformat(ts_raw)
        detail = payload.get("detail", {})
        if not isinstance(detail, Mapping):
            return None
        error = payload.get("error")
        if error is not None and not isinstance(error, str):
            return None
        # StageEvent.__post_init__ enforces the FAILED-iff-error and tz-aware
        # invariants; a violation raises and we fail closed below.
        return StageEvent(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=stage,
            phase=phase,
            ts=ts,
            detail=dict(detail),
            error=error,
        )
    except (KeyError, ValueError, TypeError):
        return None


class AgentActivityBroadcaster:
    """Consume a stage EventBus topic and drive the agent-activity channel."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        publisher: AgentActivityPublisher,
        stage_topic: str = DEFAULT_STAGE_TOPIC,
        group_id: str = DEFAULT_GROUP_ID,
        max_incidents: int = DEFAULT_MAX_INCIDENTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not stage_topic:
            raise ValueError("stage_topic MUST be non-empty")
        if max_incidents <= 0:
            raise ValueError("max_incidents MUST be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds MUST be >= 0")
        self._event_bus = event_bus
        self._publisher = publisher
        self._stage_topic = stage_topic
        self._group_id = group_id
        self._max_incidents = max_incidents
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._projection = AgentActivityProjection()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._stopped = False

    async def run(self) -> None:
        """Start the background consume task. Idempotent before :meth:`stop`."""
        # `_stopped` MUST be checked before `_started` - the flags are set in
        # the order (run -> _started=True, stop -> _stopped=True) so a
        # `run() -> stop() -> run()` sequence otherwise sees `_started=True`
        # and silently returns, making the RuntimeError guard unreachable.
        if self._stopped:
            raise RuntimeError("broadcaster already stopped; instantiate a new one")
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(
            self._relay(), name=f"agent-activity-relay:{self._stage_topic}"
        )

    async def stop(self) -> None:
        """Cancel the consume task and await cleanup. Idempotent."""
        if self._stopped:
            return
        self._stopped = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _relay(self) -> None:
        while True:
            try:
                async for envelope in self._event_bus.subscribe(self._stage_topic, self._group_id):
                    await self._handle(envelope.payload)
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a transient bus error must not kill the relay
                _LOGGER.warning(
                    "agent_activity_broadcaster_error_retrying",
                    extra={"topic": self._stage_topic},
                    exc_info=True,
                )
                await self._sleeper(self._retry_backoff_seconds)

    async def _handle(self, payload: Mapping[str, Any]) -> None:
        event = parse_stage_event(payload)
        if event is None:
            # Drop an unparseable frame - fail-closed, never crash the relay.
            _LOGGER.debug("agent_activity_broadcaster_dropped_malformed_frame")
            return
        async with self._lock:
            result = project_stage(self._projection, event)
            self._projection = bound_projection(result.projection, self._max_incidents)
            activity_events = list(result.events)
        for activity_event in activity_events:
            try:
                await self._publisher.publish(activity_event)
            except Exception:  # noqa: BLE001 - fan-out is best-effort, never fatal
                _LOGGER.warning(
                    "agent_activity_broadcaster_publish_failed",
                    extra={"correlation_id": event.correlation_id},
                    exc_info=True,
                )


__all__ = [
    "DEFAULT_GROUP_ID",
    "DEFAULT_MAX_INCIDENTS",
    "DEFAULT_STAGE_TOPIC",
    "AgentActivityBroadcaster",
    "parse_stage_event",
]
