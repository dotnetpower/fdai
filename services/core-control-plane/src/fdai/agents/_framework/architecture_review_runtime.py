"""Runtime-only helpers for the ARB observation trace binding."""

from __future__ import annotations

from typing import Any

from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.core.architecture_review import ArchitectureReviewTraceObserver

_ARCHITECTURE_REVIEW_OBSERVER_PRINCIPAL = "architecture-review-observer"
_ARCHITECTURE_REVIEW_OBSERVER_TOPICS = (
    "object.change",
    "object.state-snapshot",
    "object.anomaly",
    "object.cost-anomaly",
    "object.capacity-forecast",
    "object.chaos-experiment",
    "object.verdict",
    "object.audit-entry",
)


def bind_architecture_review_observer(
    bridge: EventBusBridge,
    observer: ArchitectureReviewTraceObserver | None,
) -> None:
    """Subscribe the observation-only ARB trace to owned runtime topics."""

    if observer is None:
        return

    async def _observe_topic(topic: str, payload: dict[str, Any]) -> None:
        observer.observe(topic, payload)

    for topic in _ARCHITECTURE_REVIEW_OBSERVER_TOPICS:
        bridge.subscribe(topic, _ARCHITECTURE_REVIEW_OBSERVER_PRINCIPAL, _observe_topic)


def handle_architecture_review_consumer_state(
    observer: ArchitectureReviewTraceObserver | None,
    *,
    agent: str,
    topic: str,
    state: str,
) -> bool:
    """Record terminal observer degradation and report whether it was handled."""

    if agent != _ARCHITECTURE_REVIEW_OBSERVER_PRINCIPAL or observer is None:
        return False
    observer.observe_consumer_state(topic=topic, state=state)
    return True


def architecture_review_observation_snapshot(
    observer: ArchitectureReviewTraceObserver | None,
) -> dict[str, object] | None:
    """Return the retained ARB observation summary."""

    return observer.snapshot() if observer is not None else None


__all__ = [
    "architecture_review_observation_snapshot",
    "bind_architecture_review_observer",
    "handle_architecture_review_consumer_state",
]
