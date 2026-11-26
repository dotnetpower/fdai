"""Provider-neutral atomic post-release closure and reconciliation plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    ReservationState,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest,
    utc,
    validate_digest,
    validate_text,
    validate_utc,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)
from fdai.shared.providers.resource_lock import (
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)


class PostReleaseClosurePhase(StrEnum):
    """Whether a record closes release or reconciles a quarantine."""

    INITIAL = "initial"
    RECONCILIATION = "reconciliation"


class PostReleaseClosureOutcome(StrEnum):
    """Target-wide terminal disposition after one closure transaction."""

    RESOLVED = "resolved"
    QUARANTINED = "quarantined"


class PostReleaseContinuityState(StrEnum):
    """Whether ownership-through-terminal-state evidence is complete."""

    CONTINUITY = "continuity"
    CONTINUITY_UNPROVEN = "continuity_unproven"


class ReconciliationEvidenceKind(StrEnum):
    """Authority-separated evidence accepted by quarantine reconciliation."""

    AUTHORITATIVE_SINK_STATUS = "authoritative_sink_status"
    INDEPENDENT_EFFECT = "independent_effect"


class ReconciliationOutcome(StrEnum):
    """Terminal evidence outcomes that may resolve quarantine."""

    SINK_COMMITTED = "sink_committed"
    SINK_NOT_COMMITTED = "sink_not_committed"
    SINK_IRREVOCABLY_NOT_ACCEPTED = "sink_irrevocably_not_accepted"
    EFFECT_VERIFIED = "effect_verified"
    EFFECT_MISMATCH = "effect_mismatch"


@dataclass(frozen=True, slots=True)
class PostReleaseReconciliationEvidence:
    """Durably appended evidence for one exact quarantined generation."""

    schema_version: Literal["1.0.0"]
    kind: ReconciliationEvidenceKind
    outcome: ReconciliationOutcome
    target_digest: str
    target_fence_generation: int
    evidence_identity_digest: str
    source_id: str
    source_version: str
    trust_anchor_id: str
    evidence_digest: str
    observed_at: datetime
    persisted_at: datetime
    append_receipt_digest: str
    synthetic: Literal[False] = False
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported post-release reconciliation evidence schema")
        if (
            self.synthetic is not False
            or self.execution_authority is not False
            or self.effect_verification_authority is not False
        ):
            raise ValueError("post-release reconciliation evidence MUST NOT grant authority")
        if type(self.kind) is not ReconciliationEvidenceKind:
            raise ValueError("post-release reconciliation evidence kind is invalid")
        if type(self.outcome) is not ReconciliationOutcome:
            raise ValueError("post-release reconciliation outcome is invalid")
        sink_outcomes = {
            ReconciliationOutcome.SINK_COMMITTED,
            ReconciliationOutcome.SINK_NOT_COMMITTED,
            ReconciliationOutcome.SINK_IRREVOCABLY_NOT_ACCEPTED,
        }
        if (self.kind is ReconciliationEvidenceKind.AUTHORITATIVE_SINK_STATUS) is not (
            self.outcome in sink_outcomes
        ):
            raise ValueError("post-release reconciliation authority mismatched outcome")
        validate_digest("target_digest", self.target_digest)
        validate_digest("evidence_identity_digest", self.evidence_identity_digest)
        validate_digest("evidence_digest", self.evidence_digest)
        validate_digest("append_receipt_digest", self.append_receipt_digest)
        if type(self.target_fence_generation) is not int or self.target_fence_generation < 1:
            raise ValueError("post-release reconciliation generation MUST be positive")
        validate_text("source_id", self.source_id)
        validate_text("source_version", self.source_version)
        validate_text("trust_anchor_id", self.trust_anchor_id)
        validate_utc("observed_at", self.observed_at)
        validate_utc("persisted_at", self.persisted_at)
        if self.persisted_at < self.observed_at:
            raise ValueError("post-release reconciliation persistence predates observation")

    @classmethod
    def create(
        cls,
        *,
        kind: ReconciliationEvidenceKind,
        outcome: ReconciliationOutcome,
        target_digest: str,
        target_fence_generation: int,
        evidence_identity_digest: str,
        source_id: str,
        source_version: str,
        trust_anchor_id: str,
        evidence_digest: str,
        observed_at: datetime,
        persisted_at: datetime,
        append_receipt_digest: str,
    ) -> Self:
        """Create one exact-generation durable reconciliation receipt."""

        if cls is not PostReleaseReconciliationEvidence:
            raise TypeError("post-release reconciliation evidence does not support subclasses")
        return cls(
            schema_version="1.0.0",
            kind=kind,
            outcome=outcome,
            target_digest=target_digest,
            target_fence_generation=target_fence_generation,
            evidence_identity_digest=evidence_identity_digest,
            source_id=source_id,
            source_version=source_version,
            trust_anchor_id=trust_anchor_id,
            evidence_digest=evidence_digest,
            observed_at=utc(observed_at, "observed_at"),
            persisted_at=utc(persisted_at, "persisted_at"),
            append_receipt_digest=append_receipt_digest,
        )


@dataclass(frozen=True, slots=True)
class PostReleaseClosureIdentity:
    """Stable attempt and generation identity for idempotent closure."""

    schema_version: Literal["1.0.0"]
    closure_key: str
    reservation_identity_digest: str
    reservation_attempt: int
    target_digest: str
    target_fence_generation: int
    evidence_identity_digest: str
    audit_append_receipt_digest: str
    client_correlation_id: str
    sink_idempotency_key: str
    identity_digest: str
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported post-release closure identity schema")
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("post-release closure identity MUST NOT grant authority")
        for digest_name, digest_value in (
            ("closure_key", self.closure_key),
            ("reservation_identity_digest", self.reservation_identity_digest),
            ("target_digest", self.target_digest),
            ("evidence_identity_digest", self.evidence_identity_digest),
            ("audit_append_receipt_digest", self.audit_append_receipt_digest),
            ("identity_digest", self.identity_digest),
        ):
            validate_digest(digest_name, digest_value)
        if type(self.reservation_attempt) is not int or self.reservation_attempt < 1:
            raise ValueError("post-release reservation attempt MUST be positive")
        if type(self.target_fence_generation) is not int or self.target_fence_generation < 1:
            raise ValueError("post-release target generation MUST be positive")
        validate_text("client_correlation_id", self.client_correlation_id)
        validate_text("sink_idempotency_key", self.sink_idempotency_key)
        expected_key = content_digest(
            {
                "domain": "post-release-closure-key",
                "reservation_identity_digest": self.reservation_identity_digest,
                "reservation_attempt": self.reservation_attempt,
            }
        )
        if self.closure_key != expected_key:
            raise ValueError("post-release closure key mismatched reservation attempt")
        expected_digest = payload_digest(
            asdict(self),
            "post-release-closure-identity",
            digest_field="identity_digest",
        )
        if self.identity_digest != expected_digest:
            raise ValueError("post-release closure identity digest mismatched")

    @classmethod
    def from_pre_release(
        cls,
        pre_release_record: SafeguardDispatchEvidenceRecord,
    ) -> Self:
        """Derive closure identity only from durable pre-release evidence."""

        if (
            type(pre_release_record) is not SafeguardDispatchEvidenceRecord
            or pre_release_record.state is not SafeguardDispatchEvidenceState.PRE_RELEASE
        ):
            raise ValueError("post-release closure requires pre-release evidence")
        evidence = pre_release_record.identity
        closure_key = content_digest(
            {
                "domain": "post-release-closure-key",
                "reservation_identity_digest": evidence.reservation_identity_digest,
                "reservation_attempt": evidence.reservation_attempt,
            }
        )
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "closure_key": closure_key,
            "reservation_identity_digest": evidence.reservation_identity_digest,
            "reservation_attempt": evidence.reservation_attempt,
            "target_digest": evidence.target_digest,
            "target_fence_generation": evidence.target_fence_generation,
            "evidence_identity_digest": evidence.identity_digest,
            "audit_append_receipt_digest": evidence.audit_append_receipt_digest,
            "client_correlation_id": evidence.client_correlation_id,
            "sink_idempotency_key": evidence.sink_idempotency_key,
            "execution_authority": False,
            "effect_verification_authority": False,
        }
        values["identity_digest"] = payload_digest(
            values,
            "post-release-closure-identity",
            digest_field="identity_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PostReleaseClosureRecord:
    """Durable no-authority terminal evidence for one closure revision."""

    schema_version: Literal["1.0.0"]
    identity: PostReleaseClosureIdentity
    revision: int
    prior_record_digest: str | None
    phase: PostReleaseClosurePhase
    outcome: PostReleaseClosureOutcome
    pre_release_record_digest: str
    pre_release_record_revision: int
    prior_reservation_record_digest: str
    reservation_record_digest: str
    reservation_state: ReservationState
    reservation_revision: int
    prior_fence_record_digest: str
    fence_record_digest: str
    fence_state: TargetDispatchFenceState
    fence_revision: int
    release_state: ResourceLockReleaseState
    release_receipt_digest: str
    release_attestation_digest: str
    release_observed_at: datetime | None
    release_recorded_at: datetime
    continuity_state: PostReleaseContinuityState
    continuity_evidence_digest: str
    authoritative_status_digest: str | None
    reconciliation_evidence: PostReleaseReconciliationEvidence | None
    independent_effect_state: Literal["pending"]
    audit_closure_digest: str
    outbox_event_id: str
    closed_at: datetime
    record_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported post-release closure record schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("post-release closure record MUST NOT grant authority")
        if type(self.identity) is not PostReleaseClosureIdentity:
            raise ValueError("post-release closure record requires exact identity")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("post-release closure revision MUST be positive")
        if self.revision == 1:
            if self.prior_record_digest is not None or (
                self.phase is not PostReleaseClosurePhase.INITIAL
            ):
                raise ValueError("initial post-release closure predecessor is invalid")
        else:
            if self.prior_record_digest is None or (
                self.phase is not PostReleaseClosurePhase.RECONCILIATION
            ):
                raise ValueError("reconciled post-release closure predecessor is invalid")
            validate_digest("prior_record_digest", self.prior_record_digest)
        if type(self.outcome) is not PostReleaseClosureOutcome:
            raise ValueError("post-release closure outcome is invalid")
        if type(self.continuity_state) is not PostReleaseContinuityState:
            raise ValueError("post-release continuity state is invalid")
        if type(self.reservation_state) is not ReservationState:
            raise ValueError("post-release reservation state is invalid")
        if type(self.fence_state) is not TargetDispatchFenceState:
            raise ValueError("post-release fence state is invalid")
        if type(self.release_state) is not ResourceLockReleaseState:
            raise ValueError("post-release release state is invalid")
        for digest_name, digest_value in (
            ("pre_release_record_digest", self.pre_release_record_digest),
            ("prior_reservation_record_digest", self.prior_reservation_record_digest),
            ("reservation_record_digest", self.reservation_record_digest),
            ("prior_fence_record_digest", self.prior_fence_record_digest),
            ("fence_record_digest", self.fence_record_digest),
            ("release_receipt_digest", self.release_receipt_digest),
            ("release_attestation_digest", self.release_attestation_digest),
            ("continuity_evidence_digest", self.continuity_evidence_digest),
            ("audit_closure_digest", self.audit_closure_digest),
            ("outbox_event_id", self.outbox_event_id),
            ("record_digest", self.record_digest),
        ):
            validate_digest(digest_name, digest_value)
        if self.authoritative_status_digest is not None:
            validate_digest(
                "authoritative_status_digest",
                self.authoritative_status_digest,
            )
        for revision_name, revision_value in (
            ("pre_release_record_revision", self.pre_release_record_revision),
            ("reservation_revision", self.reservation_revision),
            ("fence_revision", self.fence_revision),
        ):
            if type(revision_value) is not int or revision_value < 1:
                raise ValueError(f"post-release {revision_name} MUST be positive")
        if self.release_observed_at is not None:
            validate_utc("release_observed_at", self.release_observed_at)
        validate_utc("release_recorded_at", self.release_recorded_at)
        validate_utc("closed_at", self.closed_at)
        if self.closed_at < self.release_recorded_at or (
            self.release_observed_at is not None
            and self.release_observed_at > self.release_recorded_at
        ):
            raise ValueError("post-release closure chronology is invalid")
        if (
            self.release_state is not ResourceLockReleaseState.UNKNOWN
            and self.release_observed_at is None
        ):
            raise ValueError("known post-release release state requires observation")
        if self.independent_effect_state != "pending":
            raise ValueError("post-release closure cannot claim independent effect verification")
        _validate_record_shape(self)
        if self.audit_closure_digest != _audit_digest(self):
            raise ValueError("post-release audit closure digest mismatched")
        if self.outbox_event_id != _outbox_event_id(self):
            raise ValueError("post-release outbox identity mismatched")
        expected_record_digest = payload_digest(
            asdict(self),
            "post-release-closure-record",
            digest_field="record_digest",
        )
        if self.record_digest != expected_record_digest:
            raise ValueError("post-release closure record digest mismatched")


def audit_closure_mapping(record: PostReleaseClosureRecord) -> dict[str, object]:
    """Return the append-only terminal audit entry for one closure revision."""

    return {
        "schema_version": "1.0.0",
        "kind": "executor.post_release_closure",
        "audit_phase": "post_release",
        "actor": "fdai.core.executor",
        "closure_key": record.identity.closure_key,
        "closure_revision": record.revision,
        "reservation_identity_digest": record.identity.reservation_identity_digest,
        "reservation_attempt": record.identity.reservation_attempt,
        "target_digest": record.identity.target_digest,
        "target_fence_generation": record.identity.target_fence_generation,
        "pre_effect_audit_append_receipt_digest": (record.identity.audit_append_receipt_digest),
        "outcome": record.outcome.value,
        "continuity_state": record.continuity_state.value,
        "continuity_evidence_digest": record.continuity_evidence_digest,
        "release_receipt_digest": record.release_receipt_digest,
        "reservation_record_digest": record.reservation_record_digest,
        "fence_record_digest": record.fence_record_digest,
        "recorded_at": record.closed_at.isoformat(),
        "audit_closure_digest": record.audit_closure_digest,
        "execution_authority": False,
        "effect_verified": False,
    }


def closure_outbox_mapping(record: PostReleaseClosureRecord) -> dict[str, object]:
    """Return the deterministic no-authority outbox event."""

    return {
        "schema_version": "1.0.0",
        "event_type": "executor.post_release_closure.v1",
        "event_id": record.outbox_event_id,
        "partition_key": record.identity.target_digest,
        "closure_key": record.identity.closure_key,
        "closure_revision": record.revision,
        "outcome": record.outcome.value,
        "continuity_state": record.continuity_state.value,
        "closure_record_digest": record.record_digest,
        "recorded_at": record.closed_at.isoformat(),
        "execution_authority": False,
        "effect_verified": False,
    }


def create_post_release_closure_record(
    *,
    identity: PostReleaseClosureIdentity,
    revision: int,
    prior_record_digest: str | None,
    phase: PostReleaseClosurePhase,
    outcome: PostReleaseClosureOutcome,
    pre_release_record: SafeguardDispatchEvidenceRecord,
    prior_reservation: IdempotencyReservationRecord,
    reservation: IdempotencyReservationRecord,
    prior_fence: TargetDispatchFenceRecord,
    fence: TargetDispatchFenceRecord,
    release_receipt: ResourceLockReleaseReceipt,
    continuity_state: PostReleaseContinuityState,
    continuity_evidence_digest: str,
    authoritative_status_digest: str | None,
    reconciliation_evidence: PostReleaseReconciliationEvidence | None,
    closed_at: datetime,
) -> PostReleaseClosureRecord:
    """Create one digest-bound durable closure record."""

    audit_closure_digest = _audit_digest_values(
        closure_key=identity.closure_key,
        revision=revision,
        outcome=outcome,
        continuity_evidence_digest=continuity_evidence_digest,
        release_receipt_digest=release_receipt.receipt_digest,
        reservation_record_digest=reservation.record_digest,
        fence_record_digest=fence.record_digest,
        closed_at=closed_at,
    )
    outbox_event_id = _outbox_event_id_values(
        closure_key=identity.closure_key,
        revision=revision,
    )
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "identity": identity,
        "revision": revision,
        "prior_record_digest": prior_record_digest,
        "phase": phase,
        "outcome": outcome,
        "pre_release_record_digest": pre_release_record.record_digest,
        "pre_release_record_revision": pre_release_record.revision,
        "prior_reservation_record_digest": prior_reservation.record_digest,
        "reservation_record_digest": reservation.record_digest,
        "reservation_state": reservation.state,
        "reservation_revision": reservation.revision,
        "prior_fence_record_digest": prior_fence.record_digest,
        "fence_record_digest": fence.record_digest,
        "fence_state": fence.state,
        "fence_revision": fence.revision,
        "release_state": release_receipt.state,
        "release_receipt_digest": release_receipt.receipt_digest,
        "release_attestation_digest": release_receipt.provider_attestation_digest,
        "release_observed_at": release_receipt.observed_at,
        "release_recorded_at": release_receipt.recorded_at,
        "continuity_state": continuity_state,
        "continuity_evidence_digest": continuity_evidence_digest,
        "authoritative_status_digest": authoritative_status_digest,
        "reconciliation_evidence": reconciliation_evidence,
        "independent_effect_state": "pending",
        "audit_closure_digest": audit_closure_digest,
        "outbox_event_id": outbox_event_id,
        "closed_at": closed_at,
        "execution_authority": False,
        "effect_verified": False,
    }
    values["record_digest"] = payload_digest(
        values,
        "post-release-closure-record",
        digest_field="record_digest",
    )
    return PostReleaseClosureRecord(**values)  # type: ignore[arg-type]


def _validate_record_shape(record: PostReleaseClosureRecord) -> None:
    resolved = record.outcome is PostReleaseClosureOutcome.RESOLVED
    if resolved is not (record.fence_state is TargetDispatchFenceState.RESOLVED):
        raise ValueError("post-release closure outcome mismatched target fence")
    if resolved:
        if record.reservation_state is not ReservationState.TERMINAL:
            raise ValueError("resolved post-release closure requires terminal reservation")
    elif (
        record.fence_state is not TargetDispatchFenceState.QUARANTINED
        or record.reservation_state is not ReservationState.OUTCOME_UNKNOWN
    ):
        raise ValueError("quarantined closure requires unknown reservation and fence quarantine")
    if record.phase is PostReleaseClosurePhase.INITIAL:
        if record.reconciliation_evidence is not None:
            raise ValueError("initial post-release closure cannot contain reconciliation evidence")
        if resolved and record.continuity_state is not PostReleaseContinuityState.CONTINUITY:
            raise ValueError("initial resolved closure requires proven continuity")
    elif (
        type(record.reconciliation_evidence) is not PostReleaseReconciliationEvidence
        or not resolved
    ):
        raise ValueError("post-release reconciliation requires evidence and resolved outcome")


def _audit_digest(record: PostReleaseClosureRecord) -> str:
    return _audit_digest_values(
        closure_key=record.identity.closure_key,
        revision=record.revision,
        outcome=record.outcome,
        continuity_evidence_digest=record.continuity_evidence_digest,
        release_receipt_digest=record.release_receipt_digest,
        reservation_record_digest=record.reservation_record_digest,
        fence_record_digest=record.fence_record_digest,
        closed_at=record.closed_at,
    )


def _outbox_event_id(record: PostReleaseClosureRecord) -> str:
    return _outbox_event_id_values(
        closure_key=record.identity.closure_key,
        revision=record.revision,
    )


def _audit_digest_values(
    *,
    closure_key: str,
    revision: int,
    outcome: PostReleaseClosureOutcome,
    continuity_evidence_digest: str,
    release_receipt_digest: str,
    reservation_record_digest: str,
    fence_record_digest: str,
    closed_at: datetime,
) -> str:
    return content_digest(
        {
            "domain": "executor-post-release-audit-closure",
            "closure_key": closure_key,
            "revision": revision,
            "outcome": outcome.value,
            "continuity_evidence_digest": continuity_evidence_digest,
            "release_receipt_digest": release_receipt_digest,
            "reservation_record_digest": reservation_record_digest,
            "fence_record_digest": fence_record_digest,
            "closed_at": closed_at.isoformat(),
        }
    )


def _outbox_event_id_values(*, closure_key: str, revision: int) -> str:
    return content_digest(
        {
            "domain": "executor-post-release-outbox-event",
            "closure_key": closure_key,
            "revision": revision,
        }
    )


__all__ = [
    "PostReleaseClosureIdentity",
    "PostReleaseClosureOutcome",
    "PostReleaseClosurePhase",
    "PostReleaseClosureRecord",
    "PostReleaseContinuityState",
    "PostReleaseReconciliationEvidence",
    "ReconciliationEvidenceKind",
    "ReconciliationOutcome",
    "audit_closure_mapping",
    "closure_outbox_mapping",
    "create_post_release_closure_record",
]
