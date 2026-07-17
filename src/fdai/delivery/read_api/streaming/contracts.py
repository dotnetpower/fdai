"""Composition contracts for the live read API stream."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.stage_publisher import StagePublisher


class LiveEmitter:
    """Lifecycle shape for a live-event source."""

    async def start(self) -> None:  # pragma: no cover - protocol shape
        raise NotImplementedError

    async def stop(self) -> None:  # pragma: no cover - protocol shape
        raise NotImplementedError


class LiveStageProducer(Protocol):
    """Lifecycle shape for a production stage relay."""

    async def run(self) -> None:  # pragma: no cover - protocol shape
        raise NotImplementedError

    async def stop(self) -> None:  # pragma: no cover - protocol shape
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class LiveStreamConfig:
    """Composition-root configuration for the live SSE surface."""

    path: str = "/live/stream"
    channel: str = "aw.pipeline.stages"
    keepalive_seconds: float = 15.0
    sink: SseSink | None = None
    emitter_factory: Callable[[SseSink, str], LiveEmitter] | None = None
    broadcaster_factory: Callable[[StagePublisher], LiveStageProducer] | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError(f"LiveStreamConfig.path MUST start with '/', got {self.path!r}")
        if not self.channel:
            raise ValueError("LiveStreamConfig.channel MUST be non-empty")
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds MUST be positive")
        if self.emitter_factory is not None and self.broadcaster_factory is not None:
            raise ValueError(
                "LiveStreamConfig: set at most one of emitter_factory or broadcaster_factory"
            )


__all__ = ["LiveEmitter", "LiveStageProducer", "LiveStreamConfig"]
