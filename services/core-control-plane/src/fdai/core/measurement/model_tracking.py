"""Per-model cost/quality tracker for T2 swap decisions.

Phase 4 § Model Cost/Quality Tracking. The T2 reasoner catalog is
compared **on the same scenario-set version and measurement window**;
swaps are proposed only when the challenger clears BOTH:

- a quality delta threshold (higher is better); AND
- a cost-per-verified-answer ceiling not worse than the incumbent.

Guard-metric breaches on the challenger (mixed-model disagreement
spike, verifier abstain-rate spike) prevent the swap even when quality
and cost both improved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ModelObservation:
    """A per-model measurement over a fixed scenario-set + window.

    `verifier_abstain_rate` and `mixed_model_disagreement_rate` are the
    two guard signals from the quality-gate delivered in P2 (see
    `core/quality_gate/gate.py`).
    """

    model_id: str
    scenario_set_version: str
    quality_score: float
    """Verified-correct share on the scenario set, in [0, 1]."""

    cost_per_verified_answer: float
    """Currency per verified-correct answer; lower is better."""

    verifier_abstain_rate: float
    mixed_model_disagreement_rate: float


class SwapOutcome(StrEnum):
    NO_CHANGE = "no_change"
    """Challenger did not beat the incumbent - keep the incumbent."""

    ADOPT_CHALLENGER = "adopt_challenger"
    """Challenger cleared BOTH thresholds without guard breach."""

    BLOCKED_GUARD_BREACH = "blocked_guard_breach"
    """Quality/cost improved but a guard metric regressed - hold."""


@dataclass(frozen=True, slots=True)
class SwapDecision:
    incumbent_model_id: str
    challenger_model_id: str
    outcome: SwapOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ModelSwapConfig:
    quality_gain_threshold: float = 0.02
    """Challenger MUST beat incumbent quality by at least this much."""

    max_abstain_rate: float = 0.15
    max_disagreement_rate: float = 0.20


class ModelSwapPolicy:
    """Compute :class:`SwapDecision` for one (incumbent, challenger) pair."""

    def __init__(self, *, config: ModelSwapConfig | None = None) -> None:
        cfg = config or ModelSwapConfig()
        if cfg.quality_gain_threshold < 0.0:
            raise ValueError("quality_gain_threshold MUST be >= 0")
        if not 0.0 <= cfg.max_abstain_rate <= 1.0:
            raise ValueError("max_abstain_rate MUST be in [0, 1]")
        if not 0.0 <= cfg.max_disagreement_rate <= 1.0:
            raise ValueError("max_disagreement_rate MUST be in [0, 1]")
        self._config = cfg

    def evaluate(
        self, *, incumbent: ModelObservation, challenger: ModelObservation
    ) -> SwapDecision:
        if incumbent.scenario_set_version != challenger.scenario_set_version:
            raise ValueError(
                "incumbent and challenger MUST share scenario_set_version - "
                f"got {incumbent.scenario_set_version} vs "
                f"{challenger.scenario_set_version}"
            )

        reasons: list[str] = []

        quality_delta = challenger.quality_score - incumbent.quality_score
        beats_quality = quality_delta >= self._config.quality_gain_threshold
        beats_cost = challenger.cost_per_verified_answer <= incumbent.cost_per_verified_answer

        guard_ok = True
        if challenger.verifier_abstain_rate > self._config.max_abstain_rate:
            guard_ok = False
            reasons.append(
                f"abstain_rate={challenger.verifier_abstain_rate}"
                f">max={self._config.max_abstain_rate}"
            )
        if challenger.mixed_model_disagreement_rate > self._config.max_disagreement_rate:
            guard_ok = False
            reasons.append(
                f"disagreement_rate={challenger.mixed_model_disagreement_rate}"
                f">max={self._config.max_disagreement_rate}"
            )

        if beats_quality and beats_cost and not guard_ok:
            return SwapDecision(
                incumbent_model_id=incumbent.model_id,
                challenger_model_id=challenger.model_id,
                outcome=SwapOutcome.BLOCKED_GUARD_BREACH,
                reasons=tuple(reasons),
            )
        if beats_quality and beats_cost and guard_ok:
            reasons.append(f"quality_delta={quality_delta:.4f}")
            return SwapDecision(
                incumbent_model_id=incumbent.model_id,
                challenger_model_id=challenger.model_id,
                outcome=SwapOutcome.ADOPT_CHALLENGER,
                reasons=tuple(reasons),
            )
        if not beats_quality:
            reasons.append(
                f"quality_delta={quality_delta:.4f}<threshold={self._config.quality_gain_threshold}"
            )
        if not beats_cost:
            reasons.append(
                f"cost_per_verified={challenger.cost_per_verified_answer}"
                f">incumbent={incumbent.cost_per_verified_answer}"
            )
        return SwapDecision(
            incumbent_model_id=incumbent.model_id,
            challenger_model_id=challenger.model_id,
            outcome=SwapOutcome.NO_CHANGE,
            reasons=tuple(reasons),
        )


__all__ = [
    "ModelObservation",
    "ModelSwapConfig",
    "ModelSwapPolicy",
    "SwapDecision",
    "SwapOutcome",
]
