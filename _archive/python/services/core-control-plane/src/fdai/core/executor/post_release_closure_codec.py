"""Strict JSON codec for durable post-release closure records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from fdai.core.executor.idempotency_reservation import ReservationState
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureIdentity,
    PostReleaseClosureOutcome,
    PostReleaseClosurePhase,
    PostReleaseClosureRecord,
    PostReleaseContinuityState,
    PostReleaseReconciliationEvidence,
    ReconciliationEvidenceKind,
    ReconciliationOutcome,
)
from fdai.core.executor.target_dispatch_fence import TargetDispatchFenceState
from fdai.shared.providers.resource_lock import ResourceLockReleaseState


def post_release_closure_to_mapping(
    record: PostReleaseClosureRecord,
) -> dict[str, object]:
    """Serialize one validated closure record to canonical JSON values."""

    if type(record) is not PostReleaseClosureRecord:
        raise ValueError("post-release closure serializer requires an exact record")
    return {
        "schema_version": record.schema_version,
        "identity": _identity_to_mapping(record.identity),
        "revision": record.revision,
        "prior_record_digest": record.prior_record_digest,
        "phase": record.phase.value,
        "outcome": record.outcome.value,
        "pre_release_record_digest": record.pre_release_record_digest,
        "pre_release_record_revision": record.pre_release_record_revision,
        "prior_reservation_record_digest": record.prior_reservation_record_digest,
        "reservation_record_digest": record.reservation_record_digest,
        "reservation_state": record.reservation_state.value,
        "reservation_revision": record.reservation_revision,
        "prior_fence_record_digest": record.prior_fence_record_digest,
        "fence_record_digest": record.fence_record_digest,
        "fence_state": record.fence_state.value,
        "fence_revision": record.fence_revision,
        "release_state": record.release_state.value,
        "release_receipt_digest": record.release_receipt_digest,
        "release_attestation_digest": record.release_attestation_digest,
        "release_observed_at": (
            record.release_observed_at.isoformat()
            if record.release_observed_at is not None
            else None
        ),
        "release_recorded_at": record.release_recorded_at.isoformat(),
        "continuity_state": record.continuity_state.value,
        "continuity_evidence_digest": record.continuity_evidence_digest,
        "authoritative_status_digest": record.authoritative_status_digest,
        "reconciliation_evidence": (
            _reconciliation_to_mapping(record.reconciliation_evidence)
            if record.reconciliation_evidence is not None
            else None
        ),
        "independent_effect_state": record.independent_effect_state,
        "audit_closure_digest": record.audit_closure_digest,
        "outbox_event_id": record.outbox_event_id,
        "closed_at": record.closed_at.isoformat(),
        "record_digest": record.record_digest,
        "execution_authority": record.execution_authority,
        "effect_verified": record.effect_verified,
    }


def post_release_closure_from_mapping(
    value: Mapping[str, object],
) -> PostReleaseClosureRecord:
    """Parse one exact closure record and rerun all semantic invariants."""

    record = _exact(
        value,
        {
            "schema_version",
            "identity",
            "revision",
            "prior_record_digest",
            "phase",
            "outcome",
            "pre_release_record_digest",
            "pre_release_record_revision",
            "prior_reservation_record_digest",
            "reservation_record_digest",
            "reservation_state",
            "reservation_revision",
            "prior_fence_record_digest",
            "fence_record_digest",
            "fence_state",
            "fence_revision",
            "release_state",
            "release_receipt_digest",
            "release_attestation_digest",
            "release_observed_at",
            "release_recorded_at",
            "continuity_state",
            "continuity_evidence_digest",
            "authoritative_status_digest",
            "reconciliation_evidence",
            "independent_effect_state",
            "audit_closure_digest",
            "outbox_event_id",
            "closed_at",
            "record_digest",
            "execution_authority",
            "effect_verified",
        },
        "record",
    )
    identity = _identity_from_mapping(_mapping(record, "identity"))
    reconciliation_raw = record["reconciliation_evidence"]
    if reconciliation_raw is not None and type(reconciliation_raw) is not dict:
        raise ValueError("post-release reconciliation evidence MUST be an object or null")
    return PostReleaseClosureRecord(
        schema_version=_schema(record),
        identity=identity,
        revision=_int(record, "revision"),
        prior_record_digest=_optional_str(record, "prior_record_digest"),
        phase=PostReleaseClosurePhase(_str(record, "phase")),
        outcome=PostReleaseClosureOutcome(_str(record, "outcome")),
        pre_release_record_digest=_str(record, "pre_release_record_digest"),
        pre_release_record_revision=_int(record, "pre_release_record_revision"),
        prior_reservation_record_digest=_str(
            record,
            "prior_reservation_record_digest",
        ),
        reservation_record_digest=_str(record, "reservation_record_digest"),
        reservation_state=ReservationState(_str(record, "reservation_state")),
        reservation_revision=_int(record, "reservation_revision"),
        prior_fence_record_digest=_str(record, "prior_fence_record_digest"),
        fence_record_digest=_str(record, "fence_record_digest"),
        fence_state=TargetDispatchFenceState(_str(record, "fence_state")),
        fence_revision=_int(record, "fence_revision"),
        release_state=ResourceLockReleaseState(_str(record, "release_state")),
        release_receipt_digest=_str(record, "release_receipt_digest"),
        release_attestation_digest=_str(record, "release_attestation_digest"),
        release_observed_at=_optional_datetime(record, "release_observed_at"),
        release_recorded_at=_datetime(record, "release_recorded_at"),
        continuity_state=PostReleaseContinuityState(_str(record, "continuity_state")),
        continuity_evidence_digest=_str(record, "continuity_evidence_digest"),
        authoritative_status_digest=_optional_str(
            record,
            "authoritative_status_digest",
        ),
        reconciliation_evidence=(
            _reconciliation_from_mapping(reconciliation_raw)
            if isinstance(reconciliation_raw, Mapping)
            else None
        ),
        independent_effect_state=_pending(record),
        audit_closure_digest=_str(record, "audit_closure_digest"),
        outbox_event_id=_str(record, "outbox_event_id"),
        closed_at=_datetime(record, "closed_at"),
        record_digest=_str(record, "record_digest"),
        execution_authority=_false(record, "execution_authority"),
        effect_verified=_false(record, "effect_verified"),
    )


def _identity_to_mapping(identity: PostReleaseClosureIdentity) -> dict[str, object]:
    return {
        "schema_version": identity.schema_version,
        "closure_key": identity.closure_key,
        "reservation_identity_digest": identity.reservation_identity_digest,
        "reservation_attempt": identity.reservation_attempt,
        "target_digest": identity.target_digest,
        "target_fence_generation": identity.target_fence_generation,
        "evidence_identity_digest": identity.evidence_identity_digest,
        "audit_append_receipt_digest": identity.audit_append_receipt_digest,
        "client_correlation_id": identity.client_correlation_id,
        "sink_idempotency_key": identity.sink_idempotency_key,
        "identity_digest": identity.identity_digest,
        "execution_authority": identity.execution_authority,
        "effect_verification_authority": identity.effect_verification_authority,
    }


def _identity_from_mapping(value: Mapping[str, object]) -> PostReleaseClosureIdentity:
    identity = _exact(
        value,
        {
            "schema_version",
            "closure_key",
            "reservation_identity_digest",
            "reservation_attempt",
            "target_digest",
            "target_fence_generation",
            "evidence_identity_digest",
            "audit_append_receipt_digest",
            "client_correlation_id",
            "sink_idempotency_key",
            "identity_digest",
            "execution_authority",
            "effect_verification_authority",
        },
        "identity",
    )
    return PostReleaseClosureIdentity(
        schema_version=_schema(identity),
        closure_key=_str(identity, "closure_key"),
        reservation_identity_digest=_str(identity, "reservation_identity_digest"),
        reservation_attempt=_int(identity, "reservation_attempt"),
        target_digest=_str(identity, "target_digest"),
        target_fence_generation=_int(identity, "target_fence_generation"),
        evidence_identity_digest=_str(identity, "evidence_identity_digest"),
        audit_append_receipt_digest=_str(
            identity,
            "audit_append_receipt_digest",
        ),
        client_correlation_id=_str(identity, "client_correlation_id"),
        sink_idempotency_key=_str(identity, "sink_idempotency_key"),
        identity_digest=_str(identity, "identity_digest"),
        execution_authority=_false(identity, "execution_authority"),
        effect_verification_authority=_false(
            identity,
            "effect_verification_authority",
        ),
    )


def _reconciliation_to_mapping(
    evidence: PostReleaseReconciliationEvidence,
) -> dict[str, object]:
    return {
        "schema_version": evidence.schema_version,
        "kind": evidence.kind.value,
        "outcome": evidence.outcome.value,
        "target_digest": evidence.target_digest,
        "target_fence_generation": evidence.target_fence_generation,
        "evidence_identity_digest": evidence.evidence_identity_digest,
        "source_id": evidence.source_id,
        "source_version": evidence.source_version,
        "trust_anchor_id": evidence.trust_anchor_id,
        "evidence_digest": evidence.evidence_digest,
        "observed_at": evidence.observed_at.isoformat(),
        "persisted_at": evidence.persisted_at.isoformat(),
        "append_receipt_digest": evidence.append_receipt_digest,
        "synthetic": evidence.synthetic,
        "execution_authority": evidence.execution_authority,
        "effect_verification_authority": evidence.effect_verification_authority,
    }


def _reconciliation_from_mapping(
    value: Mapping[str, object],
) -> PostReleaseReconciliationEvidence:
    evidence = _exact(
        value,
        {
            "schema_version",
            "kind",
            "outcome",
            "target_digest",
            "target_fence_generation",
            "evidence_identity_digest",
            "source_id",
            "source_version",
            "trust_anchor_id",
            "evidence_digest",
            "observed_at",
            "persisted_at",
            "append_receipt_digest",
            "synthetic",
            "execution_authority",
            "effect_verification_authority",
        },
        "reconciliation evidence",
    )
    return PostReleaseReconciliationEvidence(
        schema_version=_schema(evidence),
        kind=ReconciliationEvidenceKind(_str(evidence, "kind")),
        outcome=ReconciliationOutcome(_str(evidence, "outcome")),
        target_digest=_str(evidence, "target_digest"),
        target_fence_generation=_int(evidence, "target_fence_generation"),
        evidence_identity_digest=_str(evidence, "evidence_identity_digest"),
        source_id=_str(evidence, "source_id"),
        source_version=_str(evidence, "source_version"),
        trust_anchor_id=_str(evidence, "trust_anchor_id"),
        evidence_digest=_str(evidence, "evidence_digest"),
        observed_at=_datetime(evidence, "observed_at"),
        persisted_at=_datetime(evidence, "persisted_at"),
        append_receipt_digest=_str(evidence, "append_receipt_digest"),
        synthetic=_false(evidence, "synthetic"),
        execution_authority=_false(evidence, "execution_authority"),
        effect_verification_authority=_false(
            evidence,
            "effect_verification_authority",
        ),
    )


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    name: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"post-release closure {name} fields are invalid")
    return value


def _mapping(value: Mapping[str, object], name: str) -> Mapping[str, object]:
    item = value[name]
    if type(item) is not dict:
        raise ValueError(f"post-release closure {name} MUST be an object")
    return item


def _str(value: Mapping[str, object], name: str) -> str:
    item = value[name]
    if type(item) is not str:
        raise ValueError(f"post-release closure {name} MUST be a string")
    return item


def _optional_str(value: Mapping[str, object], name: str) -> str | None:
    item = value[name]
    if item is not None and type(item) is not str:
        raise ValueError(f"post-release closure {name} MUST be a string or null")
    return item


def _int(value: Mapping[str, object], name: str) -> int:
    item = value[name]
    if type(item) is not int:
        raise ValueError(f"post-release closure {name} MUST be an integer")
    return item


def _datetime(value: Mapping[str, object], name: str) -> datetime:
    item = value[name]
    if type(item) is not str:
        raise ValueError(f"post-release closure {name} MUST be a timestamp")
    parsed = datetime.fromisoformat(item)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"post-release closure {name} MUST include a timezone")
    return parsed.astimezone(UTC)


def _optional_datetime(
    value: Mapping[str, object],
    name: str,
) -> datetime | None:
    return None if value[name] is None else _datetime(value, name)


def _false(value: Mapping[str, object], name: str) -> Literal[False]:
    if value[name] is not False:
        raise ValueError(f"post-release closure {name} MUST be false")
    return False


def _schema(value: Mapping[str, object]) -> Literal["1.0.0"]:
    if value["schema_version"] != "1.0.0":
        raise ValueError("unsupported post-release closure schema")
    return "1.0.0"


def _pending(value: Mapping[str, object]) -> Literal["pending"]:
    if value["independent_effect_state"] != "pending":
        raise ValueError("post-release closure independent effect state MUST be pending")
    return "pending"


__all__ = [
    "post_release_closure_from_mapping",
    "post_release_closure_to_mapping",
]
