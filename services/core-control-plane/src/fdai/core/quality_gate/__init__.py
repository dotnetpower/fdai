"""Mixed-model cross-check, deterministic verifier, and RAG grounding. Guards T2 output.

Public exports (P2-B):

- :class:`~fdai.core.quality_gate.gate.QualityGate` - orchestrator.
- :class:`~fdai.core.quality_gate.gate.QualityCandidate` /
  :class:`~fdai.core.quality_gate.gate.QualityDecision` /
  :class:`~fdai.core.quality_gate.gate.QualityOutcome` - data types.
- :class:`~fdai.core.quality_gate.gate.QualityGateConfig` - thresholds.
- :class:`~fdai.core.quality_gate.gate.CrossCheckModel` /
  :class:`~fdai.core.quality_gate.gate.VerifierPolicy` /
  :class:`~fdai.core.quality_gate.gate.GroundingSource` - DI seams.
- :class:`~fdai.core.quality_gate.rule_based.RuleBasedVerifier` -
  the first non-fake :class:`VerifierPolicy`; denies any candidate
  ``action_type`` no cited rule authorizes on the target resource type.
- :class:`~fdai.core.quality_gate.rag_grounding.RagGroundingSource` -
  the first non-fake :class:`GroundingSource`; checks each citation is
  topically relevant to the candidate via an injected
  :class:`~fdai.core.quality_gate.rag_grounding.RuleEmbeddingIndex`.
- :class:`~fdai.core.quality_gate.rubric.RubricEvaluator` +
  :func:`~fdai.core.quality_gate.rubric.evaluate_rubric_output` - the
  subtractive hallucination filter; a judge scores the candidate's
  ``reasoning_trace`` against fixed criteria and the gate folds the
  minimum score into confidence via ``min()`` (never additive).
"""

from fdai.core.quality_gate.critic import (
    CriticModel,
    CriticObjection,
    CriticOutput,
    CriticSeverity,
    CriticStance,
    CriticVerdict,
    evaluate_critic_output,
)
from fdai.core.quality_gate.debate import (
    DebateOrchestrator,
    DebateOrchestratorConfig,
    DebateOutcome,
    DebateVerdict,
    ProposerRetry,
)
from fdai.core.quality_gate.debate_router import (
    DebateRoute,
    DebateRouterConfig,
    DebateRoutingDecision,
    decide_debate_route,
)
from fdai.core.quality_gate.escalation_ladder import (
    EscalationDecision,
    EscalationLadderConfig,
    EscalationRoute,
    EscalationTier,
    decide_escalation,
    escalation_decision_audit_fields,
)
from fdai.core.quality_gate.gate import (
    CrossCheckModel,
    CrossCheckProposal,
    GroundingSource,
    ModelVote,
    PromptEvidenceCrossCheckModel,
    QualityCandidate,
    QualityDecision,
    QualityGate,
    QualityGateConfig,
    QualityOutcome,
    VerifierPolicy,
    quality_decision_audit_fields,
)
from fdai.core.quality_gate.judge import (
    JudgeDecision,
    JudgeModel,
    JudgeOutput,
    JudgeVerdict,
    evaluate_judge_output,
)
from fdai.core.quality_gate.rag_grounding import (
    HashedRuleEmbeddingIndex,
    RagGroundingSource,
    RuleEmbeddingIndex,
)
from fdai.core.quality_gate.rubric import (
    RubricCriterion,
    RubricDecision,
    RubricEvaluator,
    RubricOutput,
    RubricScore,
    RubricVerdict,
    evaluate_rubric_output,
)
from fdai.core.quality_gate.rule_based import RuleBasedVerifier
from fdai.core.quality_gate.self_consistency import (
    STABILITY_SIGNAL_KEY,
    CascadeDecision,
    SelfConsistencyResult,
    SelfConsistencySampler,
    compute_stability,
    run_consistency_cascade,
)

__all__ = [
    "CriticModel",
    "CriticObjection",
    "CriticOutput",
    "CriticSeverity",
    "CriticStance",
    "CriticVerdict",
    "CrossCheckModel",
    "CrossCheckProposal",
    "DebateOrchestrator",
    "DebateOrchestratorConfig",
    "DebateOutcome",
    "DebateRoute",
    "DebateRouterConfig",
    "DebateRoutingDecision",
    "DebateVerdict",
    "EscalationDecision",
    "EscalationLadderConfig",
    "EscalationRoute",
    "EscalationTier",
    "GroundingSource",
    "HashedRuleEmbeddingIndex",
    "JudgeDecision",
    "JudgeModel",
    "JudgeOutput",
    "JudgeVerdict",
    "ModelVote",
    "PromptEvidenceCrossCheckModel",
    "ProposerRetry",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "RagGroundingSource",
    "RubricCriterion",
    "RubricDecision",
    "RubricEvaluator",
    "RubricOutput",
    "RubricScore",
    "RubricVerdict",
    "RuleBasedVerifier",
    "RuleEmbeddingIndex",
    "STABILITY_SIGNAL_KEY",
    "CascadeDecision",
    "SelfConsistencyResult",
    "SelfConsistencySampler",
    "VerifierPolicy",
    "compute_stability",
    "decide_debate_route",
    "decide_escalation",
    "evaluate_critic_output",
    "evaluate_judge_output",
    "evaluate_rubric_output",
    "escalation_decision_audit_fields",
    "quality_decision_audit_fields",
    "run_consistency_cascade",
]
