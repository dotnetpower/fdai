"""Mixed-model cross-check, deterministic verifier, and RAG grounding. Guards T2 output.

Public exports (P2-B):

- :class:`~aiopspilot.core.quality_gate.gate.QualityGate` — orchestrator.
- :class:`~aiopspilot.core.quality_gate.gate.QualityCandidate` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityDecision` /
  :class:`~aiopspilot.core.quality_gate.gate.QualityOutcome` — data types.
- :class:`~aiopspilot.core.quality_gate.gate.QualityGateConfig` — thresholds.
- :class:`~aiopspilot.core.quality_gate.gate.CrossCheckModel` /
  :class:`~aiopspilot.core.quality_gate.gate.VerifierPolicy` /
  :class:`~aiopspilot.core.quality_gate.gate.GroundingSource` — DI seams.
- :class:`~aiopspilot.core.quality_gate.rule_based.RuleBasedVerifier` —
  the first non-fake :class:`VerifierPolicy`; denies any candidate
  ``action_type`` no cited rule authorizes on the target resource type.
- :class:`~aiopspilot.core.quality_gate.rag_grounding.RagGroundingSource` —
  the first non-fake :class:`GroundingSource`; checks each citation is
  topically relevant to the candidate via an injected
  :class:`~aiopspilot.core.quality_gate.rag_grounding.RuleEmbeddingIndex`.
"""

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
from aiopspilot.core.quality_gate.rag_grounding import (
    RagGroundingSource,
    RuleEmbeddingIndex,
)
from aiopspilot.core.quality_gate.rule_based import RuleBasedVerifier

__all__ = [
    "CrossCheckModel",
    "GroundingSource",
    "QualityCandidate",
    "QualityDecision",
    "QualityGate",
    "QualityGateConfig",
    "QualityOutcome",
    "RagGroundingSource",
    "RuleBasedVerifier",
    "RuleEmbeddingIndex",
    "VerifierPolicy",
]
