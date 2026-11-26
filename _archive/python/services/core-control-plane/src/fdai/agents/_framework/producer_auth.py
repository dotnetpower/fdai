"""Authenticated producer checks derived from the fixed pantheon registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fdai.agents._framework.registry import load_pantheon

_REGISTRY = load_pantheon()


class _BehaviorRecorder(Protocol):
    def record_behavior(self, name: str, amount: int = 1) -> None: ...


def topic_owner(topic: str) -> str | None:
    """Return the single writer for a pantheon topic."""

    return _REGISTRY.owner_of_topic(topic)


def producer_is_topic_owner(topic: str, payload: Mapping[str, Any]) -> bool:
    """Return whether the authenticated payload producer owns ``topic``."""

    owner = topic_owner(topic)
    return owner is not None and payload.get("producer_principal") == owner


def require_topic_owner(
    host: _BehaviorRecorder,
    topic: str,
    payload: Mapping[str, Any],
    *,
    behavior: str,
) -> bool:
    """Record and reject when a topic payload is not from its registered owner."""

    if producer_is_topic_owner(topic, payload):
        return False
    host.record_behavior(behavior)
    return True


__all__ = ["producer_is_topic_owner", "require_topic_owner", "topic_owner"]
