"""Durable safeguard bundle, dispatch observation, and pre-release checkpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Self

from fdai_service_contracts.execution_safeguards import SafeguardProofBundle

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationTransitionReceipt,
)
from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_identity import (
    PROVENANCE_FIELDS,
    SafeguardDispatchEvidenceIdentity,
)
from fdai.core.executor.safeguard_dispatch_start import (
    SafeguardDispatchStartCheckpoint,
)
from fdai.core.executor.safeguard_dispatch_support import (
    payload_digest as _payload_digest,
)
from fdai.core.executor.safeguard_dispatch_support import (
    utc as _utc,
)
from fdai.core.executor.safeguard_dispatch_support import (
    validate_digest as _validate_digest,
)
from fdai.core.executor.safeguard_dispatch_support import (
    validate_text as _validate_text,
)
from fdai.core.executor.safeguard_dispatch_support import (
    validate_utc as _validate_utc,
)
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceRecord,
)
from fdai.shared.providers.resource_lock import (
    LiveLockOwnershipAssessment,
    require_current_lock_ownership,
)

if TYPE_CHECKING:
    from fdai.core.executor.safeguard_dispatch_store import (
        SafeguardDispatchTransitionReceipt,
    )


class SafeguardDispatchEvidenceState(StrEnum):
    """Monotonic evidence lifecycle before target-lock release."""

    BUNDLE_PERSISTED = "bundle_persisted"
    DISPATCH_STARTED = "dispatch_started"
    DISPATCH_OBSERVED = "dispatch_observed"
    PRE_RELEASE = "pre_release"


class DispatchTransportState(StrEnum):
    """Transport knowledge independent from authoritative sink state."""

    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AuthoritativeSinkState(StrEnum):
    """Authoritative sink knowledge without independent effect verification."""

    UNOBSERVED = "unobserved"
    ACCEPTED = "accepted"
    NOT_ACCEPTED = "not_accepted"
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    UNKNOWN = "unknown"


class PreReleaseContinuityState(StrEnum):
    """Whether fresh current ownership was proven after dispatch handling."""

    CURRENT = "current"
    CONTINUITY_UNPROVEN = "continuity_unproven"


class ContinuityUnprovenReason(StrEnum):
    """Why a fresh pre-release ownership prerequisite was unavailable."""

    ASSESSMENT_FAILED = "assessment_failed"
    CALLBACK_CANCELLED = "callback_cancelled"
    CALLBACK_FAILED = "callback_failed"
    INELIGIBLE = "ineligible"
    MISSING = "missing"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SafeguardDispatchObservation:
    """Immutable transport and authoritative sink observation."""

    schema_version: Literal["1.0.0"]
    evidence_identity_digest: str
    bundle_record_digest: str
    bundle_record_revision: int
    dispatch_start_record_digest: str
    dispatch_start_record_revision: int
    in_flight_reservation_receipt_digest: str
    target_fence_record_digest: str
    target_fence_revision: int
    transport_state: DispatchTransportState
    sink_state: AuthoritativeSinkState
    sink_operation_reference_digest: str | None
    authoritative_status_digest: str | None
    dispatch_started_at: datetime
    observed_at: datetime
    observation_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard dispatch observation schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("safeguard dispatch observation MUST NOT grant authority")
        _validate_digest("evidence_identity_digest", self.evidence_identity_digest)
        _validate_digest("bundle_record_digest", self.bundle_record_digest)
        _validate_digest(
            "in_flight_reservation_receipt_digest",
            self.in_flight_reservation_receipt_digest,
        )
        if type(self.bundle_record_revision) is not int or self.bundle_record_revision < 1:
            raise ValueError("safeguard dispatch bundle record revision MUST be positive")
        _validate_digest(
            "dispatch_start_record_digest",
            self.dispatch_start_record_digest,
        )
        if (
            type(self.dispatch_start_record_revision) is not int
            or self.dispatch_start_record_revision < 1
        ):
            raise ValueError("safeguard dispatch-start record revision MUST be positive")
        _validate_digest(
            "target_fence_record_digest",
            self.target_fence_record_digest,
        )
        if type(self.target_fence_revision) is not int or self.target_fence_revision < 1:
            raise ValueError("safeguard dispatch fence revision MUST be positive")
        if type(self.transport_state) is not DispatchTransportState:
            raise ValueError("safeguard dispatch transport state is invalid")
        if type(self.sink_state) is not AuthoritativeSinkState:
            raise ValueError("safeguard dispatch sink state is invalid")
        for digest_name, digest_value in (
            (
                "sink_operation_reference_digest",
                self.sink_operation_reference_digest,
            ),
            ("authoritative_status_digest", self.authoritative_status_digest),
        ):
            if digest_value is not None:
                _validate_digest(digest_name, digest_value)
        if (
            self.sink_state
            in {
                AuthoritativeSinkState.ACCEPTED,
                AuthoritativeSinkState.NOT_ACCEPTED,
                AuthoritativeSinkState.COMMITTED,
                AuthoritativeSinkState.NOT_COMMITTED,
            }
            and self.authoritative_status_digest is None
        ):
            raise ValueError("authoritative sink state requires status evidence")
        if (
            self.sink_state
            in {
                AuthoritativeSinkState.ACCEPTED,
                AuthoritativeSinkState.COMMITTED,
            }
            and self.sink_operation_reference_digest is None
        ):
            raise ValueError("accepted sink state requires operation reference")
        if (
            self.sink_state
            in {
                AuthoritativeSinkState.UNOBSERVED,
                AuthoritativeSinkState.UNKNOWN,
            }
            and self.authoritative_status_digest is not None
        ):
            raise ValueError("unknown sink state cannot carry authoritative status")
        _validate_utc("dispatch_started_at", self.dispatch_started_at)
        _validate_utc("observed_at", self.observed_at)
        if self.observed_at < self.dispatch_started_at:
            raise ValueError("dispatch observation predates dispatch start")
        _validate_digest("observation_digest", self.observation_digest)
        if self.observation_digest != _content_digest(
            self,
            "safeguard-dispatch-observation",
        ):
            raise ValueError("safeguard dispatch observation digest mismatched")

    @classmethod
    def create(
        cls,
        *,
        dispatch_start_record: SafeguardDispatchEvidenceRecord,
        transport_state: DispatchTransportState,
        sink_state: AuthoritativeSinkState,
        sink_operation_reference_digest: str | None,
        authoritative_status_digest: str | None,
        observed_at: datetime,
    ) -> Self:
        """Create one observation from a durable pre-I/O start checkpoint."""

        if cls is not SafeguardDispatchObservation:
            raise TypeError("safeguard dispatch observation does not support subclasses")
        if (
            type(dispatch_start_record) is not SafeguardDispatchEvidenceRecord
            or dispatch_start_record.state is not SafeguardDispatchEvidenceState.DISPATCH_STARTED
            or dispatch_start_record.dispatch_start_checkpoint is None
        ):
            raise ValueError("safeguard dispatch observation requires durable dispatch start")
        evidence_identity = dispatch_start_record.identity
        start = dispatch_start_record.dispatch_start_checkpoint
        normalized_at = _utc(observed_at, "observed_at")
        if normalized_at < start.dispatch_started_at:
            raise ValueError("safeguard dispatch observation predates in-flight fence")
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_identity_digest": evidence_identity.identity_digest,
            "bundle_record_digest": start.bundle_record_digest,
            "bundle_record_revision": start.bundle_record_revision,
            "dispatch_start_record_digest": dispatch_start_record.record_digest,
            "dispatch_start_record_revision": dispatch_start_record.revision,
            "in_flight_reservation_receipt_digest": (
                start.in_flight_reservation_receipt.receipt_digest
            ),
            "target_fence_record_digest": start.in_flight_fence.record_digest,
            "target_fence_revision": start.in_flight_fence.revision,
            "transport_state": transport_state,
            "sink_state": sink_state,
            "sink_operation_reference_digest": sink_operation_reference_digest,
            "authoritative_status_digest": authoritative_status_digest,
            "dispatch_started_at": start.dispatch_started_at,
            "observed_at": normalized_at,
            "execution_authority": False,
            "effect_verified": False,
        }
        values["observation_digest"] = _payload_digest(
            values,
            "safeguard-dispatch-observation",
            digest_field="observation_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PreReleaseOwnershipCheckpoint:
    """Fresh post-dispatch ownership evidence or explicit continuity unknown."""

    schema_version: Literal["1.0.0"]
    evidence_identity_digest: str
    continuity_state: PreReleaseContinuityState
    acquisition_receipt_digest: str
    assessment_digest: str | None
    verifier_id: str | None
    verifier_version: str | None
    trust_anchor_id: str | None
    evaluated_at: datetime | None
    valid_until: datetime | None
    rejection_reasons: tuple[str, ...]
    unproven_reason: ContinuityUnprovenReason | None
    observed_at: datetime
    checkpoint_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported pre-release ownership checkpoint schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("pre-release ownership checkpoint MUST NOT grant authority")
        _validate_digest("evidence_identity_digest", self.evidence_identity_digest)
        if type(self.continuity_state) is not PreReleaseContinuityState:
            raise ValueError("pre-release continuity state is invalid")
        _validate_digest("acquisition_receipt_digest", self.acquisition_receipt_digest)
        if self.assessment_digest is not None:
            _validate_digest("assessment_digest", self.assessment_digest)
        for identity_name, identity_value in (
            ("verifier_id", self.verifier_id),
            ("verifier_version", self.verifier_version),
            ("trust_anchor_id", self.trust_anchor_id),
        ):
            if identity_value is not None:
                _validate_text(identity_name, identity_value)
        for timestamp_name, timestamp_value in (
            ("evaluated_at", self.evaluated_at),
            ("valid_until", self.valid_until),
        ):
            if timestamp_value is not None:
                _validate_utc(timestamp_name, timestamp_value)
        if (
            type(self.rejection_reasons) is not tuple
            or any(type(reason) is not str or not reason for reason in self.rejection_reasons)
            or self.rejection_reasons != tuple(sorted(set(self.rejection_reasons)))
        ):
            raise ValueError("pre-release rejection reasons MUST be canonical")
        if (
            self.unproven_reason is not None
            and type(self.unproven_reason) is not ContinuityUnprovenReason
        ):
            raise ValueError("pre-release continuity reason is invalid")
        _validate_utc("observed_at", self.observed_at)
        from fdai.core.executor.safeguard_dispatch_validation import validate_checkpoint_shape

        validate_checkpoint_shape(self)
        _validate_digest("checkpoint_digest", self.checkpoint_digest)
        if self.checkpoint_digest != _content_digest(
            self,
            "pre-release-ownership-checkpoint",
        ):
            raise ValueError("pre-release ownership checkpoint digest mismatched")

    @classmethod
    def from_assessment(
        cls,
        *,
        evidence_identity: SafeguardDispatchEvidenceIdentity,
        assessment: LiveLockOwnershipAssessment,
        not_before: datetime,
        observed_at: datetime,
    ) -> Self:
        """Persist a fresh assessment as current or explicitly unproven."""

        if cls is not PreReleaseOwnershipCheckpoint:
            raise TypeError("pre-release ownership checkpoint does not support subclasses")
        if type(evidence_identity) is not SafeguardDispatchEvidenceIdentity:
            raise ValueError("pre-release checkpoint requires exact identity")
        if type(assessment) is not LiveLockOwnershipAssessment:
            raise ValueError("pre-release checkpoint requires exact assessment")
        if (
            assessment.acquisition_receipt.receipt_digest
            != evidence_identity.acquisition_receipt_digest
        ):
            raise ValueError("pre-release assessment changed acquisition")
        normalized_boundary = _utc(not_before, "not_before")
        normalized_at = _utc(observed_at, "observed_at")
        reason: ContinuityUnprovenReason | None = None
        if (
            assessment.verifier_id != evidence_identity.lock_verifier_id
            or assessment.verifier_version != evidence_identity.lock_verifier_version
            or assessment.trust_anchor_id != evidence_identity.lock_trust_anchor_id
        ):
            reason = ContinuityUnprovenReason.ASSESSMENT_FAILED
        elif assessment.evaluated_at < normalized_boundary:
            reason = ContinuityUnprovenReason.STALE
        else:
            try:
                require_current_lock_ownership(
                    assessment,
                    observed_at=normalized_at,
                )
            except ValueError:
                reason = (
                    ContinuityUnprovenReason.INELIGIBLE
                    if not assessment.eligible
                    else ContinuityUnprovenReason.STALE
                )
        return cls._create(
            evidence_identity=evidence_identity,
            assessment=assessment,
            observed_at=normalized_at,
            unproven_reason=reason,
        )

    @classmethod
    def unproven(
        cls,
        *,
        evidence_identity: SafeguardDispatchEvidenceIdentity,
        reason: ContinuityUnprovenReason,
        observed_at: datetime,
    ) -> Self:
        """Record missing or failed assessment without a success shape."""

        if type(reason) is not ContinuityUnprovenReason:
            raise ValueError("pre-release continuity reason is invalid")
        return cls._create(
            evidence_identity=evidence_identity,
            assessment=None,
            observed_at=_utc(observed_at, "observed_at"),
            unproven_reason=reason,
        )

    @classmethod
    def _create(
        cls,
        *,
        evidence_identity: SafeguardDispatchEvidenceIdentity,
        assessment: LiveLockOwnershipAssessment | None,
        observed_at: datetime,
        unproven_reason: ContinuityUnprovenReason | None,
    ) -> Self:
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "evidence_identity_digest": evidence_identity.identity_digest,
            "continuity_state": (
                PreReleaseContinuityState.CURRENT
                if unproven_reason is None
                else PreReleaseContinuityState.CONTINUITY_UNPROVEN
            ),
            "acquisition_receipt_digest": (evidence_identity.acquisition_receipt_digest),
            "assessment_digest": (assessment.assessment_digest if assessment is not None else None),
            "verifier_id": (assessment.verifier_id if assessment is not None else None),
            "verifier_version": (assessment.verifier_version if assessment is not None else None),
            "trust_anchor_id": (assessment.trust_anchor_id if assessment is not None else None),
            "evaluated_at": (assessment.evaluated_at if assessment is not None else None),
            "valid_until": (assessment.valid_until if assessment is not None else None),
            "rejection_reasons": (
                tuple(reason.value for reason in assessment.rejection_reasons)
                if assessment is not None
                else ()
            ),
            "unproven_reason": unproven_reason,
            "observed_at": observed_at,
            "execution_authority": False,
            "effect_verified": False,
        }
        values["checkpoint_digest"] = _payload_digest(
            values,
            "pre-release-ownership-checkpoint",
            digest_field="checkpoint_digest",
        )
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SafeguardDispatchEvidenceRecord:
    """Immutable current evidence record for one target-fence generation."""

    schema_version: Literal["1.0.0"]
    identity: SafeguardDispatchEvidenceIdentity
    bundle: SafeguardProofBundle
    state: SafeguardDispatchEvidenceState
    revision: int
    prior_record_digest: str | None
    dispatch_start_checkpoint: SafeguardDispatchStartCheckpoint | None
    dispatch_observation: SafeguardDispatchObservation | None
    pre_release_checkpoint: PreReleaseOwnershipCheckpoint | None
    independent_effect_state: Literal["pending"]
    state_changed_at: datetime
    record_digest: str
    execution_authority: Literal[False] = False
    effect_verified: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != "1.0.0":
            raise ValueError("unsupported safeguard dispatch evidence record schema")
        if self.execution_authority is not False or self.effect_verified is not False:
            raise ValueError("safeguard dispatch evidence record MUST NOT grant authority")
        if type(self.identity) is not SafeguardDispatchEvidenceIdentity:
            raise ValueError("safeguard dispatch evidence requires exact identity")
        if type(self.bundle) is not SafeguardProofBundle:
            raise ValueError("safeguard dispatch evidence requires exact bundle")
        if self.bundle.bundle_digest != self.identity.safeguard_bundle_digest:
            raise ValueError("safeguard dispatch evidence bundle changed")
        if type(self.state) is not SafeguardDispatchEvidenceState:
            raise ValueError("safeguard dispatch evidence state is invalid")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("safeguard dispatch evidence revision MUST be positive")
        if self.revision == 1:
            if self.prior_record_digest is not None:
                raise ValueError("initial safeguard dispatch evidence has predecessor")
        else:
            if self.prior_record_digest is None:
                raise ValueError("safeguard dispatch evidence transition lacks predecessor")
            _validate_digest("prior_record_digest", self.prior_record_digest)
        if (
            self.dispatch_start_checkpoint is not None
            and type(self.dispatch_start_checkpoint) is not SafeguardDispatchStartCheckpoint
        ):
            raise ValueError("safeguard dispatch-start checkpoint is invalid")
        if (
            self.dispatch_observation is not None
            and type(self.dispatch_observation) is not SafeguardDispatchObservation
        ):
            raise ValueError("safeguard dispatch observation is invalid")
        if (
            self.pre_release_checkpoint is not None
            and type(self.pre_release_checkpoint) is not PreReleaseOwnershipCheckpoint
        ):
            raise ValueError("safeguard pre-release checkpoint is invalid")
        if (
            type(self.independent_effect_state) is not str
            or self.independent_effect_state != "pending"
        ):
            raise ValueError("independent effect verification MUST start pending")
        _validate_utc("state_changed_at", self.state_changed_at)
        from fdai.core.executor.safeguard_dispatch_validation import validate_record_shape

        validate_record_shape(self)
        _validate_digest("record_digest", self.record_digest)
        if self.record_digest != _content_digest(
            self,
            "safeguard-dispatch-evidence-record",
        ):
            raise ValueError("safeguard dispatch evidence record digest mismatched")

    @classmethod
    def create_bundle_persisted(
        cls,
        *,
        preparing_fence: TargetDispatchFenceRecord,
        persistence_context: SafeguardBundlePersistenceContext,
        bundle: SafeguardProofBundle,
        persisted_at: datetime,
    ) -> SafeguardDispatchEvidenceRecord:
        """Create the durable exact-bundle state before in-flight dispatch."""

        if cls is not SafeguardDispatchEvidenceRecord:
            raise TypeError("safeguard dispatch evidence record does not support subclasses")
        identity = SafeguardDispatchEvidenceIdentity.create(
            preparing_fence=preparing_fence,
            persistence_context=persistence_context,
            bundle=bundle,
        )
        normalized_at = _utc(persisted_at, "persisted_at")
        if (
            normalized_at < bundle.recorded_at
            or normalized_at < preparing_fence.state_changed_at
            or normalized_at >= identity.reservation_lease_expires_at
            or normalized_at >= identity.lock_assessment_valid_until
        ):
            raise ValueError("safeguard bundle persistence is backdated")
        return _build_record(
            identity=identity,
            bundle=bundle,
            state=SafeguardDispatchEvidenceState.BUNDLE_PERSISTED,
            revision=1,
            prior_record_digest=None,
            state_changed_at=normalized_at,
        )


def record_dispatch_start(
    record: SafeguardDispatchEvidenceRecord,
    *,
    bundle_persistence_receipt: SafeguardDispatchTransitionReceipt,
    in_flight_reservation_receipt: IdempotencyReservationTransitionReceipt,
    prepared_fence: TargetDispatchFenceRecord,
    in_flight_fence: TargetDispatchFenceRecord,
    dispatch_started_at: datetime,
    changed_at: datetime,
) -> SafeguardDispatchEvidenceRecord:
    """Persist exact dispatch lineage before transport I/O can begin."""

    if record.state is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED:
        raise ValueError("safeguard dispatch evidence is not bundle-persisted")
    start = SafeguardDispatchStartCheckpoint.create(
        bundle_persistence_receipt=bundle_persistence_receipt,
        in_flight_reservation_receipt=in_flight_reservation_receipt,
        prepared_fence=prepared_fence,
        in_flight_fence=in_flight_fence,
        dispatch_started_at=dispatch_started_at,
    )
    if (
        bundle_persistence_receipt.record != record
        or start.evidence_identity_digest != record.identity.identity_digest
    ):
        raise ValueError("safeguard dispatch start changed persisted bundle")
    normalized_at = _utc(changed_at, "changed_at")
    if normalized_at < start.dispatch_started_at or normalized_at < record.state_changed_at:
        raise ValueError("safeguard dispatch-start transition is backdated")
    return _build_record(
        identity=record.identity,
        bundle=record.bundle,
        state=SafeguardDispatchEvidenceState.DISPATCH_STARTED,
        revision=record.revision + 1,
        prior_record_digest=record.record_digest,
        dispatch_start_checkpoint=start,
        state_changed_at=normalized_at,
    )


def record_dispatch_observation(
    record: SafeguardDispatchEvidenceRecord,
    *,
    observation: SafeguardDispatchObservation,
    changed_at: datetime,
) -> SafeguardDispatchEvidenceRecord:
    """Bind immutable post-dispatch transport and sink evidence."""

    if record.state is not SafeguardDispatchEvidenceState.DISPATCH_STARTED:
        raise ValueError("safeguard dispatch evidence has no durable dispatch start")
    if observation.evidence_identity_digest != record.identity.identity_digest:
        raise ValueError("safeguard dispatch observation changed identity")
    if (
        observation.dispatch_start_record_digest != record.record_digest
        or observation.dispatch_start_record_revision != record.revision
    ):
        raise ValueError("safeguard dispatch observation changed dispatch start")
    normalized_at = _utc(changed_at, "changed_at")
    if normalized_at < observation.observed_at or normalized_at < record.state_changed_at:
        raise ValueError("safeguard dispatch observation transition is backdated")
    return _build_record(
        identity=record.identity,
        bundle=record.bundle,
        state=SafeguardDispatchEvidenceState.DISPATCH_OBSERVED,
        revision=record.revision + 1,
        prior_record_digest=record.record_digest,
        dispatch_start_checkpoint=record.dispatch_start_checkpoint,
        dispatch_observation=observation,
        state_changed_at=normalized_at,
    )


def record_pre_release_checkpoint(
    record: SafeguardDispatchEvidenceRecord,
    *,
    checkpoint: PreReleaseOwnershipCheckpoint,
    current_lock_assessment: LiveLockOwnershipAssessment | None = None,
    changed_at: datetime,
) -> SafeguardDispatchEvidenceRecord:
    """Persist fresh ownership or continuity-unproven before lock exit."""

    if record.state is not SafeguardDispatchEvidenceState.DISPATCH_OBSERVED:
        raise ValueError("safeguard dispatch evidence has no dispatch observation")
    if checkpoint.evidence_identity_digest != record.identity.identity_digest:
        raise ValueError("pre-release checkpoint changed evidence identity")
    if (
        record.dispatch_observation is None
        or checkpoint.observed_at < record.dispatch_observation.observed_at
    ):
        raise ValueError("pre-release checkpoint predates dispatch")
    normalized_at = _utc(changed_at, "changed_at")
    if checkpoint.continuity_state is PreReleaseContinuityState.CURRENT and (
        checkpoint.evaluated_at is None
        or checkpoint.valid_until is None
        or checkpoint.evaluated_at < record.dispatch_observation.observed_at
        or normalized_at >= checkpoint.valid_until
    ):
        raise ValueError("pre-release ownership assessment is not current")
    if normalized_at < checkpoint.observed_at or normalized_at < record.state_changed_at:
        raise ValueError("pre-release checkpoint transition is backdated")
    current = _build_record(
        identity=record.identity,
        bundle=record.bundle,
        state=SafeguardDispatchEvidenceState.PRE_RELEASE,
        revision=record.revision + 1,
        prior_record_digest=record.record_digest,
        dispatch_start_checkpoint=record.dispatch_start_checkpoint,
        dispatch_observation=record.dispatch_observation,
        pre_release_checkpoint=checkpoint,
        state_changed_at=normalized_at,
    )
    from fdai.core.executor.safeguard_dispatch_transition import (
        validate_dispatch_evidence_transition,
    )

    validate_dispatch_evidence_transition(
        record,
        current,
        current_lock_assessment=current_lock_assessment,
    )
    return current


def _build_record(
    *,
    identity: SafeguardDispatchEvidenceIdentity,
    bundle: SafeguardProofBundle,
    state: SafeguardDispatchEvidenceState,
    revision: int,
    prior_record_digest: str | None,
    state_changed_at: datetime,
    dispatch_start_checkpoint: SafeguardDispatchStartCheckpoint | None = None,
    dispatch_observation: SafeguardDispatchObservation | None = None,
    pre_release_checkpoint: PreReleaseOwnershipCheckpoint | None = None,
) -> SafeguardDispatchEvidenceRecord:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "identity": identity,
        "bundle": bundle,
        "state": state,
        "revision": revision,
        "prior_record_digest": prior_record_digest,
        "dispatch_start_checkpoint": dispatch_start_checkpoint,
        "dispatch_observation": dispatch_observation,
        "pre_release_checkpoint": pre_release_checkpoint,
        "independent_effect_state": "pending",
        "state_changed_at": state_changed_at,
        "execution_authority": False,
        "effect_verified": False,
    }
    values["record_digest"] = _payload_digest(
        values,
        "safeguard-dispatch-evidence-record",
        digest_field="record_digest",
    )
    return SafeguardDispatchEvidenceRecord(**values)  # type: ignore[arg-type]


def _content_digest(
    value: (
        SafeguardDispatchEvidenceIdentity
        | SafeguardDispatchObservation
        | PreReleaseOwnershipCheckpoint
        | SafeguardDispatchEvidenceRecord
    ),
    domain: str,
) -> str:
    digest_field = {
        SafeguardDispatchEvidenceIdentity: "identity_digest",
        SafeguardDispatchObservation: "observation_digest",
        PreReleaseOwnershipCheckpoint: "checkpoint_digest",
        SafeguardDispatchEvidenceRecord: "record_digest",
    }[type(value)]
    return _payload_digest(
        _revision_safe_body(value, asdict(value)),
        domain,
        digest_field=digest_field,
    )


def _revision_safe_body(
    value: object,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Reproduce the digest body the nested identity revision actually hashed.

    A record written before execution provenance existed hashed an identity
    with no provenance keys.  ``asdict`` now materializes those keys as
    ``None``, so hashing it unchanged would invalidate every historical
    record.  Dropping them for a ``1.0.0`` identity keeps those records
    verifiable without weakening the digest for current ones.
    """

    if type(value) is not SafeguardDispatchEvidenceRecord:
        return body
    identity = body.get("identity")
    if not isinstance(identity, dict) or identity.get("schema_version") != "1.0.0":
        return body
    return {
        **body,
        "identity": {key: item for key, item in identity.items() if key not in PROVENANCE_FIELDS},
    }


__all__ = [
    "AuthoritativeSinkState",
    "ContinuityUnprovenReason",
    "DispatchTransportState",
    "PreReleaseContinuityState",
    "PreReleaseOwnershipCheckpoint",
    "SafeguardDispatchEvidenceIdentity",
    "SafeguardDispatchEvidenceRecord",
    "SafeguardDispatchEvidenceState",
    "SafeguardDispatchObservation",
    "SafeguardDispatchStartCheckpoint",
    "record_dispatch_start",
    "record_dispatch_observation",
    "record_pre_release_checkpoint",
]
