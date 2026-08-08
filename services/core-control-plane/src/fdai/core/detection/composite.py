"""Composite (multivariate) anomaly detector - #7 compound-degradation signal.

A single-metric z-score (`core/detection/anomaly.py`) is noisy: one
stream wobbling past its threshold is often benign. An organization's
on-call knows a *real* incident by **correlated** signals firing
together - latency up **and** error-rate up **and** saturation high - a
compound degradation a single-metric detector either misses (each stream
just under threshold) or over-reports (one noisy stream alone).

This detector is a **fuser, not a new baseline**: it consumes the
per-metric :class:`~fdai.core.detection.anomaly.AnomalyFinding` objects
already produced for one resource + window and raises a
:class:`CompositeAnomalyFinding` only when a **quorum** of them fire.
It is deterministic and explainable - the members, their combined
magnitude (root-sum-square of z-scores), and the quorum are all recorded
- and it is a **suppressor at the single-signal end** (below quorum it
abstains) and an **amplifier at the compound end** (concurrent signals
escalate severity beyond any single member).

Shadow-first and CSP-neutral: it emits an
:class:`~fdai.shared.contracts.models.Event`
(``event_type="anomaly.composite"``) in shadow mode that re-enters
``event-ingest`` like any finding, and imports only
``fdai.shared.contracts`` + the anomaly finding type + the stdlib.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.core.detection.anomaly import AnomalyFinding
from fdai.shared.contracts.models import Category, Event, Mode, Severity

_COMPOSITE_EVENT_TYPE = "anomaly.composite"
_DEFAULT_SOURCE = "fdai.core.detection.composite"

# A flat-baseline member (z_score is None) is a strong signal; give it a
# fixed weight in the combined magnitude rather than dropping it.
_FLAT_BASELINE_Z = 5.0


@dataclass(frozen=True, slots=True)
class CompositeAnomalyFinding:
    """A fused, multivariate anomaly over one resource + window.

    ``member_metrics`` names the concurrently-anomalous streams;
    ``combined_magnitude`` is the root-sum-square of member z-scores (a
    flat-baseline member contributes a fixed weight). Carries enough
    context to reconstruct the fusion without re-reading the members.
    """

    detector_id: str
    resource_ref: str
    window_bucket: str
    member_metrics: tuple[str, ...]
    member_count: int
    quorum: int
    combined_magnitude: float
    dominant_direction: str
    """``"over"``, ``"under"``, or ``"mixed"`` across members."""
    category: Category
    severity: Severity
    idempotency_key: str
    reason: str


class CompositeAnomalyDetector:
    """Deterministic quorum-based fuser of per-metric anomaly findings."""

    def __init__(
        self,
        *,
        detector_id: str,
        quorum: int = 2,
        category: Category = Category.RELIABILITY,
        source: str = _DEFAULT_SOURCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not detector_id:
            raise ValueError("detector_id MUST be non-empty")
        if quorum < 2:
            raise ValueError("quorum MUST be >= 2 (a composite needs multiple signals)")
        self._detector_id = detector_id
        self._quorum = quorum
        self._category = category
        self._source = source
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def fuse(
        self,
        *,
        resource_ref: str,
        window_bucket: str,
        findings: Sequence[AnomalyFinding],
    ) -> CompositeAnomalyFinding | None:
        """Return a composite finding when a quorum of members fire, else ``None``.

        Only members whose ``resource_ref`` matches are considered (a
        composite is per-resource). Duplicate metrics collapse to one
        member (the highest-magnitude occurrence) so a re-emitted stream
        cannot inflate the quorum. Below quorum -> ``None`` (a single
        noisy stream is not a compound anomaly).
        """
        members = _dedupe_strongest(
            [f for f in findings if f.resource_ref == resource_ref and _has_valid_magnitude(f)]
        )
        if len(members) < self._quorum:
            return None

        member_metrics = tuple(sorted(m.metric for m in members))
        combined = _combined_magnitude(members)
        direction = _dominant_direction(members)
        severity = _composite_severity(member_count=len(members), combined=combined)
        reason = (
            f"{len(members)} concurrent anomalies (quorum {self._quorum}) on "
            f"'{resource_ref}': combined_magnitude {combined:.2f}, "
            f"direction {direction}"
        )
        return CompositeAnomalyFinding(
            detector_id=self._detector_id,
            resource_ref=resource_ref,
            window_bucket=window_bucket,
            member_metrics=member_metrics,
            member_count=len(members),
            quorum=self._quorum,
            combined_magnitude=combined,
            dominant_direction=direction,
            category=self._category,
            severity=severity,
            idempotency_key=self._idempotency_key(
                resource_ref=resource_ref,
                window_bucket=window_bucket,
                member_metrics=member_metrics,
            ),
            reason=reason,
        )

    def to_event(
        self,
        finding: CompositeAnomalyFinding,
        *,
        mode: Mode = Mode.SHADOW,
    ) -> Event:
        """Normalize a composite finding into a shadow-mode Event."""
        now = self._clock()
        payload: dict[str, object] = {
            "kind": "anomaly.composite",
            "detector_id": finding.detector_id,
            "resource": {"resource_ref": finding.resource_ref},
            "member_metrics": list(finding.member_metrics),
            "member_count": finding.member_count,
            "quorum": finding.quorum,
            "combined_magnitude": finding.combined_magnitude,
            "dominant_direction": finding.dominant_direction,
            "category": finding.category.value,
            "severity": finding.severity.value,
            "window_bucket": finding.window_bucket,
            "reason": finding.reason,
        }
        return Event(
            schema_version="1.0.0",
            event_id=uuid4(),
            idempotency_key=finding.idempotency_key,
            source=self._source,
            event_type=_COMPOSITE_EVENT_TYPE,
            resource_ref=finding.resource_ref,
            payload=payload,
            detected_at=now,
            ingested_at=now,
            mode=mode,
        )

    def _idempotency_key(
        self,
        *,
        resource_ref: str,
        window_bucket: str,
        member_metrics: tuple[str, ...],
    ) -> str:
        members = ",".join(member_metrics)
        return str(
            uuid5(
                NAMESPACE_URL,
                f"fdai-composite:{self._detector_id}:{resource_ref}:{window_bucket}:{members}",
            )
        )


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------


def _member_z(finding: AnomalyFinding) -> float:
    """Return a member's magnitude, substituting a fixed weight for a flat baseline."""
    return _FLAT_BASELINE_Z if finding.z_score is None else finding.z_score


def _has_valid_magnitude(finding: AnomalyFinding) -> bool:
    """True unless the member carries a corrupt (non-finite) z-score.

    A flat-baseline member (``z_score is None``) is valid; a NaN / inf
    z-score is a corrupt signal that would poison the root-sum-square
    magnitude and is excluded before the quorum is counted, so garbage
    input cannot manufacture (or inflate) a composite finding.
    """
    return finding.z_score is None or math.isfinite(finding.z_score)


def _dedupe_strongest(findings: Sequence[AnomalyFinding]) -> list[AnomalyFinding]:
    """Collapse duplicate metrics to their highest-magnitude occurrence.

    Order-stable by metric name so the fusion is deterministic regardless
    of input order.
    """
    strongest: dict[str, AnomalyFinding] = {}
    for finding in findings:
        current = strongest.get(finding.metric)
        if current is None or _member_z(finding) > _member_z(current):
            strongest[finding.metric] = finding
    return [strongest[metric] for metric in sorted(strongest)]


def _combined_magnitude(members: Sequence[AnomalyFinding]) -> float:
    """Root-sum-square of member z-scores - concurrent signals reinforce."""
    return round(math.sqrt(sum(_member_z(m) ** 2 for m in members)), 4)


def _dominant_direction(members: Sequence[AnomalyFinding]) -> str:
    """Return the shared direction, or ``"mixed"`` when members disagree."""
    directions = {m.direction for m in members}
    if directions == {"over"}:
        return "over"
    if directions == {"under"}:
        return "under"
    return "mixed"


def _composite_severity(*, member_count: int, combined: float) -> Severity:
    """Escalate with both the breadth (member count) and depth (magnitude).

    A broad, deep composite is the strongest operational signal; a
    two-signal, near-threshold composite stays medium.
    """
    if member_count >= 3 or combined >= 8.0:
        return Severity.CRITICAL
    if combined >= 6.0:
        return Severity.HIGH
    return Severity.MEDIUM


__all__ = [
    "CompositeAnomalyDetector",
    "CompositeAnomalyFinding",
]
