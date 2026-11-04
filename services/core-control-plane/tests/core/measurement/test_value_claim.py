from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fdai.core.measurement.value_claim import (
    CohortRole,
    ObservationLane,
    ValueClaimDeclaration,
    ValueClaimStatus,
    ValueCohortObservation,
    ValueDirection,
    ValueUnit,
    settle_value_claim,
)
from pydantic import ValidationError

_START = datetime(2026, 10, 1, tzinfo=UTC)
_END = datetime(2026, 10, 15, tzinfo=UTC)
_AFTER = datetime(2026, 10, 16, tzinfo=UTC)


def _declaration(**overrides: object) -> ValueClaimDeclaration:
    values: dict[str, object] = {
        "claim_id": "claim-1",
        "workflow_ref": "predictive-scale",
        "workflow_version": "1.0.0",
        "objective_ref": "objective-1",
        "metric_name": "mttr",
        "unit": ValueUnit.DURATION_SECONDS,
        "direction": ValueDirection.DECREASE_IS_BETTER,
        "scenario_set_version": "set-1",
        "window_start": _START,
        "window_end": _END,
        "min_samples_per_cohort": 5,
    }
    values.update(overrides)
    return ValueClaimDeclaration.model_validate(values)


def _cohort(role: CohortRole, samples: list[str], **overrides: object) -> ValueCohortObservation:
    values: dict[str, object] = {
        "role": role,
        "lane": ObservationLane.INDEPENDENT_OBSERVATION,
        "scenario_set_version": "set-1",
        "complete": True,
        "samples": tuple(Decimal(item) for item in samples),
        "evidence_refs": (f"evidence:{role.value}",),
        "observed_at": _AFTER,
    }
    values.update(overrides)
    return ValueCohortObservation.model_validate(values)


_BASELINE = ["600", "620", "580", "610", "590", "605"]
_FASTER = ["300", "310", "290", "305", "295", "300"]


def test_clear_improvement_reports_conservative_value_and_total() -> None:
    result = settle_value_claim(
        _declaration(),
        (_cohort(CohortRole.BASELINE, _BASELINE), _cohort(CohortRole.TREATMENT, _FASTER)),
    )

    assert result.status is ValueClaimStatus.IMPROVED
    assert result.mean_improvement_per_event is not None
    assert result.conservative_improvement_per_event is not None
    assert 0 < result.conservative_improvement_per_event < result.mean_improvement_per_event
    assert result.conservative_total_improvement == (
        result.conservative_improvement_per_event * result.treatment_sample_count
    )


def test_settlement_is_replay_stable_and_order_independent() -> None:
    cohorts = (_cohort(CohortRole.BASELINE, _BASELINE), _cohort(CohortRole.TREATMENT, _FASTER))

    first = settle_value_claim(_declaration(), cohorts)
    second = settle_value_claim(_declaration(), tuple(reversed(cohorts)))

    assert first.settlement_digest == second.settlement_digest


def test_noisy_overlapping_cohorts_make_no_value_claim() -> None:
    result = settle_value_claim(
        _declaration(),
        (
            _cohort(CohortRole.BASELINE, ["100", "400", "250", "90", "410", "300"]),
            _cohort(CohortRole.TREATMENT, ["120", "380", "260", "100", "390", "310"]),
        ),
    )

    assert result.status is ValueClaimStatus.NO_SIGNIFICANT_CHANGE
    assert result.conservative_total_improvement == Decimal(0)


def test_significant_regression_is_reported_without_value() -> None:
    result = settle_value_claim(
        _declaration(),
        (_cohort(CohortRole.BASELINE, _FASTER), _cohort(CohortRole.TREATMENT, _BASELINE)),
    )

    assert result.status is ValueClaimStatus.REGRESSED
    assert result.conservative_total_improvement == Decimal(0)


def test_increase_is_better_direction_inverts_the_sign() -> None:
    result = settle_value_claim(
        _declaration(direction=ValueDirection.INCREASE_IS_BETTER),
        (_cohort(CohortRole.BASELINE, _FASTER), _cohort(CohortRole.TREATMENT, _BASELINE)),
    )

    assert result.status is ValueClaimStatus.IMPROVED


def test_executor_report_never_settles() -> None:
    result = settle_value_claim(
        _declaration(),
        (
            _cohort(CohortRole.BASELINE, _BASELINE),
            _cohort(CohortRole.TREATMENT, _FASTER, lane=ObservationLane.EXECUTOR_REPORT),
        ),
    )

    assert result.status is ValueClaimStatus.UNSETTLED_NOT_INDEPENDENT
    assert result.conservative_total_improvement is None


def test_policy_escape_blocks_any_claimed_value() -> None:
    result = settle_value_claim(
        _declaration(),
        (
            _cohort(CohortRole.BASELINE, _BASELINE),
            _cohort(CohortRole.TREATMENT, _FASTER, policy_escape_count=1),
        ),
    )

    assert result.status is ValueClaimStatus.BLOCKED_POLICY_ESCAPE
    assert result.conservative_total_improvement is None


@pytest.mark.parametrize(
    ("overrides", "status", "reason"),
    [
        (
            {"scenario_set_version": "set-2"},
            ValueClaimStatus.UNSETTLED_SCOPE_MISMATCH,
            "treatment_scenario_set_mismatch",
        ),
        (
            {"observed_at": _START},
            ValueClaimStatus.UNSETTLED_SCOPE_MISMATCH,
            "treatment_observed_before_window_end",
        ),
        ({"complete": False}, ValueClaimStatus.UNSETTLED_INCOMPLETE, "cohort_not_complete"),
        (
            {"samples_override": ["1", "1", "1"]},
            ValueClaimStatus.UNSETTLED_INSUFFICIENT_SAMPLE,
            "sample_floor_not_met",
        ),
    ],
)
def test_unsupported_cohorts_stay_unsettled(
    overrides: dict[str, object], status: ValueClaimStatus, reason: str
) -> None:
    samples = list(overrides.pop("samples_override", _FASTER))  # type: ignore[call-overload]
    result = settle_value_claim(
        _declaration(),
        (
            _cohort(CohortRole.BASELINE, _BASELINE),
            _cohort(CohortRole.TREATMENT, samples, **overrides),
        ),
    )

    assert result.status is status
    assert reason in result.reason_codes
    assert result.conservative_total_improvement is None


def test_missing_or_duplicate_cohort_is_incomplete() -> None:
    only_baseline = settle_value_claim(_declaration(), (_cohort(CohortRole.BASELINE, _BASELINE),))
    duplicated = settle_value_claim(
        _declaration(),
        (_cohort(CohortRole.BASELINE, _BASELINE), _cohort(CohortRole.BASELINE, _BASELINE)),
    )

    assert only_baseline.status is ValueClaimStatus.UNSETTLED_INCOMPLETE
    assert duplicated.status is ValueClaimStatus.UNSETTLED_INCOMPLETE


def test_cost_claim_requires_matching_currency() -> None:
    declaration = _declaration(unit=ValueUnit.COST_AMOUNT, currency="USD")
    result = settle_value_claim(
        declaration,
        (
            _cohort(CohortRole.BASELINE, _BASELINE, currency="USD"),
            _cohort(CohortRole.TREATMENT, _FASTER, currency="EUR"),
        ),
    )

    assert result.status is ValueClaimStatus.UNSETTLED_SCOPE_MISMATCH
    assert "treatment_currency_mismatch" in result.reason_codes


def test_declaration_rejects_inconsistent_currency_and_window() -> None:
    with pytest.raises(ValidationError):
        _declaration(unit=ValueUnit.COST_AMOUNT)
    with pytest.raises(ValidationError):
        _declaration(currency="USD")
    with pytest.raises(ValidationError):
        _declaration(window_end=_START)
    with pytest.raises(ValidationError):
        _declaration(min_samples_per_cohort=1)


def test_cohort_rejects_non_finite_samples() -> None:
    with pytest.raises(ValidationError):
        _cohort(CohortRole.BASELINE, ["NaN"])
