"""Stage-event construction and publication for the control loop."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.shared.providers.stage_publisher import (
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)


async def emit_stage(
    publisher: StagePublisher,
    *,
    event_id: str,
    correlation_id: str,
    stage: StageName,
    phase: StagePhase,
    detail: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> None:
    try:
        event = StageEvent(
            event_id=event_id,
            correlation_id=correlation_id,
            stage=stage,
            phase=phase,
            source=ObservationSource.RUNTIME_OBSERVED,
            detail=dict(detail) if detail else {},
            error=error,
        )
    except ValueError:  # pragma: no cover - defence in depth
        return
    await publisher.emit(event)
