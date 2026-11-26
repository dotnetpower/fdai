"""Strict JSON codec for durable target dispatch fence records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal, cast

from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)


def target_dispatch_fence_to_mapping(
    record: TargetDispatchFenceRecord,
) -> dict[str, object]:
    """Serialize one validated fence record to canonical JSON values."""

    if type(record) is not TargetDispatchFenceRecord:
        raise ValueError("target dispatch fence serializer requires an exact record")
    return {
        "schema_version": record.schema_version,
        "identity": {
            "schema_version": record.identity.schema_version,
            "target_digest": record.identity.target_digest,
            "reservation_identity_digest": (record.identity.reservation_identity_digest),
            "reservation_attempt": record.identity.reservation_attempt,
            "acquisition_receipt_digest": (record.identity.acquisition_receipt_digest),
            "acquisition_acquired_at": (record.identity.acquisition_acquired_at.isoformat()),
            "continuity_policy_digest": (record.identity.continuity_policy_digest),
            "continuity_strategy": record.identity.continuity_strategy,
            "generation": record.identity.generation,
            "client_correlation_id": record.identity.client_correlation_id,
            "sink_idempotency_key": record.identity.sink_idempotency_key,
            "identity_digest": record.identity.identity_digest,
            "execution_authority": record.identity.execution_authority,
            "effect_verification_authority": (record.identity.effect_verification_authority),
        },
        "state": record.state.value,
        "revision": record.revision,
        "prior_record_digest": record.prior_record_digest,
        "audit_append_receipt_digest": record.audit_append_receipt_digest,
        "safeguard_bundle_digest": record.safeguard_bundle_digest,
        "state_changed_at": record.state_changed_at.isoformat(),
        "no_dispatch_evidence_digest": record.no_dispatch_evidence_digest,
        "resolution_evidence_digest": record.resolution_evidence_digest,
        "record_digest": record.record_digest,
        "execution_authority": record.execution_authority,
        "effect_verified": record.effect_verified,
    }


def target_dispatch_fence_from_mapping(
    value: Mapping[str, object],
) -> TargetDispatchFenceRecord:
    """Parse one exact durable record and rerun all semantic invariants."""

    record = _exact_mapping(
        value,
        {
            "schema_version",
            "identity",
            "state",
            "revision",
            "prior_record_digest",
            "audit_append_receipt_digest",
            "safeguard_bundle_digest",
            "state_changed_at",
            "no_dispatch_evidence_digest",
            "resolution_evidence_digest",
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
            "target_digest",
            "reservation_identity_digest",
            "reservation_attempt",
            "acquisition_receipt_digest",
            "acquisition_acquired_at",
            "continuity_policy_digest",
            "continuity_strategy",
            "generation",
            "client_correlation_id",
            "sink_idempotency_key",
            "identity_digest",
            "execution_authority",
            "effect_verification_authority",
        },
        "identity",
    )
    identity = TargetDispatchFenceIdentity(
        schema_version=_schema_version(identity_raw),
        target_digest=_str_field(identity_raw, "target_digest"),
        reservation_identity_digest=_str_field(
            identity_raw,
            "reservation_identity_digest",
        ),
        reservation_attempt=_int_field(identity_raw, "reservation_attempt"),
        acquisition_receipt_digest=_str_field(
            identity_raw,
            "acquisition_receipt_digest",
        ),
        acquisition_acquired_at=_datetime_field(
            identity_raw,
            "acquisition_acquired_at",
        ),
        continuity_policy_digest=_str_field(
            identity_raw,
            "continuity_policy_digest",
        ),
        continuity_strategy=_continuity_strategy(identity_raw),
        generation=_int_field(identity_raw, "generation"),
        client_correlation_id=_str_field(
            identity_raw,
            "client_correlation_id",
        ),
        sink_idempotency_key=_str_field(
            identity_raw,
            "sink_idempotency_key",
        ),
        identity_digest=_str_field(identity_raw, "identity_digest"),
        execution_authority=_false_field(
            identity_raw,
            "execution_authority",
        ),
        effect_verification_authority=_false_field(
            identity_raw,
            "effect_verification_authority",
        ),
    )
    return TargetDispatchFenceRecord(
        schema_version=_schema_version(record),
        identity=identity,
        state=_state_field(record),
        revision=_int_field(record, "revision"),
        prior_record_digest=_optional_str_field(
            record,
            "prior_record_digest",
        ),
        audit_append_receipt_digest=_optional_str_field(
            record,
            "audit_append_receipt_digest",
        ),
        safeguard_bundle_digest=_optional_str_field(
            record,
            "safeguard_bundle_digest",
        ),
        state_changed_at=_datetime_field(record, "state_changed_at"),
        no_dispatch_evidence_digest=_optional_str_field(
            record,
            "no_dispatch_evidence_digest",
        ),
        resolution_evidence_digest=_optional_str_field(
            record,
            "resolution_evidence_digest",
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
        raise ValueError(f"target dispatch fence {name} fields are invalid")
    return value


def _mapping_field(
    value: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    field = value.get(name)
    if type(field) is not dict:
        raise ValueError(f"target dispatch fence {name} MUST be an object")
    return cast(dict[str, object], field)


def _str_field(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if type(field) is not str:
        raise ValueError(f"target dispatch fence {name} MUST be a string")
    return field


def _optional_str_field(
    value: Mapping[str, object],
    name: str,
) -> str | None:
    field = value.get(name)
    if field is None:
        return None
    if type(field) is not str:
        raise ValueError(f"target dispatch fence {name} MUST be a string or null")
    return field


def _int_field(value: Mapping[str, object], name: str) -> int:
    field = value.get(name)
    if type(field) is not int:
        raise ValueError(f"target dispatch fence {name} MUST be an integer")
    return field


def _datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime:
    field = _str_field(value, name)
    try:
        parsed = datetime.fromisoformat(field)
    except ValueError as exc:
        raise ValueError(f"target dispatch fence {name} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"target dispatch fence {name} MUST include a timezone")
    return parsed.astimezone(UTC)


def _schema_version(
    value: Mapping[str, object],
) -> Literal["1.0.0"]:
    if _str_field(value, "schema_version") != "1.0.0":
        raise ValueError("target dispatch fence schema version is unsupported")
    return "1.0.0"


def _continuity_strategy(
    value: Mapping[str, object],
) -> Literal["quarantined_reconciliation"]:
    if _str_field(value, "continuity_strategy") != "quarantined_reconciliation":
        raise ValueError("target dispatch fence continuity strategy is unsupported")
    return "quarantined_reconciliation"


def _state_field(value: Mapping[str, object]) -> TargetDispatchFenceState:
    raw = _str_field(value, "state")
    try:
        return TargetDispatchFenceState(raw)
    except ValueError as exc:
        raise ValueError("target dispatch fence state is invalid") from exc


def _false_field(
    value: Mapping[str, object],
    name: str,
) -> Literal[False]:
    if value.get(name) is not False:
        raise ValueError(f"target dispatch fence {name} MUST be false")
    return False


__all__ = [
    "target_dispatch_fence_from_mapping",
    "target_dispatch_fence_to_mapping",
]
