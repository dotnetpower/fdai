"""Model swap policy outcomes."""

from __future__ import annotations

import pytest
from fdai.core.measurement.model_tracking import (
    ModelObservation,
    ModelSwapConfig,
    ModelSwapPolicy,
    SwapOutcome,
)


def _obs(
    model_id: str,
    *,
    quality: float,
    cost: float,
    abstain: float = 0.05,
    disagreement: float = 0.05,
    version: str = "v2026.07",
) -> ModelObservation:
    return ModelObservation(
        model_id=model_id,
        scenario_set_version=version,
        quality_score=quality,
        cost_per_verified_answer=cost,
        verifier_abstain_rate=abstain,
        mixed_model_disagreement_rate=disagreement,
    )


def test_config_rejects_negative_quality_gain() -> None:
    with pytest.raises(ValueError, match="quality_gain_threshold"):
        ModelSwapPolicy(config=ModelSwapConfig(quality_gain_threshold=-0.01))


def test_config_rejects_out_of_range_abstain() -> None:
    with pytest.raises(ValueError, match="max_abstain_rate"):
        ModelSwapPolicy(config=ModelSwapConfig(max_abstain_rate=1.5))


def test_config_rejects_out_of_range_disagreement() -> None:
    with pytest.raises(ValueError, match="max_disagreement_rate"):
        ModelSwapPolicy(config=ModelSwapConfig(max_disagreement_rate=-0.1))


def test_scenario_version_mismatch_is_hard_error() -> None:
    policy = ModelSwapPolicy()
    with pytest.raises(ValueError, match="scenario_set_version"):
        policy.evaluate(
            incumbent=_obs("m-a", quality=0.7, cost=1.0, version="v1"),
            challenger=_obs("m-b", quality=0.8, cost=0.9, version="v2"),
        )


def test_adopt_challenger_when_quality_and_cost_beat_incumbent() -> None:
    policy = ModelSwapPolicy()
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.80, cost=0.8),
    )
    assert decision.outcome is SwapOutcome.ADOPT_CHALLENGER
    assert any("quality_delta=" in r for r in decision.reasons)


def test_no_change_when_quality_gain_below_threshold() -> None:
    policy = ModelSwapPolicy(config=ModelSwapConfig(quality_gain_threshold=0.05))
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.72, cost=0.5),  # only +0.02
    )
    assert decision.outcome is SwapOutcome.NO_CHANGE
    assert any("quality_delta=0.0200" in r for r in decision.reasons)


def test_no_change_when_cost_worse_even_if_quality_beats() -> None:
    policy = ModelSwapPolicy()
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.85, cost=1.5),
    )
    assert decision.outcome is SwapOutcome.NO_CHANGE
    assert any("cost_per_verified" in r for r in decision.reasons)


def test_blocked_when_guards_regress_despite_quality_and_cost_gain() -> None:
    policy = ModelSwapPolicy()
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.85, cost=0.8, abstain=0.3, disagreement=0.05),
    )
    assert decision.outcome is SwapOutcome.BLOCKED_GUARD_BREACH
    assert any("abstain_rate=" in r for r in decision.reasons)


def test_blocked_when_disagreement_rate_regresses() -> None:
    policy = ModelSwapPolicy()
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.85, cost=0.8, abstain=0.05, disagreement=0.5),
    )
    assert decision.outcome is SwapOutcome.BLOCKED_GUARD_BREACH
    assert any("disagreement_rate=" in r for r in decision.reasons)


def test_equal_cost_still_counts_as_beats() -> None:
    """Equal cost is accepted as 'not worse' - only strictly higher blocks."""
    policy = ModelSwapPolicy()
    decision = policy.evaluate(
        incumbent=_obs("m-a", quality=0.70, cost=1.0),
        challenger=_obs("m-b", quality=0.80, cost=1.0),
    )
    assert decision.outcome is SwapOutcome.ADOPT_CHALLENGER
