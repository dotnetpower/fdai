"""Automatic promotion and rollback for chat-only policy variants."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class ChatPolicyTarget(StrEnum):
    NARRATOR_PROMPT = "narrator_prompt"
    GLOSSARY = "glossary"
    READ_ROUTING = "read_routing"
    EVIDENCE_SELECTION = "evidence_selection"
    RESPONSE_RENDERING = "response_rendering"
    NARRATOR_MODEL_ORDER = "narrator_model_order"


class PolicyStage(StrEnum):
    SHADOW = "shadow"
    CANARY_1 = "canary_1"
    CANARY_5 = "canary_5"
    CANARY_25 = "canary_25"
    ACTIVE = "active"
    ROLLED_BACK = "rolled_back"


_NEXT_STAGE = {
    PolicyStage.SHADOW: PolicyStage.CANARY_1,
    PolicyStage.CANARY_1: PolicyStage.CANARY_5,
    PolicyStage.CANARY_5: PolicyStage.CANARY_25,
    PolicyStage.CANARY_25: PolicyStage.ACTIVE,
}


@dataclass(frozen=True, slots=True)
class ChatPolicyCandidate:
    candidate_id: str
    principal_scope: str
    cluster_id: str
    target: ChatPolicyTarget
    policy_digest: str
    incumbent_policy_digest: str
    stage: PolicyStage = PolicyStage.SHADOW

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.principal_scope.strip():
            raise ValueError("policy candidate identity and principal_scope MUST be non-empty")
        if not self.cluster_id.strip():
            raise ValueError("policy candidate cluster_id MUST be non-empty")
        if len(self.policy_digest) != 64 or len(self.incumbent_policy_digest) != 64:
            raise ValueError("policy candidate digests MUST be 64 characters")


@dataclass(frozen=True, slots=True)
class PolicyTrialMetrics:
    sample_count: int
    score_delta_lcb95: float
    hard_failure_escapes: int
    candidate_cost_per_verified_microusd: float
    incumbent_cost_per_verified_microusd: float
    latency_delta_ms: float
    locale_gap_delta: float
    disagreement_rate_delta: float

    def __post_init__(self) -> None:
        numeric = (
            self.score_delta_lcb95,
            self.candidate_cost_per_verified_microusd,
            self.incumbent_cost_per_verified_microusd,
            self.latency_delta_ms,
            self.locale_gap_delta,
            self.disagreement_rate_delta,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("policy trial metrics MUST be finite")
        if self.sample_count < 0 or self.hard_failure_escapes < 0:
            raise ValueError("policy trial counts MUST be non-negative")


@dataclass(frozen=True, slots=True)
class PromotionConfig:
    min_samples: int = 100
    min_score_delta_lcb95: float = 0.0
    max_latency_delta_ms: float = 250.0
    max_locale_gap_delta: float = 0.02
    max_disagreement_rate_delta: float = 0.02


@dataclass(frozen=True, slots=True)
class PolicyTransition:
    candidate_id: str
    from_stage: PolicyStage
    to_stage: PolicyStage
    reasons: tuple[str, ...]


def evaluate_policy_transition(
    candidate: ChatPolicyCandidate,
    metrics: PolicyTrialMetrics,
    *,
    config: PromotionConfig | None = None,
) -> PolicyTransition:
    """Advance one stage or automatically roll back on a guard breach."""

    cfg = config or PromotionConfig()
    if candidate.stage in {PolicyStage.ACTIVE, PolicyStage.ROLLED_BACK}:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("terminal_stage",),
        )
    guard_reasons: list[str] = []
    if metrics.hard_failure_escapes:
        guard_reasons.append("hard_failure_escape")
    if metrics.score_delta_lcb95 < cfg.min_score_delta_lcb95:
        guard_reasons.append("score_regression")
    if metrics.candidate_cost_per_verified_microusd > metrics.incumbent_cost_per_verified_microusd:
        guard_reasons.append("cost_regression")
    if metrics.latency_delta_ms > cfg.max_latency_delta_ms:
        guard_reasons.append("latency_regression")
    if metrics.locale_gap_delta > cfg.max_locale_gap_delta:
        guard_reasons.append("locale_disparity")
    if metrics.disagreement_rate_delta > cfg.max_disagreement_rate_delta:
        guard_reasons.append("disagreement_regression")
    if guard_reasons:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            PolicyStage.ROLLED_BACK,
            tuple(guard_reasons),
        )
    if metrics.sample_count < cfg.min_samples:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("insufficient_samples",),
        )
    return PolicyTransition(
        candidate.candidate_id,
        candidate.stage,
        _NEXT_STAGE[candidate.stage],
        ("promotion_guards_passed",),
    )


__all__ = [
    "ChatPolicyCandidate",
    "ChatPolicyTarget",
    "PolicyStage",
    "PolicyTransition",
    "PolicyTrialMetrics",
    "PromotionConfig",
    "evaluate_policy_transition",
]
