"""Risk scoring and eligibility for seven-safeguard execution.

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
    OperationalPromotionReceiptVerifier,
    PersistedPromotionAuthorityVerifier,
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
from fdai.core.risk_gate.preconditions import (
    EventPreconditionEvaluator,
    PreconditionEvaluation,
    PreconditionEvaluator,
)

__all__ = [
    "ActionModeRecord",
    "ActionPromotionRegistry",
    "CandidateAction",
    "EventPreconditionEvaluator",
    "OperationalPromotionReceiptVerifier",
    "PersistedPromotionAuthorityVerifier",
    "PrecedenceDecision",
    "PrecedenceOutcome",
    "PrecedenceResolver",
    "PreconditionEvaluation",
    "PreconditionEvaluator",
    "PromotionMetrics",
    "RiskDecision",
    "RiskDecisionOutcome",
    "RiskGate",
    "RiskGateConfig",
    "Vertical",
    "duration_since",
]
