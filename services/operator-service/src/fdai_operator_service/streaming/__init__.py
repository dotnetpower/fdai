"""Read-only Operator streaming adapters and HTTP surfaces."""

from .agent_frames import AgentActivityProjector
from .live_stream import LiveStreamEvent, LiveStreamHub, make_live_stream_route
from .stage_frames import parse_stage_frame

__all__ = [
    "AgentActivityProjector",
    "LiveStreamEvent",
    "LiveStreamHub",
    "make_live_stream_route",
    "parse_stage_frame",
]
