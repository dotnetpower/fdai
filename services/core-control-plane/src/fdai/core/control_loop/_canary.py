"""Trusted synthetic canary path for end-to-end control-loop health."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fdai.core.control_loop.models import ControlLoopOutcome, ControlLoopResult
from fdai.shared.contracts.models import Event
from fdai.shared.providers.stage_publisher import StageName, StagePhase

CANARY_EVENT_TYPE = "fdai.control.canary"
CANARY_SOURCE = "fdai.canary-job"
_AUDIT_TIMEOUT_SECONDS = 5
_LOGGER = logging.getLogger(__name__)


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
    started_at = datetime.now(tz=UTC)
    attempt = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "actor": CANARY_SOURCE,
        "action_kind": "control_loop.canary.attempt",
        "mode": event.mode.value,
        "tier": "canary",
        "decision": "no-op",
        "idempotency_key": event.idempotency_key,
        "detected_at": event.detected_at.isoformat(),
        "attempt_id": str(uuid4()),
        "started_at": started_at.isoformat(),
    }
    await _append(host, {**attempt, "outcome": "started", "recorded_at": started_at.isoformat()})
    try:
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
    except asyncio.CancelledError as exc:
        await _record_interruption(host, attempt, outcome="cancelled", error=exc)
        raise
    except Exception as exc:  # noqa: BLE001 - persist failure before propagating it
        await _record_interruption(host, attempt, outcome="failure", error=exc)
        raise
    recorded_at = datetime.now(tz=UTC)
    latency_ms = max(0, int((recorded_at - event.detected_at).total_seconds() * 1000))
    # A failed or cancelled append has an uncertain commit outcome. Do not write a
    # contradictory terminal record; independent readback owns that determination.
    await _append(
        host,
        {
            **attempt,
            "action_kind": "control_loop.canary",
            "outcome": "success",
            "latency_ms": latency_ms,
            "recorded_at": recorded_at.isoformat(),
        },
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


async def _append(host: Any, entry: Mapping[str, Any]) -> None:
    async with asyncio.timeout(_AUDIT_TIMEOUT_SECONDS):
        await host._audit_store.append_audit_entry(entry)


async def _record_interruption(
    host: Any, attempt: Mapping[str, Any], *, outcome: str, error: BaseException
) -> None:
    """Keep the original failure/cancellation even when its terminal audit cannot commit."""
    try:
        await _append(
            host,
            {
                **attempt,
                "outcome": outcome,
                "recorded_at": datetime.now(tz=UTC).isoformat(),
                "error_type": type(error).__name__,
            },
        )
    except (Exception, asyncio.CancelledError) as exc:
        _LOGGER.error(
            "canary_terminal_audit_unavailable",
            extra={
                "event_id": attempt["event_id"],
                "correlation_id": attempt["correlation_id"],
                "attempt_id": attempt["attempt_id"],
                "error_type": type(exc).__name__,
            },
        )


__all__ = ["CANARY_EVENT_TYPE", "CANARY_SOURCE", "process_canary"]
