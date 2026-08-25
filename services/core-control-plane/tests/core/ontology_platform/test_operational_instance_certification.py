"""OI-12 operational instance certification receipt tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.ontology_platform.operational_instance_certification import (
    OperationalCertificationAxis,
    OperationalCertificationMeasurement,
    OperationalCertificationStatus,
    OperationalInstanceCertificationReceipt,
    build_operational_instance_certification,
)

_START = datetime(2026, 8, 25, tzinfo=UTC)
_END = _START + timedelta(hours=1)
_RELEASE = "sha256:" + "a" * 64
_EVIDENCE = "sha256:" + "b" * 64
_UNITS = {
    OperationalCertificationAxis.FRESHNESS: "seconds",
    OperationalCertificationAxis.API_PRESSURE: "ratio",
    OperationalCertificationAxis.LAG: "seconds",
    OperationalCertificationAxis.STORAGE_GROWTH: "bytes_per_hour",
    OperationalCertificationAxis.ROLLUP_COVERAGE: "ratio",
    OperationalCertificationAxis.ARCHIVE_RESTORE: "ratio",
    OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY: "seconds",
}


def _measurement(axis: OperationalCertificationAxis) -> OperationalCertificationMeasurement:
    value = Decimal("0.95") if _UNITS[axis] == "ratio" else Decimal("5")
    return OperationalCertificationMeasurement(
        axis=axis,
        status=OperationalCertificationStatus.AVAILABLE,
        measured_at=_START + timedelta(minutes=30),
        value=value,
        unit=_UNITS[axis],
        reason_codes=(),
        evidence_digests=(_EVIDENCE,),
    )


def _measurements() -> tuple[OperationalCertificationMeasurement, ...]:
    return tuple(_measurement(axis) for axis in OperationalCertificationAxis)


def _build(
    measurements: tuple[OperationalCertificationMeasurement, ...],
) -> OperationalInstanceCertificationReceipt:
    return build_operational_instance_certification(
        measurements,
        window_start=_START,
        window_end=_END,
        recorded_at=_END + timedelta(seconds=1),
        ontology_release_digest=_RELEASE,
    )


def test_complete_seven_axis_receipt_is_ordered_replayable_and_authority_free() -> None:
    measurements = _measurements()

    first = _build(tuple(reversed(measurements)))
    replay = _build(measurements)

    assert tuple(item.axis for item in first.measurements) == tuple(
        sorted(OperationalCertificationAxis, key=lambda axis: axis.value)
    )
    assert first.complete is True
    assert first.unavailable_axes == ()
    assert first.digest == replay.digest
    assert first.observation_authority is False
    assert first.mutation_authority is False
    assert first.execution_authority is False


def test_unmeasured_storage_and_provider_recovery_remain_explicitly_unavailable() -> None:
    measurements = {measurement.axis: measurement for measurement in _measurements()}
    for axis, reason in (
        (OperationalCertificationAxis.STORAGE_GROWTH, "storage_metric_unavailable"),
        (
            OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY,
            "recovery_exercise_not_observed",
        ),
    ):
        measurements[axis] = replace(
            measurements[axis],
            status=OperationalCertificationStatus.UNAVAILABLE,
            value=None,
            unit=None,
            reason_codes=(reason,),
        )

    receipt = _build(tuple(measurements.values()))

    assert receipt.complete is False
    assert receipt.unavailable_axes == (
        OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY,
        OperationalCertificationAxis.STORAGE_GROWTH,
    )
    assert {
        measurement.axis: measurement.reason_codes
        for measurement in receipt.measurements
        if measurement.status is OperationalCertificationStatus.UNAVAILABLE
    } == {
        OperationalCertificationAxis.PROVIDER_FAILURE_RECOVERY: ("recovery_exercise_not_observed",),
        OperationalCertificationAxis.STORAGE_GROWTH: ("storage_metric_unavailable",),
    }


def test_receipt_rejects_missing_or_duplicate_axis() -> None:
    measurements = _measurements()

    with pytest.raises(ValueError, match="exactly the seven"):
        _build(measurements[:-1])
    with pytest.raises(ValueError, match="unique by axis"):
        _build((*measurements, measurements[0]))


def test_receipt_rejects_post_build_invariant_or_digest_substitution() -> None:
    receipt = _build(_measurements())

    with pytest.raises(ValueError, match="ordered seven"):
        replace(receipt, measurements=receipt.measurements[:-1])
    with pytest.raises(ValueError, match="completeness MUST match"):
        replace(receipt, complete=False)
    with pytest.raises(ValueError, match="digest does not match"):
        replace(receipt, digest="sha256:" + "c" * 64)


def test_measurement_rejects_invalid_available_or_unavailable_shapes() -> None:
    with pytest.raises(ValueError, match=r"ratio MUST be in \[0, 1\]"):
        replace(
            _measurement(OperationalCertificationAxis.API_PRESSURE),
            value=Decimal("1.1"),
        )
    with pytest.raises(ValueError, match="unit does not match"):
        replace(
            _measurement(OperationalCertificationAxis.FRESHNESS),
            unit="ratio",
        )
    with pytest.raises(ValueError, match="requires reasons"):
        replace(
            _measurement(OperationalCertificationAxis.LAG),
            status=OperationalCertificationStatus.UNAVAILABLE,
            value=None,
            unit=None,
        )


def test_storage_growth_preserves_contraction_without_widening_other_axes() -> None:
    contraction = replace(
        _measurement(OperationalCertificationAxis.STORAGE_GROWTH),
        value=Decimal("-128"),
    )

    assert contraction.value == Decimal("-128")
    with pytest.raises(ValueError, match="MUST NOT be negative"):
        replace(
            _measurement(OperationalCertificationAxis.FRESHNESS),
            value=Decimal("-0.1"),
        )


@pytest.mark.parametrize(
    "authority_field",
    ["observation_authority", "mutation_authority", "execution_authority"],
)
def test_receipt_authority_cannot_be_replaced_with_true(authority_field: str) -> None:
    receipt = _build(_measurements())

    with pytest.raises(ValueError, match="MUST NOT grant authority"):
        replace(receipt, **{authority_field: True})
