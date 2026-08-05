"""Compatibility facade for neutral agent runtime-state publication.

The headless runtime imports :mod:`fdai.delivery.agent_activity`. This module
preserves the Operator API import path for existing adapters and tests without
owning runtime records or publication behavior.
"""

from fdai.delivery.agent_activity import (
    DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS,
    DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS,
    DEFAULT_STAGE_TOPIC,
    AgentRuntimeStatePublisher,
    EventBusPantheonActivityObserver,
)

DEFAULT_RUNTIME_STATE_TOPIC = DEFAULT_STAGE_TOPIC

__all__ = [
    "DEFAULT_RUNTIME_STATE_INTERVAL_SECONDS",
    "DEFAULT_RUNTIME_STATE_STARTUP_RETRY_SECONDS",
    "DEFAULT_RUNTIME_STATE_TOPIC",
    "AgentRuntimeStatePublisher",
    "EventBusPantheonActivityObserver",
]
