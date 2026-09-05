"""Automatic promotion and rollback for chat-only policy variants."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)

CHAT_POLICY_PROMOTION_EVIDENCE_PURPOSE = "chat-policy-promotion"


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
    policy_text: str | None = None
    stage: PolicyStage = PolicyStage.SHADOW

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.principal_scope.strip():
            raise ValueError("policy candidate identity and principal_scope MUST be non-empty")
        if not self.cluster_id.strip():
            raise ValueError("policy candidate cluster_id MUST be non-empty")
        if len(self.policy_digest) != 64 or len(self.incumbent_policy_digest) != 64:
            raise ValueError("policy candidate digests MUST be 64 characters")
        if self.policy_text is not None:
            if not self.policy_text.strip() or len(self.policy_text) > 2_000:
                raise ValueError("policy artifact text MUST contain 1..2000 characters")
            digest = hashlib.sha256(self.policy_text.encode()).hexdigest()
            if digest != self.policy_digest:
                raise ValueError("policy artifact text MUST match policy_digest")


@dataclass(frozen=True, slots=True)
class PolicyTrialMetrics:
    observed_stage: PolicyStage
    evidence_digest: str
    sample_count: int
    score_delta_lcb95: float
    hard_failure_escapes: int
    candidate_cost_per_verified_microusd: float
    incumbent_cost_per_verified_microusd: float
    latency_delta_ms: float
    locale_gap_delta: float
    disagreement_rate_delta: float
    measured_at: datetime
    decision_evidence: DecisionEvidenceAdmission | None = None

    def __post_init__(self) -> None:
        _require_digest("policy trial evidence_digest", self.evidence_digest)
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
        if (
            self.candidate_cost_per_verified_microusd < 0
            or self.incumbent_cost_per_verified_microusd < 0
        ):
            raise ValueError("policy trial costs MUST be non-negative")
        if self.measured_at.tzinfo is None or self.measured_at.utcoffset() is None:
            raise ValueError("policy trial measured_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class PromotionConfig:
    min_samples: int = 100
    min_score_delta_lcb95: float = 0.01
    max_latency_delta_ms: float = 250.0
    max_locale_gap_delta: float = 0.02
    max_disagreement_rate_delta: float = 0.02

    def __post_init__(self) -> None:
        numeric = (
            self.min_score_delta_lcb95,
            self.max_latency_delta_ms,
            self.max_locale_gap_delta,
            self.max_disagreement_rate_delta,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("promotion thresholds MUST be finite")
        if self.min_samples < 1:
            raise ValueError("promotion min_samples MUST be positive")
        if self.min_score_delta_lcb95 <= 0:
            raise ValueError("promotion score gain MUST be positive")
        if self.max_latency_delta_ms < 0:
            raise ValueError("promotion latency tolerance MUST be non-negative")
        if not 0 <= self.max_locale_gap_delta <= 1:
            raise ValueError("promotion locale gap tolerance MUST be in [0, 1]")
        if not 0 <= self.max_disagreement_rate_delta <= 1:
            raise ValueError("promotion disagreement tolerance MUST be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PolicyTransition:
    candidate_id: str
    from_stage: PolicyStage
    to_stage: PolicyStage
    reasons: tuple[str, ...]
    evidence_digest: str
    decision_evidence_receipt_digest: str | None = None
    decision_evidence_verification_bundle_digest: str | None = None

    def __post_init__(self) -> None:
        _require_digest("policy transition evidence_digest", self.evidence_digest)
        if not self.reasons or any(not reason.strip() for reason in self.reasons):
            raise ValueError("policy transition reasons MUST be non-empty")
        allowed = {self.from_stage, PolicyStage.ROLLED_BACK}
        next_stage = _NEXT_STAGE.get(self.from_stage)
        if next_stage is not None:
            allowed.add(next_stage)
        if self.to_stage not in allowed:
            raise ValueError("policy transition MUST follow the staged promotion graph")


def evaluate_policy_transition(
    candidate: ChatPolicyCandidate,
    metrics: PolicyTrialMetrics,
    *,
    config: PromotionConfig | None = None,
) -> PolicyTransition:
    """Advance one stage or automatically roll back on a guard breach."""

    cfg = config or PromotionConfig()
    if metrics.observed_stage is not candidate.stage:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("measurement_stage_mismatch",),
            metrics.evidence_digest,
        )
    if candidate.stage in {PolicyStage.ACTIVE, PolicyStage.ROLLED_BACK}:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("terminal_stage",),
            metrics.evidence_digest,
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
            metrics.evidence_digest,
        )
    if metrics.sample_count < cfg.min_samples:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("insufficient_samples",),
            metrics.evidence_digest,
        )
    if metrics.decision_evidence is None:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            ("decision_evidence_admission_missing",),
            metrics.evidence_digest,
        )
    reasons = assess_decision_evidence_admission(
        metrics.decision_evidence,
        expected_evidence_digest=f"sha256:{metrics.evidence_digest}",
        expected_scope_digest=chat_policy_promotion_scope_digest(candidate),
        expected_purpose_id=CHAT_POLICY_PROMOTION_EVIDENCE_PURPOSE,
        expected_source_revision=candidate.policy_digest,
        evaluated_at=metrics.measured_at,
    )
    if reasons:
        return PolicyTransition(
            candidate.candidate_id,
            candidate.stage,
            candidate.stage,
            tuple(f"decision_evidence_{reason.value}" for reason in reasons),
            metrics.evidence_digest,
            metrics.decision_evidence.receipt_digest,
            metrics.decision_evidence.verification_bundle_digest,
        )
    return PolicyTransition(
        candidate.candidate_id,
        candidate.stage,
        _NEXT_STAGE[candidate.stage],
        ("promotion_guards_passed",),
        metrics.evidence_digest,
        metrics.decision_evidence.receipt_digest,
        metrics.decision_evidence.verification_bundle_digest,
    )


def chat_policy_promotion_scope_digest(candidate: ChatPolicyCandidate) -> str:
    """Return the exact principal, cluster, target, and policy promotion scope."""

    return content_digest(
        {
            "candidate_id": candidate.candidate_id,
            "cluster_id": candidate.cluster_id,
            "policy_digest": candidate.policy_digest,
            "principal_scope": candidate.principal_scope,
            "target": candidate.target.value,
        }
    )


def _require_digest(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} MUST be a lowercase SHA-256 digest")


__all__ = [
    "CHAT_POLICY_PROMOTION_EVIDENCE_PURPOSE",
    "ChatPolicyCandidate",
    "ChatPolicyTarget",
    "PolicyStage",
    "PolicyTransition",
    "PolicyTrialMetrics",
    "PromotionConfig",
    "chat_policy_promotion_scope_digest",
    "evaluate_policy_transition",
]
