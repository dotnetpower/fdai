"""Relay production stage events from the event bus to the Live SSE sink."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable

from fdai.delivery.read_api.streaming.agent_activity_broadcaster import (
    DEFAULT_STAGE_TOPIC,
    parse_stage_event,
)
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.stage_publisher import StagePublisher

_LOGGER = logging.getLogger(__name__)

DEFAULT_GROUP_ID = "fdai-live-stage"
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0


class LiveStageBroadcaster:
    """Consume validated stage frames and publish their raw SSE representation."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        publisher: StagePublisher,
        stage_topic: str = DEFAULT_STAGE_TOPIC,
        group_id: str = DEFAULT_GROUP_ID,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not stage_topic:
            raise ValueError("stage_topic MUST be non-empty")
        if not group_id:
            raise ValueError("group_id MUST be non-empty")
        if not math.isfinite(retry_backoff_seconds) or retry_backoff_seconds <= 0:
            raise ValueError("retry_backoff_seconds MUST be finite and positive")
        self._event_bus = event_bus
        self._publisher = publisher
        self._stage_topic = stage_topic
        self._group_id = group_id
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self._started = False
        self._stopped = False

    async def run(self) -> None:
        """Start the background relay task."""
        if self._stopped:
            raise RuntimeError("broadcaster already stopped; instantiate a new one")
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(
            self._relay(),
            name=f"live-stage-relay:{self._stage_topic}",
        )

    async def stop(self) -> None:
        """Cancel the relay and await cleanup."""
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
                async for envelope in self._event_bus.subscribe(
                    self._stage_topic,
                    self._group_id,
                ):
                    event = parse_stage_event(envelope.payload)
                    if event is None:
                        _LOGGER.debug("live_stage_broadcaster_dropped_malformed_frame")
                        continue
                    await self._publisher.emit(event)
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - transient bus errors must recover
                _LOGGER.warning(
                    "live_stage_broadcaster_error_retrying",
                    extra={"topic": self._stage_topic},
                    exc_info=True,
                )
                await self._sleeper(self._retry_backoff_seconds)


__all__ = ["LiveStageBroadcaster"]
