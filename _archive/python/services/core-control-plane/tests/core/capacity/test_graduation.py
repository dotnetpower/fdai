from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.capacity import (
    CapacityGraduationController,
    CapacityGraduationEvidence,
    CapacityTransition,
    GraduationRecommendationStatus,
)
from fdai.rule_catalog.schema.capacity_graduation_policy import (
    load_capacity_graduation_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
NOW = datetime(2026, 8, 30, 3, tzinfo=UTC)


def _controller() -> CapacityGraduationController:
    policy = load_capacity_graduation_policy(
        REPO_ROOT / "rule-catalog" / "capacity-graduation-policy.yaml"
    )
    return CapacityGraduationController(policy)


def _evidence(
    transition: CapacityTransition,
    **changes: object,
) -> CapacityGraduationEvidence:
    values: dict[str, object] = {
        "transition": transition,
        "target_ref": "resource:example",
        "correlation_id": "correlation:example",
        "observed_at": NOW,
        "source_authority_ref": "measurement:capacity",
        "evidence_refs": ("evidence:capacity",),
        "complete": True,
        "synthetic": False,
        "projected_cost_ratio": 1.0,
        "cost_evidence_ref": "evidence:cost",
        "cost_observed_at": NOW,
    }
    values.update(changes)
    return CapacityGraduationEvidence.model_validate(values)


@pytest.mark.parametrize(
    ("transition", "metrics"),
    (
        (
            CapacityTransition.SCALE_TO_ZERO,
            {
                "zero_lag_ratio": 0.7,
                "cold_start_count": 100,
                "observation_days": 7,
                "cold_start_budget_ratio": 1.0,
                "delivery_violations": 0,
            },
        ),
        (
            CapacityTransition.DEDICATED_VECTOR_STORE,
            {"capacity_ratio": 0.6},
        ),
        (
            CapacityTransition.AKS_OR_CELL,
            {"required_capabilities": ("gpu",)},
        ),
        (
            CapacityTransition.NON_AZURE_PROVIDER,
            {"contract_count": 8, "shadow_campaigns": 1, "policy_escapes": 0},
        ),
    ),
)
def test_recommends_each_transition_only_from_complete_evidence(
    transition: CapacityTransition,
    metrics: dict[str, object],
) -> None:
    recommendation = _controller().evaluate(
        _evidence(transition, **metrics),
        evaluated_at=NOW,
    )

    assert recommendation.status is GraduationRecommendationStatus.RECOMMEND
    assert recommendation.reason_codes == ("graduation_thresholds_satisfied",)
    assert recommendation.producer_principal == "Freyr"
    assert recommendation.shadow_only is True
    assert recommendation.execution_authority is False


def test_stale_cost_evidence_holds() -> None:
    evidence = _evidence(
        CapacityTransition.DEDICATED_VECTOR_STORE,
        capacity_ratio=0.8,
        projected_cost_ratio=1.3,
        cost_observed_at=NOW - timedelta(hours=2),
    )

    recommendation = _controller().evaluate(evidence, evaluated_at=NOW)

    assert recommendation.status is GraduationRecommendationStatus.HOLD
    assert recommendation.reason_codes == ("cost_evidence_stale",)


def test_synthetic_incomplete_evidence_never_recommends() -> None:
    evidence = _evidence(
        CapacityTransition.AKS_OR_CELL,
        required_capabilities=("gpu",),
        complete=False,
        synthetic=True,
    )

    recommendation = _controller().evaluate(evidence, evaluated_at=NOW)

    assert recommendation.status is GraduationRecommendationStatus.HOLD
    assert recommendation.reason_codes == ("evidence_incomplete", "evidence_synthetic")


def test_replay_identity_changes_with_evidence_or_time() -> None:
    controller = _controller()
    evidence = _evidence(
        CapacityTransition.NON_AZURE_PROVIDER,
        contract_count=8,
        shadow_campaigns=1,
        policy_escapes=0,
    )

    first = controller.evaluate(evidence, evaluated_at=NOW)
    replay = controller.evaluate(evidence, evaluated_at=NOW)
    later = controller.evaluate(evidence, evaluated_at=NOW + timedelta(seconds=1))

    assert replay == first
    assert later.id != first.id
