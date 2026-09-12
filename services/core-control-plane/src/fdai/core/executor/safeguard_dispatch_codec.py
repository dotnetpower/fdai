"""Strict JSON codec for durable safeguard dispatch evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, cast

from fdai_service_contracts.execution_safeguards import SafeguardProofBundle

from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
    DispatchTransportState,
    PreReleaseContinuityState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
    SafeguardDispatchObservation,
)
from fdai.core.executor.safeguard_dispatch_identity import (
    PROVENANCE_FIELDS,
    IdentitySchemaVersion,
    SafeguardDispatchEvidenceIdentity,
)
from fdai.core.executor.safeguard_dispatch_start import (
    SafeguardDispatchStartCheckpoint,
)
from fdai.core.executor.safeguard_dispatch_start_codec import (
    dispatch_start_checkpoint_from_mapping,
    dispatch_start_checkpoint_to_mapping,
)


def safeguard_dispatch_record_to_mapping(
    record: SafeguardDispatchEvidenceRecord,
) -> dict[str, object]:
    """Serialize one validated evidence record to canonical JSON values."""

    if type(record) is not SafeguardDispatchEvidenceRecord:
        raise ValueError("safeguard dispatch serializer requires an exact record")
    return {
        "schema_version": record.schema_version,
        "identity": _identity_mapping(record.identity),
        "bundle": record.bundle.model_dump(mode="json"),
        "state": record.state.value,
        "revision": record.revision,
        "prior_record_digest": record.prior_record_digest,
        "dispatch_start_checkpoint": (
            dispatch_start_checkpoint_to_mapping(record.dispatch_start_checkpoint)
            if record.dispatch_start_checkpoint is not None
            else None
        ),
        "dispatch_observation": (
            _observation_mapping(record.dispatch_observation)
            if record.dispatch_observation is not None
            else None
        ),
        "pre_release_checkpoint": (
            _checkpoint_mapping(record.pre_release_checkpoint)
            if record.pre_release_checkpoint is not None
            else None
        ),
        "independent_effect_state": record.independent_effect_state,
        "state_changed_at": record.state_changed_at.isoformat(),
        "record_digest": record.record_digest,
        "execution_authority": record.execution_authority,
        "effect_verified": record.effect_verified,
    }


def safeguard_dispatch_record_from_mapping(
    value: Mapping[str, object],
) -> SafeguardDispatchEvidenceRecord:
    """Parse one exact durable record and rerun all semantic invariants."""

    record = _exact_mapping(
        value,
        {
            "schema_version",
            "identity",
            "bundle",
            "state",
            "revision",
            "prior_record_digest",
            "dispatch_start_checkpoint",
            "dispatch_observation",
            "pre_release_checkpoint",
            "independent_effect_state",
            "state_changed_at",
            "record_digest",
            "execution_authority",
            "effect_verified",
        },
        "record",
    )
    bundle_raw = _mapping_field(record, "bundle")
    return SafeguardDispatchEvidenceRecord(
        schema_version=_schema_version(record),
        identity=_identity_from_mapping(_mapping_field(record, "identity")),
        bundle=SafeguardProofBundle.model_validate(bundle_raw),
        state=_enum_field(
            record,
            "state",
            SafeguardDispatchEvidenceState,
        ),
        revision=_int_field(record, "revision"),
        prior_record_digest=_optional_str_field(
            record,
            "prior_record_digest",
        ),
        dispatch_start_checkpoint=_optional_dispatch_start(record),
        dispatch_observation=_optional_observation(record),
        pre_release_checkpoint=_optional_checkpoint(record),
        independent_effect_state=_pending_field(record),
        state_changed_at=_datetime_field(record, "state_changed_at"),
        record_digest=_str_field(record, "record_digest"),
        execution_authority=_false_field(record, "execution_authority"),
        effect_verified=_false_field(record, "effect_verified"),
    )


def _identity_mapping(
    identity: SafeguardDispatchEvidenceIdentity,
) -> dict[str, object]:
    mapping = _identity_base_mapping(identity)
    if identity.schema_version == "1.0.0":
        return mapping
    mapping["execution_origin"] = identity.execution_origin
    mapping["execution_venue"] = identity.execution_venue
    return mapping


def _identity_base_mapping(
    identity: SafeguardDispatchEvidenceIdentity,
) -> dict[str, object]:
    return {
        "schema_version": identity.schema_version,
        "action_id": identity.action_id,
        "target_digest": identity.target_digest,
        "target_fence_identity_digest": identity.target_fence_identity_digest,
        "target_fence_record_digest": identity.target_fence_record_digest,
        "target_fence_generation": identity.target_fence_generation,
        "target_fence_revision": identity.target_fence_revision,
        "reservation_identity_digest": identity.reservation_identity_digest,
        "reservation_attempt": identity.reservation_attempt,
        "acquisition_receipt_digest": identity.acquisition_receipt_digest,
        "reservation_receipt_digest": identity.reservation_receipt_digest,
        "reservation_record_digest": identity.reservation_record_digest,
        "reservation_revision": identity.reservation_revision,
        "reservation_lease_expires_at": (identity.reservation_lease_expires_at.isoformat()),
        "audit_append_receipt_digest": identity.audit_append_receipt_digest,
        "lock_assessment_digest": identity.lock_assessment_digest,
        "lock_assessment_valid_until": (identity.lock_assessment_valid_until.isoformat()),
        "lock_proof_digest": identity.lock_proof_digest,
        "idempotency_proof_digest": identity.idempotency_proof_digest,
        "audit_intent_proof_digest": identity.audit_intent_proof_digest,
        "pre_bundle_commitment_digest": identity.pre_bundle_commitment_digest,
        "lock_verifier_id": identity.lock_verifier_id,
        "lock_verifier_version": identity.lock_verifier_version,
        "lock_trust_anchor_id": identity.lock_trust_anchor_id,
        "safeguard_bundle_digest": identity.safeguard_bundle_digest,
        "continuity_policy_digest": identity.continuity_policy_digest,
        "execution_path": identity.execution_path,
        "execution_fingerprint": identity.execution_fingerprint,
        "source_revision": identity.source_revision,
        "client_correlation_id": identity.client_correlation_id,
        "sink_idempotency_key": identity.sink_idempotency_key,
        "identity_digest": identity.identity_digest,
        "execution_authority": identity.execution_authority,
        "effect_verification_authority": (identity.effect_verification_authority),
    }


#: Identity keys every revision writes.
_IDENTITY_BASE_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "action_id",
        "target_digest",
        "target_fence_identity_digest",
        "target_fence_record_digest",
        "target_fence_generation",
        "target_fence_revision",
        "reservation_identity_digest",
        "reservation_attempt",
        "acquisition_receipt_digest",
        "reservation_receipt_digest",
        "reservation_record_digest",
        "reservation_revision",
        "reservation_lease_expires_at",
        "audit_append_receipt_digest",
        "lock_assessment_digest",
        "lock_assessment_valid_until",
        "lock_proof_digest",
        "idempotency_proof_digest",
        "audit_intent_proof_digest",
        "pre_bundle_commitment_digest",
        "lock_verifier_id",
        "lock_verifier_version",
        "lock_trust_anchor_id",
        "safeguard_bundle_digest",
        "continuity_policy_digest",
        "execution_path",
        "execution_fingerprint",
        "source_revision",
        "client_correlation_id",
        "sink_idempotency_key",
        "identity_digest",
        "execution_authority",
        "effect_verification_authority",
    }
)


def _identity_from_mapping(
    value: Mapping[str, object],
) -> SafeguardDispatchEvidenceIdentity:
    identity = _exact_mapping(
        value,
        _identity_keys(value),
        "identity",
    )
    return SafeguardDispatchEvidenceIdentity(
        schema_version=_identity_schema_version(identity),
        action_id=_str_field(identity, "action_id"),
        target_digest=_str_field(identity, "target_digest"),
        target_fence_identity_digest=_str_field(
            identity,
            "target_fence_identity_digest",
        ),
        target_fence_record_digest=_str_field(
            identity,
            "target_fence_record_digest",
        ),
        target_fence_generation=_int_field(
            identity,
            "target_fence_generation",
        ),
        target_fence_revision=_int_field(
            identity,
            "target_fence_revision",
        ),
        reservation_identity_digest=_str_field(
            identity,
            "reservation_identity_digest",
        ),
        reservation_attempt=_int_field(identity, "reservation_attempt"),
        acquisition_receipt_digest=_str_field(
            identity,
            "acquisition_receipt_digest",
        ),
        reservation_receipt_digest=_str_field(
            identity,
            "reservation_receipt_digest",
        ),
        reservation_record_digest=_str_field(
            identity,
            "reservation_record_digest",
        ),
        reservation_revision=_int_field(identity, "reservation_revision"),
        reservation_lease_expires_at=_datetime_field(
            identity,
            "reservation_lease_expires_at",
        ),
        audit_append_receipt_digest=_str_field(
            identity,
            "audit_append_receipt_digest",
        ),
        lock_assessment_digest=_str_field(
            identity,
            "lock_assessment_digest",
        ),
        lock_assessment_valid_until=_datetime_field(
            identity,
            "lock_assessment_valid_until",
        ),
        lock_proof_digest=_str_field(identity, "lock_proof_digest"),
        idempotency_proof_digest=_str_field(
            identity,
            "idempotency_proof_digest",
        ),
        audit_intent_proof_digest=_str_field(
            identity,
            "audit_intent_proof_digest",
        ),
        pre_bundle_commitment_digest=_str_field(
            identity,
            "pre_bundle_commitment_digest",
        ),
        lock_verifier_id=_str_field(identity, "lock_verifier_id"),
        lock_verifier_version=_str_field(
            identity,
            "lock_verifier_version",
        ),
        lock_trust_anchor_id=_str_field(
            identity,
            "lock_trust_anchor_id",
        ),
        safeguard_bundle_digest=_str_field(
            identity,
            "safeguard_bundle_digest",
        ),
        continuity_policy_digest=_str_field(
            identity,
            "continuity_policy_digest",
        ),
        execution_path=_str_field(identity, "execution_path"),
        execution_fingerprint=_str_field(
            identity,
            "execution_fingerprint",
        ),
        source_revision=_str_field(identity, "source_revision"),
        client_correlation_id=_str_field(
            identity,
            "client_correlation_id",
        ),
        sink_idempotency_key=_str_field(
            identity,
            "sink_idempotency_key",
        ),
        identity_digest=_str_field(identity, "identity_digest"),
        execution_origin=_optional_str_field(identity, "execution_origin"),
        execution_venue=_optional_str_field(identity, "execution_venue"),
        execution_authority=_false_field(
            identity,
            "execution_authority",
        ),
        effect_verification_authority=_false_field(
            identity,
            "effect_verification_authority",
        ),
    )


def _identity_keys(value: Mapping[str, object]) -> set[str]:
    """Return the exact key set the stored identity revision must carry.

    Decoding stays strict per revision: a ``1.0.0`` body may not smuggle a
    provenance key, and a ``1.1.0`` body may not omit one.  An unreadable
    or unknown revision falls back to the newest key set so the error
    surfaces as an unsupported schema rather than a key-set mismatch.
    """

    raw = value.get("schema_version")
    if raw == "1.0.0":
        return set(_IDENTITY_BASE_KEYS)
    return set(_IDENTITY_BASE_KEYS | PROVENANCE_FIELDS)


def _identity_schema_version(
    value: Mapping[str, object],
) -> IdentitySchemaVersion:
    raw = _str_field(value, "schema_version")
    if raw == "1.0.0":
        return "1.0.0"
    if raw == "1.1.0":
        return "1.1.0"
    raise ValueError("safeguard dispatch schema version is unsupported")


def _observation_mapping(
    observation: SafeguardDispatchObservation,
) -> dict[str, object]:
    return {
        "schema_version": observation.schema_version,
        "evidence_identity_digest": observation.evidence_identity_digest,
        "bundle_record_digest": observation.bundle_record_digest,
        "bundle_record_revision": observation.bundle_record_revision,
        "dispatch_start_record_digest": (observation.dispatch_start_record_digest),
        "dispatch_start_record_revision": (observation.dispatch_start_record_revision),
        "in_flight_reservation_receipt_digest": (observation.in_flight_reservation_receipt_digest),
        "target_fence_record_digest": observation.target_fence_record_digest,
        "target_fence_revision": observation.target_fence_revision,
        "transport_state": observation.transport_state.value,
        "sink_state": observation.sink_state.value,
        "sink_operation_reference_digest": (observation.sink_operation_reference_digest),
        "authoritative_status_digest": observation.authoritative_status_digest,
        "dispatch_started_at": observation.dispatch_started_at.isoformat(),
        "observed_at": observation.observed_at.isoformat(),
        "observation_digest": observation.observation_digest,
        "execution_authority": observation.execution_authority,
        "effect_verified": observation.effect_verified,
    }


def _observation_from_mapping(
    value: Mapping[str, object],
) -> SafeguardDispatchObservation:
    observation = _exact_mapping(
        value,
        {
            "schema_version",
            "evidence_identity_digest",
            "bundle_record_digest",
            "bundle_record_revision",
            "dispatch_start_record_digest",
            "dispatch_start_record_revision",
            "in_flight_reservation_receipt_digest",
            "target_fence_record_digest",
            "target_fence_revision",
            "transport_state",
            "sink_state",
            "sink_operation_reference_digest",
            "authoritative_status_digest",
            "dispatch_started_at",
            "observed_at",
            "observation_digest",
            "execution_authority",
            "effect_verified",
        },
        "dispatch observation",
    )
    return SafeguardDispatchObservation(
        schema_version=_schema_version(observation),
        evidence_identity_digest=_str_field(
            observation,
            "evidence_identity_digest",
        ),
        bundle_record_digest=_str_field(
            observation,
            "bundle_record_digest",
        ),
        bundle_record_revision=_int_field(
            observation,
            "bundle_record_revision",
        ),
        dispatch_start_record_digest=_str_field(
            observation,
            "dispatch_start_record_digest",
        ),
        dispatch_start_record_revision=_int_field(
            observation,
            "dispatch_start_record_revision",
        ),
        in_flight_reservation_receipt_digest=_str_field(
            observation,
            "in_flight_reservation_receipt_digest",
        ),
        target_fence_record_digest=_str_field(
            observation,
            "target_fence_record_digest",
        ),
        target_fence_revision=_int_field(
            observation,
            "target_fence_revision",
        ),
        transport_state=_enum_field(
            observation,
            "transport_state",
            DispatchTransportState,
        ),
        sink_state=_enum_field(
            observation,
            "sink_state",
            AuthoritativeSinkState,
        ),
        sink_operation_reference_digest=_optional_str_field(
            observation,
            "sink_operation_reference_digest",
        ),
        authoritative_status_digest=_optional_str_field(
            observation,
            "authoritative_status_digest",
        ),
        dispatch_started_at=_datetime_field(
            observation,
            "dispatch_started_at",
        ),
        observed_at=_datetime_field(observation, "observed_at"),
        observation_digest=_str_field(
            observation,
            "observation_digest",
        ),
        execution_authority=_false_field(
            observation,
            "execution_authority",
        ),
        effect_verified=_false_field(observation, "effect_verified"),
    )


def _checkpoint_mapping(
    checkpoint: PreReleaseOwnershipCheckpoint,
) -> dict[str, object]:
    return {
        "schema_version": checkpoint.schema_version,
        "evidence_identity_digest": checkpoint.evidence_identity_digest,
        "continuity_state": checkpoint.continuity_state.value,
        "acquisition_receipt_digest": checkpoint.acquisition_receipt_digest,
        "assessment_digest": checkpoint.assessment_digest,
        "verifier_id": checkpoint.verifier_id,
        "verifier_version": checkpoint.verifier_version,
        "trust_anchor_id": checkpoint.trust_anchor_id,
        "evaluated_at": (
            checkpoint.evaluated_at.isoformat() if checkpoint.evaluated_at is not None else None
        ),
        "valid_until": (
            checkpoint.valid_until.isoformat() if checkpoint.valid_until is not None else None
        ),
        "rejection_reasons": list(checkpoint.rejection_reasons),
        "unproven_reason": (
            checkpoint.unproven_reason.value if checkpoint.unproven_reason is not None else None
        ),
        "observed_at": checkpoint.observed_at.isoformat(),
        "checkpoint_digest": checkpoint.checkpoint_digest,
        "execution_authority": checkpoint.execution_authority,
        "effect_verified": checkpoint.effect_verified,
    }


def _checkpoint_from_mapping(
    value: Mapping[str, object],
) -> PreReleaseOwnershipCheckpoint:
    checkpoint = _exact_mapping(
        value,
        {
            "schema_version",
            "evidence_identity_digest",
            "continuity_state",
            "acquisition_receipt_digest",
            "assessment_digest",
            "verifier_id",
            "verifier_version",
            "trust_anchor_id",
            "evaluated_at",
            "valid_until",
            "rejection_reasons",
            "unproven_reason",
            "observed_at",
            "checkpoint_digest",
            "execution_authority",
            "effect_verified",
        },
        "pre-release checkpoint",
    )
    reasons = checkpoint.get("rejection_reasons")
    if type(reasons) is not list or any(type(reason) is not str for reason in reasons):
        raise ValueError("safeguard dispatch rejection_reasons MUST be a string array")
    return PreReleaseOwnershipCheckpoint(
        schema_version=_schema_version(checkpoint),
        evidence_identity_digest=_str_field(
            checkpoint,
            "evidence_identity_digest",
        ),
        continuity_state=_enum_field(
            checkpoint,
            "continuity_state",
            PreReleaseContinuityState,
        ),
        acquisition_receipt_digest=_str_field(
            checkpoint,
            "acquisition_receipt_digest",
        ),
        assessment_digest=_optional_str_field(
            checkpoint,
            "assessment_digest",
        ),
        verifier_id=_optional_str_field(checkpoint, "verifier_id"),
        verifier_version=_optional_str_field(
            checkpoint,
            "verifier_version",
        ),
        trust_anchor_id=_optional_str_field(checkpoint, "trust_anchor_id"),
        evaluated_at=_optional_datetime_field(checkpoint, "evaluated_at"),
        valid_until=_optional_datetime_field(checkpoint, "valid_until"),
        rejection_reasons=tuple(cast(list[str], reasons)),
        unproven_reason=_optional_enum_field(
            checkpoint,
            "unproven_reason",
            ContinuityUnprovenReason,
        ),
        observed_at=_datetime_field(checkpoint, "observed_at"),
        checkpoint_digest=_str_field(checkpoint, "checkpoint_digest"),
        execution_authority=_false_field(
            checkpoint,
            "execution_authority",
        ),
        effect_verified=_false_field(checkpoint, "effect_verified"),
    )


def _optional_observation(
    record: Mapping[str, object],
) -> SafeguardDispatchObservation | None:
    raw = record.get("dispatch_observation")
    if raw is None:
        return None
    if type(raw) is not dict:
        raise ValueError("safeguard dispatch observation MUST be an object")
    return _observation_from_mapping(cast(dict[str, object], raw))


def _optional_dispatch_start(
    record: Mapping[str, object],
) -> SafeguardDispatchStartCheckpoint | None:
    raw = record.get("dispatch_start_checkpoint")
    if raw is None:
        return None
    if type(raw) is not dict:
        raise ValueError("safeguard dispatch-start checkpoint MUST be an object")
    return dispatch_start_checkpoint_from_mapping(cast(dict[str, object], raw))


def _optional_checkpoint(
    record: Mapping[str, object],
) -> PreReleaseOwnershipCheckpoint | None:
    raw = record.get("pre_release_checkpoint")
    if raw is None:
        return None
    if type(raw) is not dict:
        raise ValueError("safeguard pre-release checkpoint MUST be an object")
    return _checkpoint_from_mapping(cast(dict[str, object], raw))


def _exact_mapping(
    value: Mapping[str, object],
    expected_keys: set[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise ValueError(f"safeguard dispatch {name} fields are invalid")
    return value


def _mapping_field(
    value: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    field = value.get(name)
    if type(field) is not dict:
        raise ValueError(f"safeguard dispatch {name} MUST be an object")
    return cast(dict[str, object], field)


def _str_field(value: Mapping[str, object], name: str) -> str:
    field = value.get(name)
    if type(field) is not str:
        raise ValueError(f"safeguard dispatch {name} MUST be a string")
    return field


def _optional_str_field(
    value: Mapping[str, object],
    name: str,
) -> str | None:
    field = value.get(name)
    if field is None:
        return None
    if type(field) is not str:
        raise ValueError(f"safeguard dispatch {name} MUST be a string or null")
    return field


def _int_field(value: Mapping[str, object], name: str) -> int:
    field = value.get(name)
    if type(field) is not int:
        raise ValueError(f"safeguard dispatch {name} MUST be an integer")
    return field


def _datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime:
    field = _str_field(value, name)
    try:
        parsed = datetime.fromisoformat(field)
    except ValueError as exc:
        raise ValueError(f"safeguard dispatch {name} MUST be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"safeguard dispatch {name} MUST include a timezone")
    return parsed.astimezone(UTC)


def _optional_datetime_field(
    value: Mapping[str, object],
    name: str,
) -> datetime | None:
    if value.get(name) is None:
        return None
    return _datetime_field(value, name)


def _schema_version(
    value: Mapping[str, object],
) -> Literal["1.0.0"]:
    if _str_field(value, "schema_version") != "1.0.0":
        raise ValueError("safeguard dispatch schema version is unsupported")
    return "1.0.0"


def _pending_field(value: Mapping[str, object]) -> Literal["pending"]:
    if _str_field(value, "independent_effect_state") != "pending":
        raise ValueError("safeguard dispatch independent effect state is invalid")
    return "pending"


def _enum_field[EnumT: StrEnum](
    value: Mapping[str, object],
    name: str,
    enum_type: type[EnumT],
) -> EnumT:
    raw = _str_field(value, name)
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ValueError(f"safeguard dispatch {name} is invalid") from exc


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
    if value.get(name) is not False:
        raise ValueError(f"safeguard dispatch {name} MUST be false")
    return False


__all__ = [
    "safeguard_dispatch_record_from_mapping",
    "safeguard_dispatch_record_to_mapping",
]
