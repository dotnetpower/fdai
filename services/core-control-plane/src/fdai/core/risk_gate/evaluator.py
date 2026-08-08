"""Unified risk decision - combines gate.py with the authority pipeline.

The two risk evaluators cover **different, complementary** concerns and
neither subsumes the other:

- [`gate.py`](gate.py) :class:`RiskGate` - the runtime **Action** safety
  layer: human-override exemptions, precondition freshness, the
  per-dispatch blast-count / rate caps, and the promotion mode
  (shadow vs enforce).
- [`authority.py`](authority.py) - the **policy ceiling**: the
  risk-classification first-match table (Axis A) plus the six-axis
  ActionType ceiling.

This module normalizes both to a single canonical :class:`AxisLevel`
ladder and takes the **minimum** (most conservative). Neither evaluator
is modified, so both keep their existing behaviour and tests - the
combination is purely additive.

Level normalization (gate outcome -> canonical AxisLevel):

- ``DENY``    -> ``DENY``
- ``HIL``     -> ``ENFORCE_HIL``
- ``ABSTAIN`` -> ``ENFORCE_HIL`` (abstain hands the decision to a human)
- ``AUTO`` + ``Mode.ENFORCE`` -> ``ENFORCE_AUTO``
- ``AUTO`` + ``Mode.SHADOW``  -> ``SHADOW_ONLY`` (promoted-shadow: judge only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fdai.core.risk_gate.authority import ExecutionAuthorityDecision
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.shared.contracts.models import Mode

_GATE_TERMINAL_TO_LEVEL: dict[RiskDecisionOutcome, AxisLevel] = {
    RiskDecisionOutcome.DENY: AxisLevel.DENY,
    RiskDecisionOutcome.HIL: AxisLevel.ENFORCE_HIL,
    RiskDecisionOutcome.ABSTAIN: AxisLevel.ENFORCE_HIL,
}

_LEVEL_TO_DECISION: dict[AxisLevel, str] = {
    AxisLevel.ENFORCE_AUTO: "auto",
    AxisLevel.ENFORCE_HIL: "hil",
    AxisLevel.SHADOW_ONLY: "shadow",
    AxisLevel.DENY: "deny",
}


def gate_level(decision: RiskDecision) -> AxisLevel:
    """Normalize a gate :class:`RiskDecision` to the canonical ladder."""
    terminal = _GATE_TERMINAL_TO_LEVEL.get(decision.outcome)
    if terminal is not None:
        return terminal
    # AUTO: enforce-promoted executes; shadow-promoted is judge-only.
    return (
        AxisLevel.ENFORCE_AUTO if decision.effective_mode is Mode.ENFORCE else AxisLevel.SHADOW_ONLY
    )


@dataclass(frozen=True, slots=True)
class UnifiedRiskDecision:
    """The single decision produced by combining both evaluators."""

    level: AxisLevel
    quorum: int
    winning_side: str  # "gate" | "authority" | "gate+authority"
    gate: RiskDecision
    authority: ExecutionAuthorityDecision | None

    @property
    def decision(self) -> str:
        return _LEVEL_TO_DECISION[self.level]

    @property
    def is_auto(self) -> bool:
        return self.level is AxisLevel.ENFORCE_AUTO

    @property
    def requires_hil(self) -> bool:
        return self.level is AxisLevel.ENFORCE_HIL

    @property
    def is_denied(self) -> bool:
        return self.level is AxisLevel.DENY

    def as_audit_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "decision": self.decision,
            "quorum": self.quorum,
            "winning_side": self.winning_side,
            "gate_outcome": self.gate.outcome.value,
            "gate_reasons": list(self.gate.reasons),
        }
        if self.authority is not None:
            entry["authority"] = self.authority.as_audit_dict()
        return entry


def combine(
    gate_decision: RiskDecision,
    authority: ExecutionAuthorityDecision | None,
) -> UnifiedRiskDecision:
    """Combine the gate decision with the (optional) authority decision.

    Takes the most conservative (minimum) canonical level. When the
    authority is absent (no risk table wired), the gate decision stands
    alone. The ``quorum`` comes from the authority (Axis A) when present,
    else defaults to 1.
    """
    g_level = gate_level(gate_decision)
    if authority is None:
        return UnifiedRiskDecision(
            level=g_level,
            quorum=1,
            winning_side="gate",
            gate=gate_decision,
            authority=None,
        )
    a_level = authority.final_level
    if a_level < g_level:
        final, side = a_level, "authority"
    elif g_level < a_level:
        final, side = g_level, "gate"
    else:
        final, side = g_level, "gate+authority"
    return UnifiedRiskDecision(
        level=final,
        quorum=authority.quorum,
        winning_side=side,
        gate=gate_decision,
        authority=authority,
    )


__all__ = ["UnifiedRiskDecision", "combine", "gate_level"]
