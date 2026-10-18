from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.shared.providers.testing import InMemoryStateStore

from fdai_cost_governance.forecast_calibration import (
    CostForecastActual,
    CostForecastPrediction,
    DurableForecastCalibration,
    ForecastCalibrationState,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64


def _prediction(index: int, *, amount: str = "100") -> CostForecastPrediction:
    start = NOW + timedelta(days=index)
    return CostForecastPrediction(
        prediction_id=f"forecast-{index}",
        target_ref="scope-example",
        model_revision="budget-forecast-v1",
        source_cutoff=start - timedelta(hours=1),
        window_start_at=start,
        window_end_at=start + timedelta(days=1),
        currency="USD",
        predicted_amount=Decimal(amount),
        evidence_refs=(f"forecast-source-{index}",),
    )


def _actual(
    prediction: CostForecastPrediction,
    *,
    amount: str,
    complete: bool = True,
) -> CostForecastActual:
    return CostForecastActual(
        prediction_id=prediction.prediction_id,
        target_ref=prediction.target_ref,
        window_start_at=prediction.window_start_at,
        window_end_at=prediction.window_end_at,
        currency=prediction.currency,
        actual_amount=Decimal(amount),
        observed_at=prediction.window_end_at + timedelta(minutes=5),
        source_authority="authoritative-billing",
        complete=complete,
        evidence_digest=DIGEST,
    )


async def test_persists_exact_forecasts_and_measures_only_eligible_cohort() -> None:
    store = InMemoryStateStore()
    calibration = DurableForecastCalibration(store, minimum_samples=2)
    first = _prediction(1, amount="100")
    second = _prediction(2, amount="90")

    assert await calibration.record_prediction(first) is True
    assert await calibration.record_prediction(second) is True
    assert await calibration.record_actual(_actual(first, amount="80")) is True
    assert await calibration.record_actual(_actual(second, amount="100")) is True

    snapshot = await calibration.snapshot(
        target_ref="scope-example",
        model_revision="budget-forecast-v1",
    )

    assert snapshot.state is ForecastCalibrationState.MEASURED
    assert snapshot.matched_samples == 2
    assert snapshot.mean_absolute_percentage_error == Decimal("0.175")
    assert snapshot.signed_bias_ratio == Decimal("0.075")
    assert snapshot.zero_actual_samples == 0
    assert snapshot.latest_observed_at == second.window_end_at + timedelta(minutes=5)
    assert len(snapshot.evidence_refs) == 5


async def test_zero_actual_and_small_cohort_remain_explicitly_unmeasured() -> None:
    store = InMemoryStateStore()
    calibration = DurableForecastCalibration(store, minimum_samples=2)
    zero = _prediction(1)
    nonzero = _prediction(2)
    await calibration.record_prediction(zero)
    await calibration.record_prediction(nonzero)
    await calibration.record_actual(_actual(zero, amount="0"))
    await calibration.record_actual(_actual(nonzero, amount="100"))

    snapshot = await calibration.snapshot(
        target_ref="scope-example",
        model_revision="budget-forecast-v1",
    )

    assert snapshot.state is ForecastCalibrationState.INSUFFICIENT_COHORT
    assert snapshot.matched_samples == 1
    assert snapshot.zero_actual_samples == 1
    assert snapshot.mean_absolute_percentage_error is None
    assert snapshot.signed_bias_ratio is None


async def test_exact_replay_is_noop_and_changed_payload_conflicts() -> None:
    store = InMemoryStateStore()
    calibration = DurableForecastCalibration(store, minimum_samples=2)
    prediction = _prediction(1)

    assert await calibration.record_prediction(prediction) is True
    assert await calibration.record_prediction(prediction) is False
    with pytest.raises(ValueError, match="idempotency conflict"):
        await calibration.record_prediction(replace(prediction, predicted_amount=Decimal("200")))


async def test_actual_requires_complete_matching_durable_prediction() -> None:
    store = InMemoryStateStore()
    calibration = DurableForecastCalibration(store, minimum_samples=2)
    prediction = _prediction(1)

    with pytest.raises(ValueError, match="durable prediction"):
        await calibration.record_actual(_actual(prediction, amount="100"))
    await calibration.record_prediction(prediction)
    with pytest.raises(ValueError, match="complete authoritative window"):
        await calibration.record_actual(_actual(prediction, amount="100", complete=False))
    with pytest.raises(ValueError, match="lineage does not match"):
        await calibration.record_actual(replace(_actual(prediction, amount="100"), currency="EUR"))


def test_contract_rejects_invalid_windows_currency_and_evidence() -> None:
    prediction = _prediction(1)
    with pytest.raises(ValueError, match="positive"):
        replace(prediction, window_end_at=prediction.window_start_at)
    with pytest.raises(ValueError, match="currency"):
        replace(prediction, currency="usd")
    with pytest.raises(ValueError, match="positive"):
        replace(prediction, predicted_amount=Decimal("0"))
    with pytest.raises(ValueError, match="evidence refs"):
        replace(prediction, evidence_refs=())
    with pytest.raises(ValueError, match="source cutoff"):
        replace(
            prediction,
            source_cutoff=prediction.window_start_at + timedelta(seconds=1),
        )
