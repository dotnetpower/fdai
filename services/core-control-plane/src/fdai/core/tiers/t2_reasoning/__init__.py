"""Frontier-model reasoning for novel or ambiguous cases only.

Output MUST pass the quality gate before it can execute. The tier is a small
orchestrator over the :class:`T2Proposer` seam and the existing
:class:`~fdai.core.quality_gate.gate.QualityGate`; see :mod:`.tier`.
"""

from __future__ import annotations

from fdai.core.tiers.t2_reasoning.recovery import (
    BoundedFailoverT2Proposer,
    T2AttemptReceipt,
    T2FailureClass,
    T2ProposerBudgetExhaustedError,
    T2ProposerCandidatesExhaustedError,
    T2RecoveryObserver,
)
from fdai.core.tiers.t2_reasoning.tier import (
    QualityGateProtocol,
    T2Decision,
    T2Outcome,
    T2ProposalContext,
    T2Proposer,
    T2Tier,
)

__all__ = [
    "BoundedFailoverT2Proposer",
    "QualityGateProtocol",
    "T2AttemptReceipt",
    "T2Decision",
    "T2FailureClass",
    "T2Outcome",
    "T2ProposalContext",
    "T2Proposer",
    "T2ProposerBudgetExhaustedError",
    "T2ProposerCandidatesExhaustedError",
    "T2RecoveryObserver",
    "T2Tier",
]
