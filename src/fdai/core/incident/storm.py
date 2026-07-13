"""Storm coordinator - incident-command sequencing under event storms.

Design contract: `docs/roadmap/fork-and-sequencing/scope-expansion.md § 3.1` (incident
lifecycle) extended with storm handling.

When a single root fault fans out into many correlated incidents, firing
every remediation at once is dangerous: it multiplies blast radius,
races on shared dependencies, and buries the operator. A human incident
commander instead *sequences* the response - highest-severity first, a
capped number in flight, and a raised approval bar while the situation is
unstable.

`StormCoordinator` encodes that deterministically and with no I/O:

- **Storm detection** - counts signals inside a sliding window; a count
  at or above the threshold is a storm.
- **Priority sequencing** - orders remediations by severity, then blast
  radius, then a stable id, so the plan is reproducible.
- **Concurrency cap** - splits the ordered plan into capped waves; under
  a storm the cap tightens (default 1 = strictly serial) so a fan-out
  does not execute in parallel.
- **Dynamic HIL** - under a storm the policy raises the approval bar
  (escalate at or above a configured severity) so nothing high-impact
  auto-executes mid-storm.

The coordinator is advisory: it produces a `StormPolicy` and an ordered
plan that the risk gate and executor consume. It never executes, never
holds a lock, and takes no model call - it stays under the ``core/``
import rule (only ``fdai.shared.contracts`` + stdlib).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.shared.contracts.models import IncidentSeverity

# SEV1 (customer-visible outage) is the most urgent; SEV5 the least.
_SEVERITY_RANK: dict[IncidentSeverity, int] = {
    IncidentSeverity.SEV1: 1,
    IncidentSeverity.SEV2: 2,
    IncidentSeverity.SEV3: 3,
    IncidentSeverity.SEV4: 4,
    IncidentSeverity.SEV5: 5,
}


@dataclass(frozen=True, slots=True)
class StormSignal:
    """One remediation-worthy signal entering the coordinator."""

    signal_id: str
    severity: IncidentSeverity
    resource_ref: str
    arrived_at: datetime
    blast_radius: int = 1  # estimated count of affected resources


@dataclass(frozen=True, slots=True)
class RemediationStep:
    """A signal placed at a deterministic position in the response plan."""

    order: int
    wave: int
    signal_id: str
    resource_ref: str
    severity: IncidentSeverity


@dataclass(frozen=True, slots=True)
class StormPolicy:
    """The advisory the risk gate reads while a storm is (or is not) active."""

    active: bool
    signal_count: int
    concurrency_cap: int
    escalate_hil_at_or_above: IncidentSeverity | None
    reason: str


class StormCoordinator:
    """Deterministic incident-command planner for event storms.

    Configuration-driven: the storm threshold, window, concurrency caps,
    and storm HIL severity are constructor args so a fork tunes them
    without editing this class.
    """

    def __init__(
        self,
        *,
        storm_threshold: int = 5,
        window: timedelta = timedelta(minutes=5),
        base_concurrency: int = 3,
        storm_concurrency: int = 1,
        storm_hil_at_or_above: IncidentSeverity = IncidentSeverity.SEV3,
    ) -> None:
        if storm_threshold < 1:
            raise ValueError("storm_threshold MUST be >= 1")
        if window <= timedelta(0):
            raise ValueError("window MUST be positive")
        if base_concurrency < 1 or storm_concurrency < 1:
            raise ValueError("concurrency caps MUST be >= 1")
        self._storm_threshold = storm_threshold
        self._window = window
        self._base_concurrency = base_concurrency
        self._storm_concurrency = storm_concurrency
        self._storm_hil = storm_hil_at_or_above

    def assess(self, signals: Iterable[StormSignal], *, now: datetime) -> StormPolicy:
        """Classify the current signal load into a storm policy.

        Only signals whose ``arrived_at`` falls inside ``window`` ending
        at ``now`` count toward the storm threshold.
        """
        recent = self._within_window(signals, now=now)
        count = len(recent)
        active = count >= self._storm_threshold
        if active:
            return StormPolicy(
                active=True,
                signal_count=count,
                concurrency_cap=self._storm_concurrency,
                escalate_hil_at_or_above=self._storm_hil,
                reason=f"storm:{count}>={self._storm_threshold} within {self._window}",
            )
        return StormPolicy(
            active=False,
            signal_count=count,
            concurrency_cap=self._base_concurrency,
            escalate_hil_at_or_above=None,
            reason=f"nominal:{count}<{self._storm_threshold} within {self._window}",
        )

    def sequence(
        self, signals: Sequence[StormSignal], *, concurrency_cap: int
    ) -> tuple[RemediationStep, ...]:
        """Order signals into a reproducible, wave-batched response plan.

        Ordering is severity (SEV1 first), then larger blast radius, then
        a stable ``(resource_ref, signal_id)`` tiebreak. Steps are packed
        into waves of at most ``concurrency_cap`` so a storm executes in
        capped, sequenced batches rather than all at once.
        """
        if concurrency_cap < 1:
            raise ValueError("concurrency_cap MUST be >= 1")
        ordered = sorted(
            signals,
            key=lambda s: (
                _SEVERITY_RANK.get(s.severity, 99),
                -s.blast_radius,
                s.resource_ref,
                s.signal_id,
            ),
        )
        return tuple(
            RemediationStep(
                order=i,
                wave=i // concurrency_cap,
                signal_id=s.signal_id,
                resource_ref=s.resource_ref,
                severity=s.severity,
            )
            for i, s in enumerate(ordered)
        )

    def plan(
        self, signals: Sequence[StormSignal], *, now: datetime
    ) -> tuple[StormPolicy, tuple[RemediationStep, ...]]:
        """Assess the storm and sequence the plan under the resulting cap.

        The plan sequences only the in-window signals - the same set the
        assessment counted - so a stale signal (arrived before ``window``)
        does not get a remediation step it should not have. A caller that
        wants to sequence an explicit signal set unconditionally uses
        :meth:`sequence` directly.
        """
        policy = self.assess(signals, now=now)
        recent = self._within_window(signals, now=now)
        steps = self.sequence(recent, concurrency_cap=policy.concurrency_cap)
        return policy, steps

    def _within_window(
        self, signals: Iterable[StormSignal], *, now: datetime
    ) -> list[StormSignal]:
        """Signals whose ``arrived_at`` falls inside ``window`` ending at ``now``."""
        return [s for s in signals if timedelta(0) <= now - s.arrived_at <= self._window]


__all__ = [
    "RemediationStep",
    "StormCoordinator",
    "StormPolicy",
    "StormSignal",
]
