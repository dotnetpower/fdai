"""Trusted synthetic canary path for end-to-end control-loop health."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.shared.contracts.models import Event
from fdai.shared.providers.stage_publisher import StageName, StagePhase

CANARY_EVENT_TYPE = "fdai.control.canary"
CANARY_SOURCE = "fdai.canary-job"


async def process_canary(
    host: Any,
    raw_event: Event | Mapping[str, Any],
) -> ControlLoopResult:
    """Ingest and audit one event received from the trusted canary topic."""
    event = host._event_ingest.ingest(raw_event)
    if event is None:
        return ControlLoopResult(
            outcome=ControlLoopOutcome.DEDUPED,
            tier="canary",
            decision="dedupe",
            resource_type=None,
            reason="duplicate_canary_idempotency_key",
        )
    if event.event_type != CANARY_EVENT_TYPE or event.source != CANARY_SOURCE:
        raise ValueError("canary topic accepts only the canonical canary source and event type")

    event_id = str(event.event_id)
    correlation_id = event.correlation_id or event_id
    host._correlate_incident_id(event)
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.INGEST,
        phase=StagePhase.DONE,
        detail={"event_type": event.event_type, "mode": event.mode.value},
    )
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.ROUTE,
        phase=StagePhase.DONE,
        detail={"routed_to": "canary-no-op", "resource_type": None},
    )
    recorded_at = datetime.now(tz=UTC)
    latency_ms = max(0, int((recorded_at - event.detected_at).total_seconds() * 1000))
    await host._audit_store.append_audit_entry(
        {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "actor": CANARY_SOURCE,
            "action_kind": "control_loop.canary",
            "mode": event.mode.value,
            "tier": "canary",
            "decision": "no-op",
            "outcome": "success",
            "idempotency_key": event.idempotency_key,
            "latency_ms": latency_ms,
            "recorded_at": recorded_at.isoformat(),
        }
    )
    await host._emit_stage(
        event_id=event_id,
        correlation_id=correlation_id,
        stage=StageName.AUDIT,
        phase=StagePhase.DONE,
        detail={"outcome": ControlLoopOutcome.CANARY_RECORDED.value},
    )
    return ControlLoopResult(
        outcome=ControlLoopOutcome.CANARY_RECORDED,
        tier="canary",
        decision="no-op",
        resource_type=None,
        reason="trusted_canary_recorded",
        event_id=event_id,
    )


__all__ = ["CANARY_EVENT_TYPE", "CANARY_SOURCE", "process_canary"]
