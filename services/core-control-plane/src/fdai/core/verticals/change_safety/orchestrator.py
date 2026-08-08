"""Change Safety vertical - integrated risk classification.

Phase 3 § Change Safety. Change events (drift, config change, IaC diff)
land on the shared control loop; this vertical classifies them into:

- **low-risk auto** - proceed to executor via the risk-gate (only when
  the risk-gate itself returns AUTO, i.e. the ActionType is promoted
  to enforce).
- **HIL** - human-in-the-loop approval required.
- **timeout / reject** - no-op that still audits.

Distinct principals for approval vs execution (per
[security-and-identity.md § Execution identity]) is enforced by the
delivery adapter + composition root; this module carries only the
classification logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ChangeRisk(StrEnum):
    """Coarse risk bucket for one change event."""

    LOW = "low"
    HIGH = "high"


class ChangeDecisionOutcome(StrEnum):
    AUTO = "auto"
    HIL = "hil"
    REJECT = "reject"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class ChangeContext:
    """What the classifier needs to decide.

    ``is_reversible`` and ``target_environment`` come from the
    inventory adapter + ActionType metadata; the classifier NEVER
    re-derives them.
    """

    change_id: str
    resource_id: str
    is_reversible: bool
    is_out_of_band: bool
    """True when the change was observed outside a merged remediation
    PR / known pipeline principal. Any out-of-band change routes to HIL
    per phase-3 doc even if the diff itself is trivial."""

    target_environment: str
    """`prod` / `staging` / `dev` - production changes always HIL."""


@dataclass(frozen=True, slots=True)
class ChangeDecision:
    """Frozen record produced by :meth:`ChangeSafetyClassifier.classify`."""

    change_id: str
    risk: ChangeRisk
    outcome: ChangeDecisionOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ChangeSafetyConfig:
    production_environments: frozenset[str] = frozenset({"prod"})


class ChangeSafetyClassifier:
    """Compute the AUTO / HIL / REJECT / TIMEOUT outcome for a change."""

    def __init__(self, *, config: ChangeSafetyConfig | None = None) -> None:
        self._config = config or ChangeSafetyConfig()

    def classify(self, context: ChangeContext) -> ChangeDecision:
        reasons: list[str] = []

        if context.is_out_of_band:
            reasons.append("out_of_band_change")
        if context.target_environment in self._config.production_environments:
            reasons.append(f"production_environment:{context.target_environment}")
        if not context.is_reversible:
            reasons.append("irreversible_change")

        if reasons:
            return ChangeDecision(
                change_id=context.change_id,
                risk=ChangeRisk.HIGH,
                outcome=ChangeDecisionOutcome.HIL,
                reasons=tuple(reasons),
            )
        return ChangeDecision(
            change_id=context.change_id,
            risk=ChangeRisk.LOW,
            outcome=ChangeDecisionOutcome.AUTO,
        )

    def record_terminal(
        self, *, change_id: str, outcome: ChangeDecisionOutcome, reason: str
    ) -> ChangeDecision:
        """Record a reject / timeout terminal state for the audit trail.

        Kept as a helper method (not a public constructor path) so the
        classifier is the only surface that stamps ``ChangeDecision``
        records - every audit entry is reconstructable from one call.
        """
        if outcome not in (
            ChangeDecisionOutcome.REJECT,
            ChangeDecisionOutcome.TIMEOUT,
        ):
            raise ValueError("record_terminal only accepts REJECT / TIMEOUT outcomes")
        return ChangeDecision(
            change_id=change_id,
            risk=ChangeRisk.HIGH,
            outcome=outcome,
            reasons=(reason,),
        )


__all__ = [
    "ChangeContext",
    "ChangeDecision",
    "ChangeDecisionOutcome",
    "ChangeRisk",
    "ChangeSafetyClassifier",
    "ChangeSafetyConfig",
]
