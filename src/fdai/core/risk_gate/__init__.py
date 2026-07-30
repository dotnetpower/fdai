"""Risk scoring; auto vs HIL vs deny; enforces the four safety invariants.

Public exports (P2-D + P2-E):

- :class:`~fdai.core.risk_gate.gate.RiskGate` - orchestrator.
- :class:`~fdai.core.risk_gate.gate.RiskDecision` /
  :class:`~fdai.core.risk_gate.gate.RiskDecisionOutcome` - data types.
- :class:`~fdai.core.risk_gate.gate.RiskGateConfig` - thresholds.
- :class:`~fdai.core.risk_gate.gate.ActionPromotionRegistry` /
  :class:`~fdai.core.risk_gate.gate.ActionModeRecord` /
  :class:`~fdai.core.risk_gate.gate.PromotionMetrics` - shadow→enforce
  promotion registry (per-ActionType mode + measured provenance).
"""

from fdai.core.risk_gate.gate import (
    ActionModeRecord,
    ActionPromotionRegistry,
    PreconditionEvaluation,
    PromotionMetrics,
    RiskDecision,
    RiskDecisionOutcome,
    RiskGate,
    RiskGateConfig,
    duration_since,
)
from fdai.core.risk_gate.precedence import (
    CandidateAction,
    PrecedenceDecision,
    PrecedenceOutcome,
    PrecedenceResolver,
    Vertical,
)

__all__ = [
    "ActionModeRecord",
    "ActionPromotionRegistry",
    "CandidateAction",
    "PrecedenceDecision",
    "PrecedenceOutcome",
    "PrecedenceResolver",
    "PreconditionEvaluation",
    "PromotionMetrics",
    "RiskDecision",
    "RiskDecisionOutcome",
    "RiskGate",
    "RiskGateConfig",
    "Vertical",
    "duration_since",
]
