"""Pure normalization and bounded-state helpers for Heimdall."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TRACE_CONTINUITY_REASONS = frozenset(
    {
        "trace_context_regenerated",
        "trace_context_dropped",
        "trace_hop_order_invalid",
    }
)
_TRACE_CONTINUITY_EVENT = "trace-continuity.discontinuity"
_SEVERITY_ALIASES = {
    "sev1": "critical",
    "sev2": "high",
    "sev3": "medium",
    "sev4": "low",
    "sev5": "info",
}
_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})


def evict_oldest(mapping: dict[Any, Any], cap: int, *, keep: Any = None) -> None:
    """Drop oldest entries until a mapping is bounded, while retaining the new key."""
    while len(mapping) > cap:
        for key in mapping:
            if key != keep:
                del mapping[key]
                break
        else:
            break


def trace_continuity_evidence(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return only Huginn-bounded continuity evidence for the matching Event."""
    if event.get("event_type") != _TRACE_CONTINUITY_EVENT:
        return {}
    attributes = event.get("attributes")
    if not isinstance(attributes, Mapping):
        return {}
    evidence = attributes.get("trace_continuity")
    if not isinstance(evidence, Mapping):
        return {}
    reason = evidence.get("reason_code")
    if not isinstance(reason, str) or reason not in TRACE_CONTINUITY_REASONS:
        return {}
    return dict(evidence)


def event_severity(event: Mapping[str, Any]) -> str:
    """Normalize an event severity and default unknown values toward review."""
    attributes = event.get("attributes")
    attribute_severity = attributes.get("severity") if isinstance(attributes, Mapping) else None
    raw = str(event.get("severity") or event.get("severity_hint") or attribute_severity or "")
    normalized = raw.strip().casefold()
    aliased = _SEVERITY_ALIASES.get(normalized, normalized)
    return aliased if aliased in _SEVERITIES else "medium"


__all__ = [
    "TRACE_CONTINUITY_REASONS",
    "event_severity",
    "evict_oldest",
    "trace_continuity_evidence",
]
