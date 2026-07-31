"""Fault-injection contract - scenarios, outcomes, experiment results.

A chaos experiment is a **governed, reversible perturbation** used to
validate that the control loop detects and proposes mitigation for an
injected fault (session notes slide 9: "Fault Injection x SRE Agent"). It
carries all four safety invariants by construction:

- **stop-condition** - a bounded ``duration_seconds`` and an explicit stop.
- **rollback** - the injector's ``stop`` is always called (harness finally).
- **blast-radius limit** - a per-scenario ``blast_radius_cap`` on targets.
- **audit** - every experiment produces an :class:`ExperimentResult`.

Chaos is HIL-only: Loki (the chaos agent) proposes an experiment, Forseti
judges it, and Var approves it before the harness may run in ``enforce``
mode. The upstream default injector is a shadow no-op, so an unapproved or
mis-wired experiment perturbs nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai.shared.contracts.models import Mode


class ExperimentOutcome(StrEnum):
    """Terminal outcome of one chaos experiment."""

    SHADOWED = "shadowed"
    """Ran in shadow mode - intent recorded, nothing perturbed."""

    VALIDATED = "validated"
    """Enforced, and the expected detection signal fired (loop works)."""

    NOT_DETECTED = "not_detected"
    """Enforced, but the expected signal did not fire (a detection gap)."""

    BLAST_RADIUS_EXCEEDED = "blast_radius_exceeded"
    """Refused - approved targets exceeded the scenario cap; nothing ran."""

    ABORTED = "aborted"
    """Injection failed; the harness stopped and rolled back."""

    ROLLBACK_FAILED = "rollback_failed"
    """Injected, but rollback did not fully succeed - a fault may still be
    live. This is the operator's highest-priority state, so it takes
    precedence over the detection verdict; ``detected`` / ``error`` still
    carry the detail. ``reverted`` is ``False`` for this outcome."""


@dataclass(frozen=True, slots=True)
class FaultScenario:
    """One reversible fault-injection scenario.

    ``target_selector`` is an opaque, CSP-neutral selector handle (never a
    concrete customer resource id). ``expected_signal`` is the detection
    signal the loop SHOULD raise when this fault is live - the harness uses
    it to decide VALIDATED vs NOT_DETECTED.
    """

    scenario_id: str
    fault_type: str
    description: str
    target_selector: str
    expected_signal: str
    blast_radius_cap: int
    duration_seconds: float
    params: Mapping[str, str] = field(default_factory=dict)
    rollback_note: str = ""

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("FaultScenario.scenario_id MUST be non-empty")
        if not self.fault_type:
            raise ValueError("FaultScenario.fault_type MUST be non-empty")
        if self.blast_radius_cap <= 0:
            raise ValueError("FaultScenario.blast_radius_cap MUST be positive")
        if self.duration_seconds <= 0:
            raise ValueError("FaultScenario.duration_seconds MUST be positive")


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """The audit-shaped record of one experiment run."""

    experiment_id: str
    scenario_id: str
    mode: Mode
    targets: tuple[str, ...]
    outcome: ExperimentOutcome
    expected_signal: str
    detected: bool
    started_at: datetime
    ended_at: datetime
    injected: bool
    stopped: bool
    error: str | None = None
    stop_reason: str | None = None

    @property
    def reverted(self) -> bool:
        """True iff the perturbation was stopped/rolled back (or never made)."""
        return self.stopped or not self.injected


__all__ = [
    "ExperimentOutcome",
    "ExperimentResult",
    "FaultScenario",
]
