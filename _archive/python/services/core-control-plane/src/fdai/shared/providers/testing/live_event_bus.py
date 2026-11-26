"""Compatibility name for the process-local EventBus adapter."""

from fdai.shared.providers.local.event_bus import LocalEventBus


class LiveInMemoryEventBus(LocalEventBus):
    """Backward-compatible test name for :class:`LocalEventBus`."""


__all__ = ["LiveInMemoryEventBus"]
