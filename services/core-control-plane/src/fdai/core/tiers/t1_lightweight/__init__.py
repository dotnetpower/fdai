"""Embedding similarity, learned-action reuse, small-model classification of routine cases.

Public exports (P2-C):

- :class:`~fdai.core.tiers.t1_lightweight.tier.T1Tier` - orchestrator.
- :class:`~fdai.core.tiers.t1_lightweight.tier.T1Config` /
  :class:`~fdai.core.tiers.t1_lightweight.tier.T1Decision` /
  :class:`~fdai.core.tiers.t1_lightweight.tier.T1Outcome` - data types.
- :class:`~fdai.core.tiers.t1_lightweight.tier.LearnedAction` /
  :class:`~fdai.core.tiers.t1_lightweight.tier.SimilarityMatch` - records.
- :class:`~fdai.core.tiers.t1_lightweight.tier.EmbeddingModel` /
  :class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary` - DI seams.
"""

from fdai.core.tiers.t1_lightweight.contextual_reuse import (
    CurrentReuseVerification,
    CurrentReuseVerifier,
    OperationalCaseContext,
)
from fdai.core.tiers.t1_lightweight.tier import (
    EmbeddingModel,
    LearnedAction,
    PatternLibrary,
    SimilarityMatch,
    T1Config,
    T1Decision,
    T1Outcome,
    T1Tier,
    cosine_similarity,
)

__all__ = [
    "EmbeddingModel",
    "CurrentReuseVerifier",
    "CurrentReuseVerification",
    "LearnedAction",
    "OperationalCaseContext",
    "PatternLibrary",
    "SimilarityMatch",
    "T1Config",
    "T1Decision",
    "T1Outcome",
    "T1Tier",
    "cosine_similarity",
]
