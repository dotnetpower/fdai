"""Durable, authority-neutral calibration for Cost Governance forecasts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from fdai.shared.providers.state_store import StateStore

_PREDICTION_PREFIX = "cost-governance/forecast-calibration/predictions/"
_ACTUAL_PREFIX = "cost-governance/forecast-calibration/actuals/"
_MAX_RECORDS = 512


class ForecastCalibrationState(StrEnum):
    INSUFFICIENT_COHORT = "insufficient_cohort"
    MEASURED = "measured"


@dataclass(frozen=True, slots=True)
class CostForecastPrediction:
    prediction_id: str
    target_ref: str
    model_revision: str
    source_cutoff: datetime
    window_start_at: datetime
    window_end_at: datetime
    currency: str
    predicted_amount: Decimal
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _exact("prediction_id", self.prediction_id)
        _exact("target_ref", self.target_ref)
        _exact("model_revision", self.model_revision)
        _window(self.source_cutoff, self.window_start_at, self.window_end_at)
        _currency(self.currency)
        _amount("predicted_amount", self.predicted_amount, positive=True)
        _refs(self.evidence_refs)

    @property
    def digest(self) -> str:
        return _digest(_prediction_mapping(self))


@dataclass(frozen=True, slots=True)
class CostForecastActual:
    prediction_id: str
    target_ref: str
    window_start_at: datetime
    window_end_at: datetime
    currency: str
    actual_amount: Decimal
    observed_at: datetime
    source_authority: str
    complete: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        _exact("prediction_id", self.prediction_id)
        _exact("target_ref", self.target_ref)
        _window(self.observed_at, self.window_start_at, self.window_end_at)
        if self.observed_at < self.window_end_at:
            raise ValueError("forecast actual MUST follow its complete observation window")
        _currency(self.currency)
        _amount("actual_amount", self.actual_amount)
        _exact("source_authority", self.source_authority)
        _sha256("evidence_digest", self.evidence_digest)

    @property
    def digest(self) -> str:
        return _digest(_actual_mapping(self))


@dataclass(frozen=True, slots=True)
class ForecastCalibrationSnapshot:
    target_ref: str
    model_revision: str
    state: ForecastCalibrationState
    matched_samples: int
    zero_actual_samples: int
    mean_absolute_percentage_error: Decimal | None
    signed_bias_ratio: Decimal | None
    latest_observed_at: datetime | None
    evidence_refs: tuple[str, ...]


class DurableForecastCalibration:
    """Persist exact predictions and authoritative actuals, then calibrate them."""

    def __init__(self, store: StateStore, *, minimum_samples: int = 5) -> None:
        if not 2 <= minimum_samples <= _MAX_RECORDS:
            raise ValueError("forecast calibration minimum_samples MUST be in [2, 512]")
        self._store = store
        self._minimum_samples = minimum_samples

    async def record_prediction(self, prediction: CostForecastPrediction) -> bool:
        mapping = {
            **_prediction_mapping(prediction),
            "schema_version": "1.0.0",
            "record_digest": prediction.digest,
        }
        return await self._append_exact(_prediction_key(prediction.prediction_id), mapping)

    async def record_actual(self, actual: CostForecastActual) -> bool:
        raw_prediction = await self._store.read_state(_prediction_key(actual.prediction_id))
        if raw_prediction is None:
            raise ValueError("forecast actual requires a durable prediction")
        if (
            raw_prediction.get("target_ref") != actual.target_ref
            or raw_prediction.get("window_start_at")
            != actual.window_start_at.astimezone(UTC).isoformat()
            or raw_prediction.get("window_end_at")
            != actual.window_end_at.astimezone(UTC).isoformat()
            or raw_prediction.get("currency") != actual.currency
        ):
            raise ValueError("forecast actual lineage does not match its prediction")
        if not actual.complete:
            raise ValueError("forecast actual requires a complete authoritative window")
        mapping = {
            **_actual_mapping(actual),
            "schema_version": "1.0.0",
            "record_digest": actual.digest,
        }
        return await self._append_exact(_actual_key(actual.prediction_id), mapping)

    async def snapshot(
        self,
        *,
        target_ref: str,
        model_revision: str,
    ) -> ForecastCalibrationSnapshot:
        _exact("target_ref", target_ref)
        _exact("model_revision", model_revision)
        predictions = {
            str(row.get("prediction_id") or ""): row
            for row in await self._store.read_states(_PREDICTION_PREFIX, limit=_MAX_RECORDS)
            if row.get("target_ref") == target_ref and row.get("model_revision") == model_revision
        }
        actuals = {
            str(row.get("prediction_id") or ""): row
            for row in await self._store.read_states(_ACTUAL_PREFIX, limit=_MAX_RECORDS)
            if row.get("target_ref") == target_ref
        }
        errors: list[Decimal] = []
        biases: list[Decimal] = []
        evidence: list[str] = []
        observed: list[datetime] = []
        zero_actual_samples = 0
        for prediction_id in sorted(set(predictions) & set(actuals)):
            prediction = predictions[prediction_id]
            actual = actuals[prediction_id]
            if actual.get("complete") is not True:
                continue
            predicted_amount = Decimal(str(prediction["predicted_amount"]))
            actual_amount = Decimal(str(actual["actual_amount"]))
            evidence.append(str(prediction["record_digest"]))
            evidence.append(str(actual["evidence_digest"]))
            observed.append(datetime.fromisoformat(str(actual["observed_at"])))
            if actual_amount == 0:
                zero_actual_samples += 1
                continue
            errors.append(abs(predicted_amount - actual_amount) / actual_amount)
            biases.append((predicted_amount - actual_amount) / actual_amount)
        state = (
            ForecastCalibrationState.MEASURED
            if len(errors) >= self._minimum_samples
            else ForecastCalibrationState.INSUFFICIENT_COHORT
        )
        return ForecastCalibrationSnapshot(
            target_ref=target_ref,
            model_revision=model_revision,
            state=state,
            matched_samples=len(errors),
            zero_actual_samples=zero_actual_samples,
            mean_absolute_percentage_error=(
                sum(errors, Decimal("0")) / Decimal(len(errors))
                if state is ForecastCalibrationState.MEASURED
                else None
            ),
            signed_bias_ratio=(
                sum(biases, Decimal("0")) / Decimal(len(biases))
                if state is ForecastCalibrationState.MEASURED
                else None
            ),
            latest_observed_at=max(observed) if observed else None,
            evidence_refs=tuple(sorted(set(evidence))),
        )

    async def _append_exact(self, key: str, mapping: dict[str, Any]) -> bool:
        created = await self._store.write_state_if_absent(key, mapping)
        if created:
            return True
        existing = await self._store.read_state(key)
        if existing != mapping:
            raise ValueError("forecast calibration idempotency conflict")
        return False


def _prediction_key(prediction_id: str) -> str:
    return _PREDICTION_PREFIX + hashlib.sha256(prediction_id.encode()).hexdigest()


def _actual_key(prediction_id: str) -> str:
    return _ACTUAL_PREFIX + hashlib.sha256(prediction_id.encode()).hexdigest()


def _prediction_mapping(prediction: CostForecastPrediction) -> dict[str, Any]:
    return {
        "prediction_id": prediction.prediction_id,
        "target_ref": prediction.target_ref,
        "model_revision": prediction.model_revision,
        "source_cutoff": prediction.source_cutoff.astimezone(UTC).isoformat(),
        "window_start_at": prediction.window_start_at.astimezone(UTC).isoformat(),
        "window_end_at": prediction.window_end_at.astimezone(UTC).isoformat(),
        "currency": prediction.currency,
        "predicted_amount": str(prediction.predicted_amount),
        "evidence_refs": list(prediction.evidence_refs),
    }


def _actual_mapping(actual: CostForecastActual) -> dict[str, Any]:
    return {
        "prediction_id": actual.prediction_id,
        "target_ref": actual.target_ref,
        "window_start_at": actual.window_start_at.astimezone(UTC).isoformat(),
        "window_end_at": actual.window_end_at.astimezone(UTC).isoformat(),
        "currency": actual.currency,
        "actual_amount": str(actual.actual_amount),
        "observed_at": actual.observed_at.astimezone(UTC).isoformat(),
        "source_authority": actual.source_authority,
        "complete": actual.complete,
        "evidence_digest": actual.evidence_digest,
    }


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _exact(name: str, value: str) -> None:
    if not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f"{name} MUST be bounded exact text")


def _sha256(name: str, value: str) -> None:
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be an exact SHA-256 digest")


def _currency(value: str) -> None:
    if len(value) != 3 or not value.isascii() or not value.isupper():
        raise ValueError("forecast currency MUST be a three-letter uppercase code")


def _amount(name: str, value: Decimal, *, positive: bool = False) -> None:
    if not value.is_finite() or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} MUST be finite and {qualifier}")


def _window(reference: datetime, start: datetime, end: datetime) -> None:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (reference, start, end)):
        raise ValueError("forecast calibration times MUST be timezone-aware")
    if end <= start:
        raise ValueError("forecast calibration window MUST be positive")


def _refs(values: tuple[str, ...]) -> None:
    if not values or len(values) > 32 or len(values) != len(set(values)):
        raise ValueError("forecast evidence refs MUST contain 1..32 unique values")
    for value in values:
        _exact("forecast evidence ref", value)


__all__ = [
    "CostForecastActual",
    "CostForecastPrediction",
    "DurableForecastCalibration",
    "ForecastCalibrationSnapshot",
    "ForecastCalibrationState",
]
