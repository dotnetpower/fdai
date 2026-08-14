"""Axis-E live-blast-probe resolution (execution-model.md 4).

Turns a *recorded* probe reading into the pure Axis-E literal that
:func:`~fdai.core.risk_gate.ceiling.resolve_ceiling` consumes. This module
performs no I/O: the dispatch path awaits the
:class:`~fdai.shared.providers.blast_probe.LiveBlastProbe` adapter and passes
the reading in, so a replay re-derives the same axis from the recorded
reading without ever re-querying the probe (execution-model.md 4.2).

Every branch either preserves or lowers autonomy. A probe that is
unconfigured, unavailable, substituted, stale, degraded, opinion-less, or
persistently blind can never make an action more autonomous than the static
ceiling already allows.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.risk_gate.ceiling import ProbeResult
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.blast_probe import ProbeVerdict

# Repeated blindness stops being a "confirm by hand" case and becomes a
# "stop executing this ActionType until an operator inspects" case
# (execution-model.md 4.2).
FAILURE_ESCALATION_THRESHOLD = 3

_VERDICT_TO_AXIS: dict[ProbeVerdict, ProbeResult] = {
    ProbeVerdict.QUIET: "quiet",
    ProbeVerdict.ACTIVE: "active",
    ProbeVerdict.OVERLOADED: "overloaded",
}

# Least-autonomous-wins ordering inside the axis. Higher = more autonomous.
_AXIS_RANK: dict[ProbeResult, int] = {"quiet": 2, "active": 1, "overloaded": 0}


@dataclass(frozen=True, slots=True)
class LiveProbeObservation:
    """One already-measured probe reading, as recorded for replay.

    ``probe_id`` is compared against ``ActionType.live_probe_ref`` so a
    reading measured for a different probe is never credited to this action.
    ``age_seconds`` and ``max_age_seconds`` are both required to prove
    freshness; either one missing leaves freshness unproven, which floors the
    axis at ``active`` rather than trusting an undatable reading.

    Raises:
        ValueError: when ``probe_id`` is empty.
    """

    probe_id: str
    verdict: ProbeVerdict
    degraded: bool = False
    age_seconds: float | None = None
    max_age_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.probe_id:
            raise ValueError("LiveProbeObservation.probe_id MUST be non-empty")

    @property
    def is_fresh(self) -> bool:
        """``True`` only when the reading proves it is inside its own window."""
        if self.age_seconds is None or self.max_age_seconds is None:
            return False
        if self.age_seconds < 0 or self.max_age_seconds <= 0:
            return False
        return self.age_seconds <= self.max_age_seconds


@dataclass(frozen=True, slots=True)
class LiveProbeAxis:
    """The resolved Axis-E input plus the reason recorded on the audit entry."""

    result: ProbeResult | None
    reason: str


def _floor_at_active(candidate: ProbeResult) -> ProbeResult:
    """Clamp a reading that cannot be fully trusted to at most ``active``."""
    return candidate if _AXIS_RANK[candidate] <= _AXIS_RANK["active"] else "active"


def resolve_live_probe_axis(
    action_type: OntologyActionType,
    *,
    observation: LiveProbeObservation | None = None,
    failure_streak: int = 0,
) -> LiveProbeAxis:
    """Resolve the Axis-E input for ``action_type`` from a recorded reading.

    Returns ``result=None`` ("no opinion", static ceiling wins) only when the
    ActionType declares no ``live_probe_ref`` and no reading was supplied.
    Every other uncertainty resolves to ``active`` (a human confirms) or
    ``overloaded`` (defer), so an absent, substituted, stale, degraded, or
    blind probe can only preserve or lower autonomy.

    Args:
        action_type: The ontology ActionType whose ``live_probe_ref`` decides
            whether Axis E has an opinion at all.
        observation: The reading already measured for this dispatch, or
            ``None`` when the probe was not reached.
        failure_streak: Consecutive failed or blind probe attempts for this
            probe. At or above :data:`FAILURE_ESCALATION_THRESHOLD` the axis
            defers instead of asking a human to keep approving by hand.
    """
    ref = action_type.live_probe_ref
    if ref is None:
        if observation is None:
            return LiveProbeAxis(None, "no live_probe_ref (no opinion)")
        # A reading for an action that declares no probe is unsolicited
        # evidence; crediting it would let an unbound probe speak for this
        # ActionType, so it lowers rather than informs.
        return LiveProbeAxis(
            "active", f"unsolicited probe reading {observation.probe_id!r} (no live_probe_ref)"
        )

    if failure_streak >= FAILURE_ESCALATION_THRESHOLD:
        return LiveProbeAxis(
            "overloaded", f"probe {ref!r} blind for {failure_streak} consecutive attempts"
        )
    if observation is None:
        return LiveProbeAxis("active", f"probe {ref!r} unavailable")
    if observation.probe_id != ref:
        return LiveProbeAxis(
            "active", f"probe reading {observation.probe_id!r} does not match ref {ref!r}"
        )
    if observation.verdict is ProbeVerdict.NO_OPINION:
        return LiveProbeAxis("active", f"probe {ref!r} returned no opinion")

    candidate = _VERDICT_TO_AXIS[observation.verdict]
    if observation.degraded:
        return LiveProbeAxis(_floor_at_active(candidate), f"probe {ref!r} degraded ({candidate})")
    if not observation.is_fresh:
        return LiveProbeAxis(_floor_at_active(candidate), f"probe {ref!r} stale ({candidate})")
    return LiveProbeAxis(candidate, f"probe {ref!r}={candidate}")


__all__ = [
    "FAILURE_ESCALATION_THRESHOLD",
    "LiveProbeAxis",
    "LiveProbeObservation",
    "resolve_live_probe_axis",
]
