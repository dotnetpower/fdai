"""Mixed-model cross-check, deterministic verifier, and RAG grounding. Guards T2 output.

Public exports (P2-B):

- :class:`~aiopspilot.core.quality_gate.gate.QualityGate` - orchestrator.
- :class:`~aiopspilot.core.quality_gate.gate.QualityCandidate` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityDecision` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityOutcome` - data types.
- :class:`~aiopspilot.core.quality_gate.gate.QualityGateConfig` - thresholds.
- :class:`~aiopspilot.core.quality_gate.gate.CrossCheckModel` /
  :class:`~aiopspilot.core.quality_gate.gate.VerifierPolicy` /
  :class:`~aiopspilot.core.quality_gate.gate.GroundingSource` - DI seams.
- :class:`~aiopspilot.core.quality_gate.rule_based.RuleBasedVerifier` -
  the first non-fake :class:`VerifierPolicy`; denies any candidate
  ``action_type`` no cited rule authorizes on the target resource type.
- :class:`~aiopspilot.core.quality_gate.rag_grounding.RagGroundingSource` -
  the first non-fake :class:`GroundingSource`; checks each citation is
  topically relevant to the candidate via an injected
  :class:`~aiopspilot.core.quality_gate.rag_grounding.RuleEmbeddingIndex`.
"""

from aiopspilot.core.quality_gate.critic import (
    CriticModel,
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
    CriticVerdict,
    evaluate_critic_output,
)
from aiopspilot.core.quality_gate.debate import (
    DebateOrchestrator,
    DebateOrchestratorConfig,
    DebateOutcome,
    DebateVerdict,
    ProposerRetry,
)
from aiopspilot.core.quality_gate.debate_router import (
    DebateRoute,
    DebateRouterConfig,
    DebateRoutingDecision,
    decide_debate_route,
)
from aiopspilot.core.quality_gate.gate import (
    CrossCheckModel,
    GroundingSource,
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
    VerifierPolicy,
)
from aiopspilot.core.quality_gate.judge import (
    JudgeDecision,
    JudgeModel,
    JudgeOutput,
    JudgeVerdict,
    evaluate_judge_output,
)
from aiopspilot.core.quality_gate.rag_grounding import (
    RagGroundingSource,
    RuleEmbeddingIndex,
)
from aiopspilot.core.quality_gate.rule_based import RuleBasedVerifier

__all__ = [
    "CriticModel",
    "CriticObjection",
    "CriticOutput",
    "CriticSeverity",
    "CriticStance",
    "CriticVerdict",
    "CrossCheckModel",
    "DebateOrchestrator",
    "DebateOrchestratorConfig",
    "DebateOutcome",
    "DebateRoute",
    "DebateRouterConfig",
    "DebateRoutingDecision",
    "DebateVerdict",
    "GroundingSource",
    "JudgeDecision",
    "JudgeModel",
    "JudgeOutput",
    "JudgeVerdict",
    "ProposerRetry",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "RagGroundingSource",
    "RuleBasedVerifier",
    "RuleEmbeddingIndex",
    "VerifierPolicy",
    "decide_debate_route",
    "evaluate_critic_output",
    "evaluate_judge_output",
]
