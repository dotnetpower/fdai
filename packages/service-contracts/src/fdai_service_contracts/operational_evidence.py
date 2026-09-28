"""Content-free wire contracts for independent operational evidence issuance.

A boundary owner asks the separate verifier workload to read back one exact decision input.
The request carries only the lookup tuple the owner later passes to ``admit`` plus a
coordinates-only source locator. The response names a status and the digest of the one
record the verifier wrote; it never carries evidence content, and it never grants authority.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.decision_evidence import EvidenceId, SourceIdentity
from fdai_service_contracts.executor_models import ContractBase, Digest, SemVer
from fdai_service_contracts.ontology_query import content_digest

OPERATIONAL_EVIDENCE_PURPOSES: tuple[str, ...] = (
    "case-history-read",
    "current-case-reuse",
    "forecast-context",
    "forecast-history-actions",
    "forecast-history-changes",
    "forecast-history-excluded_windows",
    "forecast-history-resource_lifecycle",
    "operational-test-context",
    "operational-test-observation",
    "operator-test-context-command",
    "test-context-transition",
)
REJECTION_VALIDITY_SECONDS = 60
_FORECAST_COORDINATES = frozenset(
    {"access_scope_digest", "target_digest", "horizon_started_at", "horizon_ended_at"}
)
LOCATOR_COORDINATES: dict[str, frozenset[str]] = {
    "case-history-read": frozenset({"principal_ref", "request_ref", "case_scope_digest"}),
    "current-case-reuse": frozenset({"case_ref", "resource_ref", "event_id"}),
    "forecast-context": _FORECAST_COORDINATES,
    "forecast-history-actions": _FORECAST_COORDINATES,
    "forecast-history-changes": _FORECAST_COORDINATES,
    "forecast-history-excluded_windows": _FORECAST_COORDINATES,
    "forecast-history-resource_lifecycle": _FORECAST_COORDINATES,
    "operational-test-context": frozenset({"context_id", "target_ref", "signal_code"}),
    "operational-test-observation": frozenset({"target_ref", "signal_code", "observed_at"}),
    "operator-test-context-command": frozenset({"idempotency_key"}),
    "test-context-transition": frozenset({"idempotency_key", "context_id", "target_ref"}),
}
_ATTEMPT_ID = r"^[a-f0-9]{32}$"
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MAX_COORDINATE_CHARS = 512
AttemptId = Annotated[str, Field(pattern=_ATTEMPT_ID)]


class OperationalEvidenceRejectionClass(StrEnum):
    """Recorded fail-closed classes; unavailable and self-verified never write a record."""

    CONFLICTING = "conflicting"
    CROSS_SCOPE = "cross_scope"
    PARTIAL = "partial"
    REPLAY_SUBSTITUTED = "replay_substituted"
    REVOKED = "revoked"
    STALE = "stale"
    SYNTHETIC_LIVE = "synthetic_live"


class OperationalEvidenceIssuanceStatus(StrEnum):
    """Content-free issuance outcome named by the verifier response."""

    ISSUED = "issued"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("operational evidence time MUST include a timezone")
    return value.astimezone(UTC)


class OperationalEvidenceLookup(ContractBase):
    """The exact tuple a boundary owner passes to the unchanged ``admit`` seam."""

    evidence_digest: Digest
    scope_digest: Digest
    purpose_id: EvidenceId
    source_revision: SourceIdentity

    @field_validator("purpose_id")
    @classmethod
    def _known_purpose(cls, value: str) -> str:
        if value not in OPERATIONAL_EVIDENCE_PURPOSES:
            raise ValueError("operational evidence purpose is not registered")
        return value

    @property
    def lookup_digest(self) -> str:
        """Return the same content address the decision-evidence admission records use."""

        return content_digest(
            {
                "evidence_digest": self.evidence_digest,
                "purpose_id": self.purpose_id,
                "scope_digest": self.scope_digest,
                "source_revision": self.source_revision,
            }
        )


class OperationalEvidenceLocator(ContractBase):
    """Coordinates of the authoritative source rows; never the evidence content itself."""

    purpose_id: EvidenceId
    coordinates: dict[str, str]

    @model_validator(mode="after")
    def _bounded_coordinates(self) -> OperationalEvidenceLocator:
        allowed = LOCATOR_COORDINATES.get(self.purpose_id)
        if allowed is None:
            raise ValueError("operational evidence locator purpose is not registered")
        if not self.coordinates or set(self.coordinates) - allowed:
            raise ValueError("operational evidence locator coordinates are not allowed")
        for value in self.coordinates.values():
            if (
                not value.strip()
                or len(value) > _MAX_COORDINATE_CHARS
                or any(character in value for character in "\r\n\x00")
            ):
                raise ValueError("operational evidence locator coordinates MUST be bounded text")
        return self

    def coordinate(self, name: str) -> str:
        """Return one required coordinate or fail as an incomplete locator."""

        value = self.coordinates.get(name)
        if value is None:
            raise LookupError(f"operational evidence locator lacks {name}")
        return value


class OperationalEvidenceIssuanceRequest(ContractBase):
    """One bounded issuance attempt; the claimed producer grants nothing by itself."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    attempt_id: AttemptId
    lookup: OperationalEvidenceLookup
    locator: OperationalEvidenceLocator
    producer_id: EvidenceId
    producer_version: SemVer
    requested_at: datetime
    execution_authority: Literal[False] = False

    @field_validator("requested_at")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def _one_purpose(self) -> OperationalEvidenceIssuanceRequest:
        if self.locator.purpose_id != self.lookup.purpose_id:
            raise ValueError("operational evidence locator purpose mismatches the lookup")
        return self

    @property
    def coalescing_key(self) -> str:
        """Identify identical in-flight work independent of attempt id and request time."""

        return content_digest(
            {
                "locator": self.locator.model_dump(mode="json"),
                "lookup": self.lookup.model_dump(mode="json"),
                "producer_id": self.producer_id,
                "producer_version": self.producer_version,
            }
        )


class OperationalEvidenceIssuanceResponse(ContractBase):
    """Content-free result; consumers re-read the named record before trusting it."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    attempt_id: AttemptId
    lookup_digest: Digest
    status: OperationalEvidenceIssuanceStatus
    record_digest: Digest | None = None
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @model_validator(mode="after")
    def _record_matches_status(self) -> OperationalEvidenceIssuanceResponse:
        if (self.status is OperationalEvidenceIssuanceStatus.UNAVAILABLE) != (
            self.record_digest is None
        ):
            raise ValueError("operational evidence response record does not match its status")
        return self

    @classmethod
    def unavailable(cls, request: OperationalEvidenceIssuanceRequest) -> Self:
        """Return the generic outage outcome for one attempt."""

        return cls(
            attempt_id=request.attempt_id,
            lookup_digest=request.lookup.lookup_digest,
            status=OperationalEvidenceIssuanceStatus.UNAVAILABLE,
        )


class _RejectionRecordBody(ContractBase):
    schema_version: Literal["1.0.0"] = "1.0.0"
    attempt_id: AttemptId
    lookup_digest: Digest
    purpose_id: EvidenceId
    rejection_class: OperationalEvidenceRejectionClass
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1, max_length=16)]
    conflict_evidence_digests: Annotated[tuple[Digest, ...], Field(max_length=32)] = ()
    trust_registry_pin: Digest
    grant_registry_pin: Digest
    verifier_id: EvidenceId
    verifier_version: SemVer
    recorded_at: datetime
    valid_until: datetime
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("recorded_at", "valid_until")
    @classmethod
    def _normalize_time(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def _content_free(self) -> _RejectionRecordBody:
        if self.purpose_id not in OPERATIONAL_EVIDENCE_PURPOSES:
            raise ValueError("operational evidence rejection purpose is not registered")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))) or any(
            _REASON_CODE.fullmatch(code) is None for code in self.reason_codes
        ):
            raise ValueError("operational evidence rejection reasons MUST be ordered codes")
        if self.conflict_evidence_digests != tuple(sorted(set(self.conflict_evidence_digests))):
            raise ValueError("operational evidence conflict digests MUST be unique and ordered")
        if (self.rejection_class is OperationalEvidenceRejectionClass.CONFLICTING) != bool(
            self.conflict_evidence_digests
        ):
            raise ValueError("operational evidence conflict digests do not match the class")
        if self.valid_until != self.recorded_at + timedelta(seconds=REJECTION_VALIDITY_SECONDS):
            raise ValueError("operational evidence rejection validity MUST be exactly 60 seconds")
        return self


class OperationalEvidenceRejectionRecord(_RejectionRecordBody):
    """Content-free, attempt-scoped rejection; it is never reused by another attempt."""

    record_digest: Digest

    @model_validator(mode="after")
    def _digest_matches(self) -> OperationalEvidenceRejectionRecord:
        expected = content_digest(self.model_dump(mode="json", exclude={"record_digest"}))
        if self.record_digest != expected:
            raise ValueError("operational evidence rejection record digest mismatched")
        return self

    @classmethod
    def create(
        cls,
        *,
        attempt_id: str,
        lookup_digest: str,
        purpose_id: str,
        rejection_class: OperationalEvidenceRejectionClass,
        reason_codes: tuple[str, ...],
        conflict_evidence_digests: tuple[str, ...] = (),
        trust_registry_pin: str,
        grant_registry_pin: str,
        verifier_id: str,
        verifier_version: str,
        recorded_at: datetime,
    ) -> Self:
        """Build the canonical record with its fixed 60-second attempt window."""

        recorded = _aware(recorded_at)
        body = _RejectionRecordBody(
            attempt_id=attempt_id,
            lookup_digest=lookup_digest,
            purpose_id=purpose_id,
            rejection_class=rejection_class,
            reason_codes=tuple(sorted(set(reason_codes))),
            conflict_evidence_digests=tuple(sorted(set(conflict_evidence_digests))),
            trust_registry_pin=trust_registry_pin,
            grant_registry_pin=grant_registry_pin,
            verifier_id=verifier_id,
            verifier_version=verifier_version,
            recorded_at=recorded,
            valid_until=recorded + timedelta(seconds=REJECTION_VALIDITY_SECONDS),
        )
        payload = body.model_dump(mode="json")
        return cls.model_validate({**payload, "record_digest": content_digest(payload)})

    def current_at(self, evaluated_at: datetime) -> bool:
        """Return whether this attempt-scoped rejection may still be read by its owner."""

        return self.recorded_at <= _aware(evaluated_at) < self.valid_until


class OperationalEvidenceVerifierState(StrEnum):
    """Writer-readback state of the verifier workload; only ``ready`` may issue."""

    READY = "ready"
    SELF_VERIFIED = "self_verified"
    UNAVAILABLE = "unavailable"


class OperationalEvidenceSourceHealth(StrEnum):
    """Outcome of one bounded read the verifier ran against a declared source."""

    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"


class OperationalEvidenceVerifierReadiness(ContractBase):
    """Content-free readiness snapshot the verifier serves; it grants no authority.

    A consumer treats a purpose as bound only when this snapshot is current, names the same
    registry pins it loaded, reports a writer-exclusive proof store, binds the purpose, and
    reports every source the purpose declares as healthy.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    state: OperationalEvidenceVerifierState
    reasons: Annotated[tuple[str, ...], Field(max_length=16)] = ()
    verifier_id: EvidenceId
    verifier_version: SemVer
    trust_registry_pin: Digest
    grant_registry_pin: Digest
    bound_purposes: Annotated[tuple[str, ...], Field(max_length=16)] = ()
    source_health: Annotated[
        dict[SourceIdentity, OperationalEvidenceSourceHealth], Field(max_length=32)
    ] = Field(default_factory=dict)
    probed_at: datetime | None = None
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator("probed_at")
    @classmethod
    def _normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @model_validator(mode="after")
    def _consistent(self) -> OperationalEvidenceVerifierReadiness:
        if self.reasons != tuple(sorted(set(self.reasons))) or any(
            _REASON_CODE.fullmatch(code) is None for code in self.reasons
        ):
            raise ValueError("verifier readiness reasons MUST be ordered codes")
        if (self.state is OperationalEvidenceVerifierState.READY) == bool(self.reasons):
            raise ValueError("verifier readiness reasons MUST explain every non-ready state")
        if self.bound_purposes != tuple(sorted(set(self.bound_purposes))) or (
            set(self.bound_purposes) - set(OPERATIONAL_EVIDENCE_PURPOSES)
        ):
            raise ValueError("verifier readiness purposes MUST be ordered registered purposes")
        return self


__all__ = [
    "LOCATOR_COORDINATES",
    "OPERATIONAL_EVIDENCE_PURPOSES",
    "REJECTION_VALIDITY_SECONDS",
    "OperationalEvidenceIssuanceRequest",
    "OperationalEvidenceIssuanceResponse",
    "OperationalEvidenceIssuanceStatus",
    "OperationalEvidenceLocator",
    "OperationalEvidenceLookup",
    "OperationalEvidenceRejectionClass",
    "OperationalEvidenceRejectionRecord",
    "OperationalEvidenceSourceHealth",
    "OperationalEvidenceVerifierReadiness",
    "OperationalEvidenceVerifierState",
]
