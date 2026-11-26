"""Strict JSON codec for durable dispatch-start lineage."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    IdempotencyReservationTransitionReceipt,
)
from fdai.core.executor.idempotency_reservation_codec import (
    reservation_record_from_mapping,
    reservation_record_to_mapping,
)
from fdai.core.executor.safeguard_dispatch_start import (
    SafeguardDispatchStartCheckpoint,
)
from fdai.core.executor.target_dispatch_fence_codec import (
    target_dispatch_fence_from_mapping,
    target_dispatch_fence_to_mapping,
)


def dispatch_start_checkpoint_to_mapping(
    checkpoint: SafeguardDispatchStartCheckpoint,
) -> dict[str, object]:
    """Serialize exact pre-I/O lineage to durable JSON values."""

    return {
        "schema_version": checkpoint.schema_version,
        "evidence_identity_digest": checkpoint.evidence_identity_digest,
        "bundle_record_digest": checkpoint.bundle_record_digest,
        "bundle_record_revision": checkpoint.bundle_record_revision,
        "bundle_persistence_receipt_digest": (checkpoint.bundle_persistence_receipt_digest),
        "in_flight_reservation_receipt": _reservation_receipt_mapping(
            checkpoint.in_flight_reservation_receipt
        ),
        "prepared_fence": target_dispatch_fence_to_mapping(checkpoint.prepared_fence),
        "in_flight_fence": target_dispatch_fence_to_mapping(checkpoint.in_flight_fence),
        "dispatch_started_at": checkpoint.dispatch_started_at.isoformat(),
        "checkpoint_digest": checkpoint.checkpoint_digest,
        "execution_authority": checkpoint.execution_authority,
        "effect_verified": checkpoint.effect_verified,
    }


def dispatch_start_checkpoint_from_mapping(
    value: Mapping[str, object],
) -> SafeguardDispatchStartCheckpoint:
    """Parse exact pre-I/O lineage and rerun semantic invariants."""

    checkpoint = _exact_mapping(
        value,
        {
            "schema_version",
            "evidence_identity_digest",
            "bundle_record_digest",
            "bundle_record_revision",
            "bundle_persistence_receipt_digest",
            "in_flight_reservation_receipt",
            "prepared_fence",
            "in_flight_fence",
            "dispatch_started_at",
            "checkpoint_digest",
            "execution_authority",
            "effect_verified",
        },
        "checkpoint",
    )
    return SafeguardDispatchStartCheckpoint(
        schema_version=_schema_version(checkpoint),
        evidence_identity_digest=_str_field(
            checkpoint,
            "evidence_identity_digest",
        ),
        bundle_record_digest=_str_field(checkpoint, "bundle_record_digest"),
        bundle_record_revision=_int_field(
            checkpoint,
            "bundle_record_revision",
        ),
        bundle_persistence_receipt_digest=_str_field(
            checkpoint,
            "bundle_persistence_receipt_digest",
        ),
        in_flight_reservation_receipt=_reservation_receipt_from_mapping(
            _mapping_field(checkpoint, "in_flight_reservation_receipt")
        ),
        prepared_fence=target_dispatch_fence_from_mapping(
            _mapping_field(checkpoint, "prepared_fence")
        ),
        in_flight_fence=target_dispatch_fence_from_mapping(
            _mapping_field(checkpoint, "in_flight_fence")
        ),
        dispatch_started_at=_datetime_field(
            checkpoint,
            "dispatch_started_at",
        ),
        checkpoint_digest=_str_field(checkpoint, "checkpoint_digest"),
        execution_authority=_false_field(
            checkpoint,
            "execution_authority",
        ),
        effect_verified=_false_field(checkpoint, "effect_verified"),
    )


def _reservation_receipt_mapping(
    receipt: IdempotencyReservationTransitionReceipt,
) -> dict[str, object]:
    return {
        "schema_version": receipt.schema_version,
        "prior_record": (
            reservation_record_to_mapping(receipt.prior_record)
            if receipt.prior_record is not None
            else None
        ),
        "record": reservation_record_to_mapping(receipt.record),
        "expected_prior_revision": receipt.expected_prior_revision,
        "store_receipt_digest": receipt.store_receipt_digest,
        "recorded_at": receipt.recorded_at.isoformat(),
        "receipt_digest": receipt.receipt_digest,
        "execution_authority": receipt.execution_authority,
        "effect_verified": receipt.effect_verified,
    }


def _reservation_receipt_from_mapping(
    value: Mapping[str, object],
) -> IdempotencyReservationTransitionReceipt:
    receipt = _exact_mapping(
        value,
        {
            "schema_version",
            "prior_record",
            "record",
            "expected_prior_revision",
            "store_receipt_digest",
            "recorded_at",
            "receipt_digest",
            "execution_authority",
            "effect_verified",
        },
        "reservation receipt",
    )
    return IdempotencyReservationTransitionReceipt(
        schema_version=_schema_version(receipt),
        prior_record=_optional_reservation_record(receipt),
        record=reservation_record_from_mapping(_mapping_field(receipt, "record")),
        expected_prior_revision=_int_field(
            receipt,
            "expected_prior_revision",
        ),
        store_receipt_digest=_str_field(receipt, "store_receipt_digest"),
        recorded_at=_datetime_field(receipt, "recorded_at"),
        receipt_digest=_str_field(receipt, "receipt_digest"),
        execution_authority=_false_field(
            receipt,
            "execution_authority",
        ),
        effect_verified=_false_field(receipt, "effect_verified"),
    )


def _optional_reservation_record(
    receipt: Mapping[str, object],
) -> IdempotencyReservationRecord | None:
    raw = receipt.get("prior_record")
    if raw is None:
        return None
    if type(raw) is not dict:
        raise ValueError("safeguard dispatch-start prior record MUST be an object")
    return reservation_record_from_mapping(cast(dict[str, object], raw))


def _exact_mapping(
    value: Mapping[str, object],
    expected_keys: set[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"safeguard dispatch-start {name} fields are invalid")
    return value


def _mapping_field(
    value: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    field = value.get(name)
    if type(field) is not dict:
        raise ValueError(f"safeguard dispatch-start {name} MUST be an object")
    return cast(dict[str, object], field)


def _str_field(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if type(field) is not str:
        raise ValueError(f"safeguard dispatch-start {name} MUST be a string")
    return field


def _int_field(value: Mapping[str, object], name: str) -> int:
    field = value.get(name)
    if type(field) is not int:
        raise ValueError(f"safeguard dispatch-start {name} MUST be an integer")
    return field


def _datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime:
    field = _str_field(value, name)
    try:
        parsed = datetime.fromisoformat(field)
    except ValueError as exc:
        raise ValueError(f"safeguard dispatch-start {name} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"safeguard dispatch-start {name} MUST include a timezone")
    return parsed.astimezone(UTC)


def _schema_version(
    value: Mapping[str, object],
) -> Literal["1.0.0"]:
    if _str_field(value, "schema_version") != "1.0.0":
        raise ValueError("safeguard dispatch-start schema version is unsupported")
    return "1.0.0"


def _false_field(
    value: Mapping[str, object],
    name: str,
) -> Literal[False]:
    if value.get(name) is not False:
        raise ValueError(f"safeguard dispatch-start {name} MUST be false")
    return False


__all__ = [
    "dispatch_start_checkpoint_from_mapping",
    "dispatch_start_checkpoint_to_mapping",
]
