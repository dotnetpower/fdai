"""Real-time streaming helpers.

Everything here glues the internal Kafka event bus to the external SSE
stream. Kept out of ``core/`` because the relay is composition-level: a
fork MAY register a different broadcaster (e.g. per-tenant channel
routing) at its own composition root.
"""

from .broadcaster import SseBroadcaster
from .stage_publisher import EventBusStagePublisher, SseSinkStagePublisher

__all__ = [
    "EventBusStagePublisher",
    "SseBroadcaster",
    "SseSinkStagePublisher",
]
