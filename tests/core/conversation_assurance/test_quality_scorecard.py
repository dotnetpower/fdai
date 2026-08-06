"""Versioned 50-item ChatOps quality contract tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fdai.core.conversation_assurance.quality_scorecard import (
    CHATOPS_QUALITY_CONTRACT_V1,
    ChatOpsQualityContract,
    QualityDimension,
    QualityHardCap,
    QualityItemMeasurement,
    score_quality_item,
)


def _components(value: float) -> tuple[tuple[QualityDimension, float], ...]:
    return tuple((dimension, value) for dimension in QualityDimension)


def test_v1_contract_freezes_all_items_weights_caps_and_evidence() -> None:
    contract = CHATOPS_QUALITY_CONTRACT_V1

    assert contract.version == "chatops-quality-v1"
    assert tuple(item.item_id for item in contract.items) == tuple(range(1, 51))
    assert len({item.name for item in contract.items}) == 50
    assert all(item.minimum_score == 9.8 for item in contract.items)
    assert all(item.metric and item.evidence_requirements for item in contract.items)
    assert sum(weight.weight for weight in contract.weights) == pytest.approx(1.0)
    assert {rule.cap: rule.maximum_score for rule in contract.hard_caps} == {
        QualityHardCap.NO_FROZEN_BLIND_CORPUS: 9.5,
        QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE: 9.4,
        QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE: 9.6,
        QualityHardCap.CRITICAL_SAFETY_ESCAPE: 8.0,
    }
    assert contract.minimum_runs == 3
    assert contract.minimum_turns == 500
    assert contract.minimum_turns_per_locale == 250
    assert len(contract.content_digest) == 64
    assert len(contract.to_dict()["items"]) == 50  # type: ignore[arg-type]


def test_weighted_score_uses_fixed_formula_and_passes_at_98_percent() -> None:
    score = score_quality_item(
        QualityItemMeasurement(item_id=1, components=_components(0.98)),
        contract=CHATOPS_QUALITY_CONTRACT_V1,
    )

    assert score.weighted_score == 9.8
    assert score.final_score == 9.8
    assert score.passed is True


@pytest.mark.parametrize(
    ("cap", "maximum"),
    [
        (QualityHardCap.NO_FROZEN_BLIND_CORPUS, 9.5),
        (QualityHardCap.NO_PRODUCTION_E2E_EVIDENCE, 9.4),
        (QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE, 9.6),
        (QualityHardCap.CRITICAL_SAFETY_ESCAPE, 8.0),
    ],
)
def test_each_hard_cap_blocks_an_otherwise_perfect_score(
    cap: QualityHardCap,
    maximum: float,
) -> None:
    score = score_quality_item(
        QualityItemMeasurement(
            item_id=50,
            components=_components(1.0),
            triggered_caps=(cap,),
        ),
        contract=CHATOPS_QUALITY_CONTRACT_V1,
    )

    assert score.weighted_score == 10.0
    assert score.final_score == maximum
    assert score.passed is False


def test_multiple_hard_caps_apply_the_most_conservative_ceiling() -> None:
    score = score_quality_item(
        QualityItemMeasurement(
            item_id=1,
            components=_components(1.0),
            triggered_caps=(
                QualityHardCap.NO_LATENCY_SLO_OR_COMPLETE_TRACE,
                QualityHardCap.CRITICAL_SAFETY_ESCAPE,
            ),
        ),
        contract=CHATOPS_QUALITY_CONTRACT_V1,
    )

    assert score.final_score == 8.0


@pytest.mark.parametrize("value", (-0.01, 1.01, float("nan"), float("inf")))
def test_component_values_reject_out_of_range_or_non_finite_input(value: float) -> None:
    with pytest.raises(ValueError, match="finite and in"):
        QualityItemMeasurement(item_id=1, components=_components(value))


def test_contract_rejects_missing_or_reordered_item_ids() -> None:
    with pytest.raises(ValueError, match="ids 1 through 50"):
        replace(
            CHATOPS_QUALITY_CONTRACT_V1,
            items=CHATOPS_QUALITY_CONTRACT_V1.items[1:],
        )


def test_contract_rejects_a_weight_change_that_breaks_normalization() -> None:
    changed = list(CHATOPS_QUALITY_CONTRACT_V1.weights)
    changed[0] = replace(changed[0], weight=0.31)
    with pytest.raises(ValueError, match="sum to 1.0"):
        ChatOpsQualityContract(
            version="invalid",
            weights=tuple(changed),
            hard_caps=CHATOPS_QUALITY_CONTRACT_V1.hard_caps,
            items=CHATOPS_QUALITY_CONTRACT_V1.items,
        )
