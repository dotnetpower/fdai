"""Bounded handler-observer support for the event-bus bridge."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol

_LOG = logging.getLogger("fdai.agents._framework.bus_bridge")


class AgentHandlerPhase(StrEnum):
    """Lifecycle phase for one observed agent message delivery."""

    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentHandlerObserver(Protocol):
    """Best-effort observer for actual Pantheon handler execution."""

    async def observe(
        self,
        *,
        agent: str,
        topic: str,
        phase: AgentHandlerPhase,
        payload: Mapping[str, object],
        error_type: str | None = None,
    ) -> None: ...


async def notify_handler_observer(
    bridge: Any,
    *,
    agent: str,
    topic: str,
    phase: AgentHandlerPhase,
    payload: Mapping[str, object],
    error_type: str | None = None,
) -> None:
    observer = bridge.handler_observer
    if observer is None or agent not in bridge.registry.names():
        return
    failure_key = (agent, topic, phase)
    try:
        observation = observer.observe(
            agent=agent,
            topic=topic,
            phase=phase,
            payload=payload,
            error_type=error_type,
        )
        if bridge.handler_observer_timeout is None:
            await observation
        else:
            await asyncio.wait_for(observation, bridge.handler_observer_timeout)
        failure_count = bridge._handler_observer_failures.pop(failure_key, 0)
        if failure_count:
            _LOG.info(
                "pantheon_handler_observer_recovered",
                extra={
                    "agent": agent,
                    "topic": topic,
                    "phase": phase.value,
                    "failure_count": failure_count,
                },
            )
    except asyncio.CancelledError:
        raise
    except TimeoutError as exc:
        bridge._handler_observer_failures[failure_key] = (
            bridge._handler_observer_failures.get(failure_key, 0) + 1
        )
        _LOG.warning(
            "pantheon_handler_observer_timeout",
            extra={
                "agent": agent,
                "topic": topic,
                "phase": phase.value,
                "error_type": type(exc).__name__,
            },
        )
    except Exception as exc:  # noqa: BLE001 - observation must not break delivery
        bridge._handler_observer_failures[failure_key] = (
            bridge._handler_observer_failures.get(failure_key, 0) + 1
        )
        _LOG.warning(
            "pantheon_handler_observer_failed",
            extra={
                "agent": agent,
                "topic": topic,
                "phase": phase.value,
                "error_type": type(exc).__name__,
            },
        )


__all__ = ["AgentHandlerObserver", "AgentHandlerPhase", "notify_handler_observer"]
