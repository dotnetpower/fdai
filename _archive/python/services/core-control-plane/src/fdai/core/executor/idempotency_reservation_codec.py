"""Exact durable JSON mapping for executor idempotency reservations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from fdai.shared.contracts.models import ExecutionPath
from fdai.shared.providers.resource_lock import ResourceLockAcquisitionReceipt

from .idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    ReservationEvidenceKind,
    ReservationState,
    _normalize_digest_value,
    _utc,
)


def reservation_record_to_mapping(
    record: IdempotencyReservationRecord,
) -> dict[str, object]:
    """Serialize one canonical record for durable JSON storage."""

    if type(record) is not IdempotencyReservationRecord:
        raise ValueError("idempotency reservation serializer requires an exact record")
    normalized = _normalize_digest_value(asdict(record))
    if not isinstance(normalized, dict):
        raise ValueError("idempotency reservation serialization is not an object")
    return cast(dict[str, object], normalized)


def reservation_record_from_mapping(
    value: Mapping[str, object],
) -> IdempotencyReservationRecord:
    """Parse one exact durable record and rerun every semantic invariant."""

    record = _exact_mapping(
        value,
        {
            "schema_version",
            "identity",
            "state",
            "revision",
            "owner_reference_digest",
            "reserved_at",
            "lease_expires_at",
            "state_changed_at",
            "dispatch_started_at",
            "evidence_kind",
            "evidence_digest",
            "terminal_outcome_digest",
            "record_digest",
            "execution_authority",
            "effect_verified",
        },
        "record",
    )
    identity_raw = _exact_mapping(
        _mapping_field(record, "identity"),
        {
            "schema_version",
            "idempotency_key",
            "action_digest",
            "execution_path",
            "execution_fingerprint",
            "source_revision",
            "acquisition_receipt",
            "identity_digest",
            "execution_authority",
        },
        "identity",
    )
    acquisition_raw = _exact_mapping(
        _mapping_field(identity_raw, "acquisition_receipt"),
        {
            "schema_version",
            "lock_key",
            "target_digest",
            "action_digest",
            "attempt",
            "provider_id",
            "provider_version",
            "producer_id",
            "producer_version",
            "owner_token_digest",
            "fencing_generation",
            "session_identity",
            "provider_attestation_digest",
            "trust_anchor_id",
            "acquired_at",
            "valid_until",
            "source_revision",
            "request_digest",
            "receipt_digest",
            "execution_authority",
        },
        "acquisition receipt",
    )
    acquisition = ResourceLockAcquisitionReceipt(
        schema_version=_schema_version_field(acquisition_raw),
        lock_key=_str_field(acquisition_raw, "lock_key"),
        target_digest=_str_field(acquisition_raw, "target_digest"),
        action_digest=_str_field(acquisition_raw, "action_digest"),
        attempt=_int_field(acquisition_raw, "attempt"),
        provider_id=_str_field(acquisition_raw, "provider_id"),
        provider_version=_str_field(acquisition_raw, "provider_version"),
        producer_id=_str_field(acquisition_raw, "producer_id"),
        producer_version=_str_field(acquisition_raw, "producer_version"),
        owner_token_digest=_str_field(acquisition_raw, "owner_token_digest"),
        fencing_generation=_optional_int_field(
            acquisition_raw,
            "fencing_generation",
        ),
        session_identity=_optional_str_field(acquisition_raw, "session_identity"),
        provider_attestation_digest=_str_field(
            acquisition_raw,
            "provider_attestation_digest",
        ),
        trust_anchor_id=_str_field(acquisition_raw, "trust_anchor_id"),
        acquired_at=_datetime_field(acquisition_raw, "acquired_at"),
        valid_until=_optional_datetime_field(acquisition_raw, "valid_until"),
        source_revision=_str_field(acquisition_raw, "source_revision"),
        request_digest=_str_field(acquisition_raw, "request_digest"),
        receipt_digest=_str_field(acquisition_raw, "receipt_digest"),
        execution_authority=_false_field(
            acquisition_raw,
            "execution_authority",
        ),
    )
    identity = IdempotencyReservationIdentity(
        schema_version=_schema_version_field(identity_raw),
        idempotency_key=_str_field(identity_raw, "idempotency_key"),
        action_digest=_str_field(identity_raw, "action_digest"),
        execution_path=_enum_field(
            identity_raw,
            "execution_path",
            ExecutionPath,
        ),
        execution_fingerprint=_str_field(
            identity_raw,
            "execution_fingerprint",
        ),
        source_revision=_str_field(identity_raw, "source_revision"),
        acquisition_receipt=acquisition,
        identity_digest=_str_field(identity_raw, "identity_digest"),
        execution_authority=_false_field(identity_raw, "execution_authority"),
    )
    return IdempotencyReservationRecord(
        schema_version=_schema_version_field(record),
        identity=identity,
        state=_enum_field(record, "state", ReservationState),
        revision=_int_field(record, "revision"),
        owner_reference_digest=_str_field(record, "owner_reference_digest"),
        reserved_at=_datetime_field(record, "reserved_at"),
        lease_expires_at=_datetime_field(record, "lease_expires_at"),
        state_changed_at=_datetime_field(record, "state_changed_at"),
        dispatch_started_at=_optional_datetime_field(
            record,
            "dispatch_started_at",
        ),
        evidence_kind=_optional_enum_field(
            record,
            "evidence_kind",
            ReservationEvidenceKind,
        ),
        evidence_digest=_optional_str_field(record, "evidence_digest"),
        terminal_outcome_digest=_optional_str_field(
            record,
            "terminal_outcome_digest",
        ),
        record_digest=_str_field(record, "record_digest"),
        execution_authority=_false_field(record, "execution_authority"),
        effect_verified=_false_field(record, "effect_verified"),
    )


def _exact_mapping(
    value: Mapping[str, object],
    expected_keys: set[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"idempotency reservation {name} fields are invalid")
    return value


def _mapping_field(
    value: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    field = value.get(name)
    if type(field) is not dict:
        raise ValueError(f"idempotency reservation {name} MUST be an object")
    return cast(dict[str, object], field)


def _str_field(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if type(field) is not str:
        raise ValueError(f"idempotency reservation {name} MUST be a string")
    return field


def _schema_version_field(
    value: Mapping[str, object],
) -> Literal["1.0.0"]:
    if _str_field(value, "schema_version") != "1.0.0":
        raise ValueError("idempotency reservation schema version is unsupported")
    return "1.0.0"


def _optional_str_field(
    value: Mapping[str, object],
    name: str,
) -> str | None:
    field = value.get(name)
    if field is None:
        return None
    if type(field) is not str:
        raise ValueError(f"idempotency reservation {name} MUST be a string or null")
    return field


def _int_field(value: Mapping[str, object], name: str) -> int:
    field = value.get(name)
    if type(field) is not int:
        raise ValueError(f"idempotency reservation {name} MUST be an integer")
    return field


def _optional_int_field(
    value: Mapping[str, object],
    name: str,
) -> int | None:
    field = value.get(name)
    if field is None:
        return None
    if type(field) is not int:
        raise ValueError(f"idempotency reservation {name} MUST be an integer or null")
    return field


def _datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime:
    field = _str_field(value, name)
    try:
        parsed = datetime.fromisoformat(field)
    except ValueError as exc:
        raise ValueError(f"idempotency reservation {name} MUST be an ISO 8601 timestamp") from exc
    return _utc(parsed, name)


def _optional_datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime | None:
    field = value.get(name)
    if field is None:
        return None
    return _datetime_field(value, name)


def _enum_field[EnumT: StrEnum](
    value: Mapping[str, object],
    name: str,
    enum_type: type[EnumT],
) -> EnumT:
    field = _str_field(value, name)
    try:
        return enum_type(field)
    except ValueError as exc:
        raise ValueError(f"idempotency reservation {name} is invalid") from exc


def _optional_enum_field[EnumT: StrEnum](
    value: Mapping[str, object],
    name: str,
    enum_type: type[EnumT],
) -> EnumT | None:
    if value.get(name) is None:
        return None
    return _enum_field(value, name, enum_type)


def _false_field(
    value: Mapping[str, object],
    name: str,
) -> Literal[False]:
    field = value.get(name)
    if field is not False:
        raise ValueError(f"idempotency reservation {name} MUST be false")
    return False


__all__ = [
    "reservation_record_from_mapping",
    "reservation_record_to_mapping",
]
