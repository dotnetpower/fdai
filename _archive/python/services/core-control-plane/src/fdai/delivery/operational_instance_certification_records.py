"""Serialize OI-12 records without provider coordinates or authority."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from fdai.core.ontology_platform.operational_instance_certification import (
    OperationalInstanceCertificationReceipt,
)


def receipt_record(receipt: OperationalInstanceCertificationReceipt) -> dict[str, object]:
    """Serialize a no-authority receipt with decimal values preserved as strings."""

    return {
        "schema_version": receipt.schema_version,
        "window_start": receipt.window_start.astimezone(UTC).isoformat(),
        "window_end": receipt.window_end.astimezone(UTC).isoformat(),
        "recorded_at": receipt.recorded_at.astimezone(UTC).isoformat(),
        "ontology_release_digest": receipt.ontology_release_digest,
        "measurements": [
            {
                "axis": measurement.axis.value,
                "status": measurement.status.value,
                "measured_at": measurement.measured_at.astimezone(UTC).isoformat(),
                "value": _decimal(measurement.value),
                "unit": measurement.unit,
                "reason_codes": list(measurement.reason_codes),
                "evidence_digests": list(measurement.evidence_digests),
            }
            for measurement in receipt.measurements
        ],
        "complete": receipt.complete,
        "unavailable_axes": [axis.value for axis in receipt.unavailable_axes],
        "observation_authority": receipt.observation_authority,
        "mutation_authority": receipt.mutation_authority,
        "execution_authority": receipt.execution_authority,
        "digest": receipt.digest,
    }


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


__all__ = ["receipt_record"]
