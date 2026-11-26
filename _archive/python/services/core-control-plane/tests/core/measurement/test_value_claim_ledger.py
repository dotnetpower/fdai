from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fdai.core.measurement.outcome_assurance import OutcomeEvidenceState
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
from fdai.core.measurement.value_claim_ledger import (
    StateStoreValueClaimLedger,
    outcome_measurement_from_settlement,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_END = datetime(2026, 10, 15, tzinfo=UTC)
_AFTER = datetime(2026, 10, 16, tzinfo=UTC)
_BASELINE = ["600", "620", "580", "610", "590", "605"]
_FASTER = ["300", "310", "290", "305", "295", "300"]


def _declaration(**overrides: object) -> ValueClaimDeclaration:
    values: dict[str, object] = {
        "claim_id": "claim-1",
        "workflow_ref": "predictive-scale",
        "workflow_version": "1.0.0",
        "objective_ref": "objective-1",
        "metric_name": "mttr",
        "unit": ValueUnit.DURATION_SECONDS,
        "direction": ValueDirection.DECREASE_IS_BETTER,
        "target_value": Decimal("400"),
        "scenario_set_version": "set-1",
        "window_start": datetime(2026, 10, 1, tzinfo=UTC),
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


def _settle(treatment: list[str], **overrides: object):
    return settle_value_claim(
        _declaration(),
        (
            _cohort(CohortRole.BASELINE, _BASELINE),
            _cohort(CohortRole.TREATMENT, treatment, **overrides),
        ),
    )


async def test_record_is_idempotent_and_returns_the_durable_record() -> None:
    store = InMemoryStateStore()
    ledger = StateStoreValueClaimLedger(store)
    declaration = _declaration()
    settlement = _settle(_FASTER)

    assert await ledger.record(declaration, settlement) is True
    assert await ledger.record(declaration, settlement) is False
    stored = await ledger.read(settlement.claim_id, settlement.settlement_digest)

    assert stored is not None
    assert stored["status"] == "improved"
    assert stored["workflow_ref"] == "predictive-scale"
    assert stored["settlement_digest"] == settlement.settlement_digest
    assert stored["conservative_total_improvement"] == str(
        settlement.conservative_total_improvement
    )


async def test_record_rejects_a_settlement_for_another_claim() -> None:
    ledger = StateStoreValueClaimLedger(InMemoryStateStore())

    with pytest.raises(ValueError, match="does not match"):
        await ledger.record(_declaration(claim_id="other"), _settle(_FASTER))


def test_improved_settlement_projects_as_a_measured_outcome_with_its_interval() -> None:
    declaration = _declaration()
    settlement = _settle(_FASTER)

    measurement = outcome_measurement_from_settlement(declaration, settlement)

    assert measurement.state is OutcomeEvidenceState.MEASURED
    assert measurement.objective_ref == "objective-1"
    assert measurement.unit == "duration_seconds"
    assert measurement.target_value == 400.0
    assert measurement.baseline_value is not None and measurement.baseline_value > 590
    assert measurement.current_value is not None and measurement.current_value < 310
    assert measurement.confidence_interval is not None
    assert (
        measurement.confidence_interval.low
        <= measurement.current_value
        <= measurement.confidence_interval.high
    )
    assert measurement.sample_size == 6
    assert measurement.source_time == _AFTER


def test_regression_projects_as_regressed_and_unsettled_never_as_measured() -> None:
    declaration = _declaration()
    regressed = settle_value_claim(
        declaration,
        (
            _cohort(CohortRole.BASELINE, _FASTER),
            _cohort(CohortRole.TREATMENT, _BASELINE),
        ),
    )
    thin = _settle(["1", "1", "1"] * 1)
    executor = _settle(_FASTER, lane=ObservationLane.EXECUTOR_REPORT)
    escaped = _settle(_FASTER, policy_escape_count=2)

    assert (
        outcome_measurement_from_settlement(declaration, regressed).state
        is OutcomeEvidenceState.REGRESSED
    )
    assert thin.status is ValueClaimStatus.UNSETTLED_INSUFFICIENT_SAMPLE
    assert (
        outcome_measurement_from_settlement(declaration, thin).state
        is OutcomeEvidenceState.INSUFFICIENT_SAMPLE
    )
    for unsettled in (executor, escaped):
        measurement = outcome_measurement_from_settlement(declaration, unsettled)
        assert measurement.state is OutcomeEvidenceState.NOT_CONNECTED
        assert measurement.current_value is None
