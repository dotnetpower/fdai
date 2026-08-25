"""Seal complete or explicitly unavailable OI-12 aggregate measurements."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_MAX_REASON_CODES = 16
_MAX_EVIDENCE_DIGESTS = 32
_MAX_VALUE_CHARACTERS = 128


class OperationalCertificationAxis(StrEnum):
    """Name the seven independently measured OI-12 certification axes."""

    FRESHNESS = "freshness"
    API_PRESSURE = "api_pressure"
    LAG = "lag"
    STORAGE_GROWTH = "storage_growth"
    ROLLUP_COVERAGE = "rollup_coverage"
    ARCHIVE_RESTORE = "archive_restore"
    PROVIDER_FAILURE_RECOVERY = "provider_failure_recovery"


_AXIS_UNITS: dict[OperationalCertificationAxis, str] = {
    OperationalCertificationAxis.FRESHNESS: "seconds",
    OperationalCertificationAxis.API_PRESSURE: "ratio",
    OperationalCertificationAxis.LAG: "seconds",
    OperationalCertificationAxis.STORAGE_GROWTH: "bytes_per_hour",
    OperationalCertificationAxis.ROLLUP_COVERAGE: "ratio",
    OperationalCertificationAxis.ARCHIVE_RESTORE: "ratio",
    OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY: "seconds",
}


class OperationalCertificationStatus(StrEnum):
    """Separate measured values from explicit evidence unavailability."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class OperationalCertificationMeasurement:
    """Carry one bounded aggregate measurement without target identities."""

    axis: OperationalCertificationAxis
    status: OperationalCertificationStatus
    measured_at: datetime
    value: Decimal | None
    unit: str | None
    reason_codes: tuple[str, ...]
    evidence_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.axis, OperationalCertificationAxis):
            raise ValueError("certification measurement requires a known axis")
        if not isinstance(self.status, OperationalCertificationStatus):
            raise ValueError("certification measurement requires a known status")
        _aware(self.measured_at, "certification measurement measured_at")
        _ordered_reasons(self.reason_codes)
        _ordered_digests(self.evidence_digests)
        if self.status is OperationalCertificationStatus.AVAILABLE:
            if self.value is None or not self.value.is_finite():
                raise ValueError("available certification measurement requires a finite value")
            if self.value < 0 and self.axis is not OperationalCertificationAxis.STORAGE_GROWTH:
                raise ValueError("certification measurement value MUST NOT be negative")
            if len(_decimal(self.value)) > _MAX_VALUE_CHARACTERS:
                raise ValueError("certification measurement value MUST be bounded")
            if self.unit != _AXIS_UNITS[self.axis]:
                raise ValueError("certification measurement unit does not match its axis")
            if self.unit == "ratio" and self.value > 1:
                raise ValueError("certification ratio MUST be in [0, 1]")
            if self.reason_codes:
                raise ValueError("available certification measurement MUST NOT carry reasons")
        elif self.value is not None or self.unit is not None or not self.reason_codes:
            raise ValueError("unavailable certification measurement requires reasons and no value")


@dataclass(frozen=True, slots=True)
class OperationalInstanceCertificationReceipt:
    """Record seven-axis measurement completeness without certifying readiness."""

    schema_version: str
    window_start: datetime
    window_end: datetime
    recorded_at: datetime
    ontology_release_digest: str
    measurements: tuple[OperationalCertificationMeasurement, ...]
    complete: bool
    unavailable_axes: tuple[OperationalCertificationAxis, ...]
    observation_authority: Literal[False]
    mutation_authority: Literal[False]
    execution_authority: Literal[False]
    digest: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported operational certification schema version")
        _aware(self.window_start, "certification window_start")
        _aware(self.window_end, "certification window_end")
        _aware(self.recorded_at, "certification recorded_at")
        _digest(self.ontology_release_digest, "certification ontology release")
        _digest(self.digest, "certification receipt")
        if self.window_end <= self.window_start:
            raise ValueError("certification window MUST be positive")
        if self.recorded_at < self.window_end:
            raise ValueError("certification recorded_at MUST NOT precede the window end")
        expected_axes = tuple(sorted(OperationalCertificationAxis, key=lambda axis: axis.value))
        observed_axes = tuple(measurement.axis for measurement in self.measurements)
        if observed_axes != expected_axes:
            raise ValueError("certification receipt MUST contain the ordered seven OI-12 axes")
        if any(
            measurement.measured_at < self.window_start or measurement.measured_at > self.window_end
            for measurement in self.measurements
        ):
            raise ValueError("certification measurement MUST fall within the certification window")
        expected_unavailable = tuple(
            measurement.axis
            for measurement in self.measurements
            if measurement.status is OperationalCertificationStatus.UNAVAILABLE
        )
        if self.unavailable_axes != expected_unavailable:
            raise ValueError("certification unavailable axes MUST match measurement status")
        if self.complete is not (not expected_unavailable):
            raise ValueError("certification completeness MUST match unavailable axes")
        if (
            self.observation_authority is not False
            or self.mutation_authority is not False
            or self.execution_authority is not False
        ):
            raise ValueError("operational certification receipt MUST NOT grant authority")
        if self.digest != _sha256(
            _receipt_body(
                schema_version=self.schema_version,
                window_start=self.window_start,
                window_end=self.window_end,
                recorded_at=self.recorded_at,
                ontology_release_digest=self.ontology_release_digest,
                measurements=self.measurements,
                complete=self.complete,
                unavailable_axes=self.unavailable_axes,
            )
        ):
            raise ValueError("certification receipt digest does not match its content")


def build_operational_instance_certification(
    measurements: tuple[OperationalCertificationMeasurement, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    recorded_at: datetime,
    ontology_release_digest: str,
) -> OperationalInstanceCertificationReceipt:
    """Build a replay-stable completeness receipt, not a pass or readiness verdict."""

    _aware(window_start, "certification window_start")
    _aware(window_end, "certification window_end")
    _aware(recorded_at, "certification recorded_at")
    _digest(ontology_release_digest, "certification ontology release")
    if window_end <= window_start:
        raise ValueError("certification window MUST be positive")
    if recorded_at < window_end:
        raise ValueError("certification recorded_at MUST NOT precede the window end")
    expected_axes = set(OperationalCertificationAxis)
    observed_axes = [measurement.axis for measurement in measurements]
    if len(observed_axes) != len(set(observed_axes)):
        raise ValueError("certification measurements MUST be unique by axis")
    if set(observed_axes) != expected_axes:
        raise ValueError("certification measurements MUST contain exactly the seven OI-12 axes")
    if any(
        measurement.measured_at < window_start or measurement.measured_at > window_end
        for measurement in measurements
    ):
        raise ValueError("certification measurement MUST fall within the certification window")
    ordered = tuple(sorted(measurements, key=lambda item: item.axis.value))
    unavailable = tuple(
        measurement.axis
        for measurement in ordered
        if measurement.status is OperationalCertificationStatus.UNAVAILABLE
    )
    body = _receipt_body(
        schema_version="1.0.0",
        window_start=window_start,
        window_end=window_end,
        recorded_at=recorded_at,
        ontology_release_digest=ontology_release_digest,
        measurements=ordered,
        complete=not unavailable,
        unavailable_axes=unavailable,
    )
    return OperationalInstanceCertificationReceipt(
        schema_version="1.0.0",
        window_start=window_start,
        window_end=window_end,
        recorded_at=recorded_at,
        ontology_release_digest=ontology_release_digest,
        measurements=ordered,
        complete=not unavailable,
        unavailable_axes=unavailable,
        observation_authority=False,
        mutation_authority=False,
        execution_authority=False,
        digest=_sha256(body),
    )


def _receipt_body(
    *,
    schema_version: str,
    window_start: datetime,
    window_end: datetime,
    recorded_at: datetime,
    ontology_release_digest: str,
    measurements: tuple[OperationalCertificationMeasurement, ...],
    complete: bool,
    unavailable_axes: tuple[OperationalCertificationAxis, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "window_start": _timestamp(window_start),
        "window_end": _timestamp(window_end),
        "recorded_at": _timestamp(recorded_at),
        "ontology_release_digest": ontology_release_digest,
        "measurements": [_measurement_body(measurement) for measurement in measurements],
        "complete": complete,
        "unavailable_axes": [axis.value for axis in unavailable_axes],
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }


def _measurement_body(measurement: OperationalCertificationMeasurement) -> dict[str, object]:
    return {
        "axis": measurement.axis.value,
        "status": measurement.status.value,
        "measured_at": _timestamp(measurement.measured_at),
        "value": _decimal(measurement.value) if measurement.value is not None else None,
        "unit": measurement.unit,
        "reason_codes": measurement.reason_codes,
        "evidence_digests": measurement.evidence_digests,
    }


def _ordered_reasons(values: tuple[str, ...]) -> None:
    if len(values) > _MAX_REASON_CODES or values != tuple(sorted(set(values))):
        raise ValueError("certification reason codes MUST be bounded, ordered, and unique")
    if any(_REASON_PATTERN.fullmatch(value) is None for value in values):
        raise ValueError("certification reason code MUST be a bounded identifier")


def _ordered_digests(values: tuple[str, ...]) -> None:
    if not 1 <= len(values) <= _MAX_EVIDENCE_DIGESTS:
        raise ValueError("certification evidence digests MUST be bounded and non-empty")
    if values != tuple(sorted(set(values))):
        raise ValueError("certification evidence digests MUST be ordered and unique")
    for value in values:
        _digest(value, "certification evidence digest")


def _decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "OperationalCertificationAxis",
    "OperationalCertificationMeasurement",
    "OperationalCertificationStatus",
    "OperationalInstanceCertificationReceipt",
    "build_operational_instance_certification",
]
