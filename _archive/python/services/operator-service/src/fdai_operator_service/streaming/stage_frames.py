"""Fail-closed validation for Core stage frames consumed by Operator Live."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

from .live_stream import LiveStreamEvent

_STAGES: Final = frozenset({"ingest", "route", "verify", "gate", "execute", "audit"})
_PHASES: Final = frozenset({"begin", "progress", "done", "failed"})
_SOURCES: Final = frozenset({"unknown", "synthetic-dev", "replay", "runtime-observed"})
_MAX_IDENTIFIER_CHARS: Final = 1_024
_MAX_ERROR_CHARS: Final = 512
_MAX_PAYLOAD_BYTES: Final = 256 * 1_024
_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)


def parse_stage_frame(payload: Mapping[str, object]) -> LiveStreamEvent | None:
    """Return a normalized stage event or reject malformed untrusted input."""
    try:
        event_id = _identifier(payload.get("event_id"))
        correlation_id = _identifier(payload.get("correlation_id"))
        stage = payload.get("stage")
        phase = payload.get("phase")
        source = payload.get("source", "unknown")
        timestamp = payload.get("ts")
        detail = payload.get("detail")
        error = payload.get("error")
        if (
            event_id is None
            or correlation_id is None
            or stage not in _STAGES
            or phase not in _PHASES
            or source not in _SOURCES
            or not isinstance(timestamp, str)
            or (detail is not None and not isinstance(detail, Mapping))
            or (error is not None and not isinstance(error, str))
            or (phase == "failed") != (error is not None)
            or (isinstance(error, str) and (not error or len(error) > _MAX_ERROR_CHARS))
        ):
            return None
        observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if observed_at.tzinfo is None or observed_at > datetime.now(UTC) + _MAX_FUTURE_SKEW:
            return None
        normalized: dict[str, object] = {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "stage": stage,
            "phase": phase,
            "source": source,
            "ts": timestamp,
        }
        if detail:
            normalized["detail"] = dict(detail)
        if error is not None:
            normalized["error"] = error
        encoded = json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            return None
        return LiveStreamEvent(event_id=event_id, payload=normalized)
    except (TypeError, ValueError, OverflowError):
        return None


def _identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_CHARS:
        return None
    return value


__all__ = ["parse_stage_frame"]
