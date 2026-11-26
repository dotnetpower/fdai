"""Reduce aggregate operational evidence into one OI-12 certification receipt."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.ontology_platform.operational_instance_certification import (
    OperationalCertificationAxis,
    OperationalCertificationMeasurement,
    OperationalCertificationStatus,
    OperationalInstanceCertificationReceipt,
    build_operational_instance_certification,
)


@dataclass(frozen=True, slots=True)
class OperationalCertificationSnapshot:
    """Carry one sanitized, content-addressed aggregate evidence observation."""

    measured_at: datetime
    ontology_release_digest: str
    database_bytes: int | None
    freshness_seconds: Decimal | None
    api_pressure_ratio: Decimal | None
    lag_seconds: Decimal | None
    rollup_total_count: int
    rollup_complete_count: int
    restore_total_count: int
    restore_passed_count: int
    provider_failure_recovery_seconds: Decimal | None
    digest: str

    def __post_init__(self) -> None:
        _aware(self.measured_at, "certification snapshot measured_at")
        _digest(self.ontology_release_digest, "certification snapshot ontology release")
        _digest(self.digest, "certification snapshot")
        if self.database_bytes is not None and self.database_bytes < 0:
            raise ValueError("certification snapshot database bytes MUST NOT be negative")
        for name in (
            "freshness_seconds",
            "api_pressure_ratio",
            "lag_seconds",
            "provider_failure_recovery_seconds",
        ):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or value < 0):
                raise ValueError(f"certification snapshot {name} MUST be finite and non-negative")
        if self.api_pressure_ratio is not None and self.api_pressure_ratio > 1:
            raise ValueError("certification snapshot API pressure ratio MUST be in [0, 1]")
        _count_pair(
            total=self.rollup_total_count,
            matched=self.rollup_complete_count,
            name="rollup",
        )
        _count_pair(
            total=self.restore_total_count,
            matched=self.restore_passed_count,
            name="restore",
        )
        if self.digest != _sha256(_snapshot_body(self)):
            raise ValueError("certification snapshot digest does not match its content")


def build_operational_certification_snapshot(
    *,
    measured_at: datetime,
    ontology_release_digest: str,
    database_bytes: int | None,
    freshness_seconds: Decimal | None,
    api_pressure_ratio: Decimal | None,
    lag_seconds: Decimal | None,
    rollup_total_count: int,
    rollup_complete_count: int,
    restore_total_count: int,
    restore_passed_count: int,
    provider_failure_recovery_seconds: Decimal | None,
) -> OperationalCertificationSnapshot:
    """Build one aggregate snapshot after validating every measured axis input."""

    digest = _sha256(
        _snapshot_body_from_values(
            measured_at=measured_at,
            ontology_release_digest=ontology_release_digest,
            database_bytes=database_bytes,
            freshness_seconds=freshness_seconds,
            api_pressure_ratio=api_pressure_ratio,
            lag_seconds=lag_seconds,
            rollup_total_count=rollup_total_count,
            rollup_complete_count=rollup_complete_count,
            restore_total_count=restore_total_count,
            restore_passed_count=restore_passed_count,
            provider_failure_recovery_seconds=provider_failure_recovery_seconds,
        )
    )
    return OperationalCertificationSnapshot(
        measured_at=measured_at,
        ontology_release_digest=ontology_release_digest,
        database_bytes=database_bytes,
        freshness_seconds=freshness_seconds,
        api_pressure_ratio=api_pressure_ratio,
        lag_seconds=lag_seconds,
        rollup_total_count=rollup_total_count,
        rollup_complete_count=rollup_complete_count,
        restore_total_count=restore_total_count,
        restore_passed_count=restore_passed_count,
        provider_failure_recovery_seconds=provider_failure_recovery_seconds,
        digest=digest,
    )


def reduce_operational_instance_certification(
    start: OperationalCertificationSnapshot,
    end: OperationalCertificationSnapshot,
    *,
    recorded_at: datetime,
) -> OperationalInstanceCertificationReceipt:
    """Reduce one positive observation window without converting absence to zero."""

    if start.ontology_release_digest != end.ontology_release_digest:
        raise ValueError("certification snapshots MUST bind the same ontology release")
    if end.measured_at <= start.measured_at:
        raise ValueError("certification snapshot window MUST be positive")
    measurements = (
        _optional_measurement(
            axis=OperationalCertificationAxis.FRESHNESS,
            value=end.freshness_seconds,
            unit="seconds",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="freshness_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.API_PRESSURE,
            value=end.api_pressure_ratio,
            unit="ratio",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="api_pressure_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.LAG,
            value=end.lag_seconds,
            unit="seconds",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="lag_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.STORAGE_GROWTH,
            value=_storage_growth(start, end),
            unit="bytes_per_hour",
            measured_at=end.measured_at,
            evidence_digests=tuple(sorted((start.digest, end.digest))),
            unavailable_reason="storage_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.ROLLUP_COVERAGE,
            value=_ratio(end.rollup_complete_count, end.rollup_total_count),
            unit="ratio",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="rollup_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.ARCHIVE_RESTORE,
            value=_ratio(end.restore_passed_count, end.restore_total_count),
            unit="ratio",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="archive_restore_measurement_unavailable",
        ),
        _optional_measurement(
            axis=OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY,
            value=end.provider_failure_recovery_seconds,
            unit="seconds",
            measured_at=end.measured_at,
            evidence_digests=(end.digest,),
            unavailable_reason="provider_failure_recovery_measurement_unavailable",
        ),
    )
    return build_operational_instance_certification(
        measurements,
        window_start=start.measured_at,
        window_end=end.measured_at,
        recorded_at=recorded_at,
        ontology_release_digest=end.ontology_release_digest,
    )


def _optional_measurement(
    *,
    axis: OperationalCertificationAxis,
    value: Decimal | None,
    unit: str,
    measured_at: datetime,
    evidence_digests: tuple[str, ...],
    unavailable_reason: str,
) -> OperationalCertificationMeasurement:
    if value is None:
        return OperationalCertificationMeasurement(
            axis=axis,
            status=OperationalCertificationStatus.UNAVAILABLE,
            measured_at=measured_at,
            value=None,
            unit=None,
            reason_codes=(unavailable_reason,),
            evidence_digests=evidence_digests,
        )
    return OperationalCertificationMeasurement(
        axis=axis,
        status=OperationalCertificationStatus.AVAILABLE,
        measured_at=measured_at,
        value=value,
        unit=unit,
        reason_codes=(),
        evidence_digests=evidence_digests,
    )


def _storage_growth(
    start: OperationalCertificationSnapshot,
    end: OperationalCertificationSnapshot,
) -> Decimal | None:
    if start.database_bytes is None or end.database_bytes is None:
        return None
    duration = end.measured_at - start.measured_at
    elapsed_microseconds = (
        duration.days * 86_400 + duration.seconds
    ) * 1_000_000 + duration.microseconds
    if elapsed_microseconds <= 0:
        return None
    return (
        Decimal(end.database_bytes - start.database_bytes)
        * Decimal(3_600_000_000)
        / Decimal(elapsed_microseconds)
    )


def _ratio(matched: int, total: int) -> Decimal | None:
    return None if total == 0 else Decimal(matched) / Decimal(total)


def _count_pair(*, total: int, matched: int, name: str) -> None:
    if total < 0 or matched < 0 or matched > total:
        raise ValueError(f"certification snapshot {name} counts are invalid")


def _snapshot_body(snapshot: OperationalCertificationSnapshot) -> dict[str, object]:
    return _snapshot_body_from_values(
        measured_at=snapshot.measured_at,
        ontology_release_digest=snapshot.ontology_release_digest,
        database_bytes=snapshot.database_bytes,
        freshness_seconds=snapshot.freshness_seconds,
        api_pressure_ratio=snapshot.api_pressure_ratio,
        lag_seconds=snapshot.lag_seconds,
        rollup_total_count=snapshot.rollup_total_count,
        rollup_complete_count=snapshot.rollup_complete_count,
        restore_total_count=snapshot.restore_total_count,
        restore_passed_count=snapshot.restore_passed_count,
        provider_failure_recovery_seconds=snapshot.provider_failure_recovery_seconds,
    )


def _snapshot_body_from_values(
    *,
    measured_at: datetime,
    ontology_release_digest: str,
    database_bytes: int | None,
    freshness_seconds: Decimal | None,
    api_pressure_ratio: Decimal | None,
    lag_seconds: Decimal | None,
    rollup_total_count: int,
    rollup_complete_count: int,
    restore_total_count: int,
    restore_passed_count: int,
    provider_failure_recovery_seconds: Decimal | None,
) -> dict[str, object]:
    return {
        "measured_at": measured_at.astimezone(UTC).isoformat(),
        "ontology_release_digest": ontology_release_digest,
        "database_bytes": database_bytes,
        "freshness_seconds": _decimal(freshness_seconds),
        "api_pressure_ratio": _decimal(api_pressure_ratio),
        "lag_seconds": _decimal(lag_seconds),
        "rollup_total_count": rollup_total_count,
        "rollup_complete_count": rollup_complete_count,
        "restore_total_count": restore_total_count,
        "restore_passed_count": restore_passed_count,
        "provider_failure_recovery_seconds": _decimal(provider_failure_recovery_seconds),
    }


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


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
    "OperationalCertificationSnapshot",
    "build_operational_certification_snapshot",
    "reduce_operational_instance_certification",
]
