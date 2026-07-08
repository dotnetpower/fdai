"""Event correlation - group related events into one incident.

A deterministic stage after normalize + dedupe
(observability-and-detection.md section 1): derive an incident anchor
from an event's correlation keys within a bounded time window, so
downstream tiers reason about one **incident**, not a storm of
duplicates.

- **Deterministic-first**: correlate by shared keys (an explicit
  ``correlation_id``, else the resource reference) within a time
  **window bucket**. No model call.
- **Grouping, not causation**: correlation only asserts events *belong
  together*; assigning the cause is RCA's job (``core/rca``), never this
  stage's.
- **Idempotent + windowed**: the incident id is
  ``incident_id_for(keys + window-bucket)`` from
  :func:`fdai.core.incident.registry.incident_id_for`, so a burst of
  events sharing a key in one window collapses to one incident, and a
  late/out-of-order event in the same bucket joins it. A new bucket
  opens a linked follow-on incident (a fresh id).
- **Uncorrelatable events pass through**: an event with no
  correlation_id and no resource reference cannot be anchored; it is
  reported ``correlated=False`` and handled on its own (never dropped).

The registry (:class:`fdai.core.incident.registry.IncidentRegistry`) is
the only writer of incident membership; this stage produces the
correlation keys that ``IncidentRegistry.open`` consumes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.incident.registry import incident_id_for
from fdai.shared.contracts.models import Event

_DEFAULT_WINDOW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """The correlation stage's verdict for one event."""

    correlated: bool
    incident_id: str | None
    correlation_keys: tuple[str, ...]
    window_bucket: int | None
    reason: str


class EventCorrelator:
    """Deterministic key + window correlation over a single event.

    Stateless: the incident id is derived purely from the event's keys
    and its window bucket, so two correlators with the same
    ``window_seconds`` always agree (deterministic replay). Membership
    accumulation lives in :class:`IncidentRegistry`, keyed by the same
    id.
    """

    def __init__(self, *, window_seconds: float = _DEFAULT_WINDOW_SECONDS) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds MUST be > 0")
        self._window = float(window_seconds)

    def correlate(self, event: Event) -> CorrelationResult:
        """Anchor ``event`` to an incident id, or report uncorrelatable."""
        base_keys = self._base_keys(event)
        if not base_keys:
            return CorrelationResult(
                correlated=False,
                incident_id=None,
                correlation_keys=(),
                window_bucket=None,
                reason="no_correlation_anchor",
            )
        bucket = int(event.detected_at.timestamp() // self._window)
        keys = (*base_keys, f"window:{bucket}")
        return CorrelationResult(
            correlated=True,
            incident_id=str(incident_id_for(keys)),
            correlation_keys=keys,
            window_bucket=bucket,
            reason="correlated",
        )

    def _base_keys(self, event: Event) -> tuple[str, ...]:
        """Extract the correlation anchor keys (before windowing).

        Precedence: an explicit ``correlation_id`` is the strongest
        anchor; the resource reference is the fallback. Both are included
        when present, and the incident id is derived from the *combined*
        key set (``incident_id_for`` sorts + de-dups the whole tuple).
        Two events therefore correlate when they share the *same* anchor
        set - not merely one key in common.
        """
        keys: list[str] = []
        if event.correlation_id:
            keys.append(f"corr:{event.correlation_id}")
        resource = event.resource_ref or _resource_ref_from_payload(event.payload)
        if resource:
            keys.append(f"res:{resource}")
        return tuple(keys)


def _resource_ref_from_payload(payload: Mapping[str, Any]) -> str | None:
    resource = payload.get("resource")
    if isinstance(resource, Mapping):
        ref = resource.get("resource_id") or resource.get("resource_ref")
        if isinstance(ref, str) and ref:
            return ref
    return None


__all__ = ["CorrelationResult", "EventCorrelator"]
