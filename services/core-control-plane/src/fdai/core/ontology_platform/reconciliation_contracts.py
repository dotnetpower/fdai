"""Versioned wire contracts for independently observed effect reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ContractBase,
    OntologyActionType,
    OntologyReleaseRef,
    OntologyTypeRef,
    SemVer,
)
from fdai.shared.providers.ontology_instance import (
    OntologyObjectRecord,
    canonical_json_mapping,
)

from .kinetics import MutationPlan, ReconciliationReceipt

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_IDENTITY_PATTERN = r"^reconciliation:[a-f0-9]{64}$"
_ATTEMPT_PATTERN = r"^reconciliation-attempt:[a-f0-9]{64}$"
_OBSERVATION_PATTERN = r"^effect-observation:[a-f0-9]{64}$"
_RECOMMENDATION_PATTERN = r"^reconciliation-next-step:[a-f0-9]{64}$"
_MAX_CONFLICTS = 64
_MAX_EVIDENCE_REFS = 128
_MAX_RECORDS = 1000
_MAX_OBSERVATION_BYTES = 1_048_576


class EffectEvidenceAuthority(StrEnum):
    """Authority asserted by an effect-evidence source."""

    PROVIDER = "provider"
    TELEMETRY = "telemetry"
    API_RECEIPT = "api_receipt"
    EXECUTOR = "executor"
    UNKNOWN = "unknown"


class ReconciliationNextStep(StrEnum):
    """Typed recommendation emitted without performing the recommended action."""

    CLOSE_MATCHED = "close_matched"
    REQUEST_VIDAR_RECOVERY = "request_vidar_recovery"
    HOLD_UNSCORABLE = "hold_unscorable"


class ObservedEffectRecord(ContractBase):
    """Immutable canonical projection of one independently observed ontology object."""

    object_id: Annotated[str, Field(min_length=1, max_length=512)]
    type_ref: OntologyTypeRef
    revision: int = Field(ge=1)
    properties_json: Annotated[str, Field(min_length=2, max_length=65_536)]

    @classmethod
    def from_record(cls, record: OntologyObjectRecord) -> Self:
        """Create a wire-safe observation without retaining a mutable property mapping."""

        if record.type_ref is None:
            raise ValueError("observed effect record requires an exact type ref")
        _, encoded = canonical_json_mapping(record.properties, path="observed_effect.properties")
        return cls(
            object_id=record.id,
            type_ref=record.type_ref,
            revision=record.revision,
            properties_json=encoded,
        )

    @model_validator(mode="after")
    def _properties_are_canonical(self) -> ObservedEffectRecord:
        try:
            decoded = json.loads(self.properties_json)
        except json.JSONDecodeError as exc:
            raise ValueError("observed effect properties MUST be canonical JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("observed effect properties MUST be a JSON object")
        _, canonical = canonical_json_mapping(decoded, path="observed_effect.properties")
        if canonical != self.properties_json:
            raise ValueError("observed effect properties MUST use canonical JSON encoding")
        return self

    def to_record(self) -> OntologyObjectRecord:
        """Decode the validated canonical projection for pure effect comparison."""

        properties = json.loads(self.properties_json)
        return OntologyObjectRecord(
            id=self.object_id,
            object_type=self.type_ref.name,
            properties=properties,
            revision=self.revision,
            type_ref=self.type_ref,
        )


class EffectObservationEnvelope(ContractBase):
    """Versioned untrusted evidence envelope for one effect observation cutoff.

    Identity and authority fields are claims used for authenticated-context binding. They do not
    grant observation authority by themselves.
    """

    schema_version: SemVer = "1.0.0"
    observation_id: Annotated[str, Field(pattern=_OBSERVATION_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    ontology_release_ref: OntologyReleaseRef
    action_type_ref: OntologyTypeRef
    owner_agent: Literal["heimdall"] = "heimdall"
    observer_identity: Annotated[str, Field(min_length=1, max_length=512)]
    execution_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_authority: EffectEvidenceAuthority
    observed_at: datetime
    observation_cutoff: datetime
    recorded_at: datetime
    fresh_until: datetime
    complete: bool
    synthetic: bool
    conflicts: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(max_length=_MAX_CONFLICTS),
    ] = ()
    evidence_refs: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=512)], ...],
        Field(min_length=1, max_length=_MAX_EVIDENCE_REFS),
    ]
    records: Annotated[tuple[ObservedEffectRecord, ...], Field(max_length=_MAX_RECORDS)] = ()

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Create a content-addressed envelope after canonicalizing repeated fields."""

        normalized = dict(values)
        normalized["ontology_release_ref"] = OntologyReleaseRef.model_validate(
            normalized["ontology_release_ref"]
        )
        normalized["action_type_ref"] = OntologyTypeRef.model_validate(
            normalized["action_type_ref"]
        )
        normalized["source_authority"] = EffectEvidenceAuthority(normalized["source_authority"])
        normalized["conflicts"] = tuple(sorted(set(normalized.get("conflicts", ()))))
        normalized["evidence_refs"] = tuple(sorted(set(normalized["evidence_refs"])))
        normalized["records"] = tuple(
            sorted(
                (
                    ObservedEffectRecord.model_validate(item)
                    for item in normalized.get("records", ())
                ),
                key=lambda item: item.object_id,
            )
        )
        prototype = cls.model_construct(
            **normalized,
            observation_id="effect-observation:" + "0" * 64,
        )
        return cls(
            **normalized,
            observation_id=_identity(
                "effect-observation",
                prototype.model_dump(mode="json", exclude={"observation_id"}),
            ),
        )

    @model_validator(mode="after")
    def _evidence_is_canonical(self) -> EffectObservationEnvelope:
        _require_aware_times(
            observed_at=self.observed_at,
            observation_cutoff=self.observation_cutoff,
            recorded_at=self.recorded_at,
            fresh_until=self.fresh_until,
        )
        if not self.observed_at <= self.observation_cutoff <= self.recorded_at:
            raise ValueError("effect observation times MUST satisfy observed <= cutoff <= recorded")
        if self.fresh_until < self.observation_cutoff:
            raise ValueError("effect observation freshness MUST cover its cutoff")
        if tuple(sorted(set(self.conflicts))) != self.conflicts:
            raise ValueError("effect observation conflicts MUST be sorted and unique")
        if tuple(sorted(set(self.evidence_refs))) != self.evidence_refs:
            raise ValueError("effect observation evidence refs MUST be sorted and unique")
        record_ids = tuple(item.object_id for item in self.records)
        if tuple(sorted(set(record_ids))) != record_ids:
            raise ValueError("effect observation records MUST be sorted and unique")
        expected_id = _identity(
            "effect-observation",
            self.model_dump(mode="json", exclude={"observation_id"}),
        )
        if self.observation_id != expected_id:
            raise ValueError("effect observation id does not match its content")
        if len(_canonical_json_bytes(self.model_dump(mode="json"))) > _MAX_OBSERVATION_BYTES:
            raise ValueError("effect observation exceeds the canonical byte limit")
        return self

    def content_digest(self) -> str:
        """Return the digest bound by a trusted observation verification receipt."""

        return reconciliation_content_digest(self.model_dump(mode="json"))


class ObservationVerificationReceipt(ContractBase):
    """Signed, content-addressed proof that an authenticator verified one observation."""

    schema_version: SemVer = "1.0.0"
    observation_id: Annotated[str, Field(pattern=_OBSERVATION_PATTERN)]
    observation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verifier_identity: Annotated[str, Field(min_length=1, max_length=512)]
    verifier_credential_lineage: Annotated[str, Field(min_length=1, max_length=512)]
    verified_at: datetime
    signature_algorithm: Literal["ed25519"]
    signature: Annotated[
        str,
        Field(pattern=r"^base64:[A-Za-z0-9_-]{16,684}$", max_length=691),
    ]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Build the content address over the signed verification fields."""

        prototype = cls.model_construct(
            **values,
            receipt_digest="sha256:" + "0" * 64,
        )
        return cls(
            **values,
            receipt_digest=reconciliation_content_digest(
                prototype.model_dump(mode="json", exclude={"receipt_digest"})
            ),
        )

    @model_validator(mode="after")
    def _receipt_is_canonical(self) -> ObservationVerificationReceipt:
        _require_aware_times(verified_at=self.verified_at)
        expected = reconciliation_content_digest(
            self.model_dump(mode="json", exclude={"receipt_digest"})
        )
        if self.receipt_digest != expected:
            raise ValueError("observation verification receipt digest does not match content")
        return self


class AuthenticatedObservationContext(ContractBase):
    """Trusted authentication result supplied separately from the evidence envelope."""

    schema_version: SemVer = "1.0.0"
    source_authority: EffectEvidenceAuthority
    observer_identity: Annotated[str, Field(min_length=1, max_length=512)]
    observer_credential_lineage: Annotated[str, Field(min_length=1, max_length=512)]
    executor_identity: Annotated[str, Field(min_length=1, max_length=512)]
    executor_credential_lineage: Annotated[str, Field(min_length=1, max_length=512)]
    source_identity: Annotated[str, Field(min_length=1, max_length=512)]
    source_credential_lineage: Annotated[str, Field(min_length=1, max_length=512)]
    verification_receipt: ObservationVerificationReceipt
    signature_verified: Literal[True]

    def content_digest(self) -> str:
        """Bind authenticated identities and credential lineage for replay."""

        return reconciliation_content_digest(self.model_dump(mode="json"))


class EffectReconciliationRequest(ContractBase):
    """Replay-stable command input for one terminal reconciliation decision."""

    schema_version: SemVer = "1.0.0"
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    observation_attempt_id: Annotated[str, Field(pattern=_ATTEMPT_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    plan: MutationPlan
    action_type: OntologyActionType | None = None
    evidence: EffectObservationEnvelope
    deadline: datetime
    evaluated_at: datetime
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Create stable reconciliation and request identities for at-least-once delivery."""

        normalized = dict(values)
        normalized["deadline"] = _canonical_datetime(normalized["deadline"], name="deadline")
        normalized["evaluated_at"] = _canonical_datetime(
            normalized["evaluated_at"], name="evaluated_at"
        )
        normalized["plan"] = MutationPlan.model_validate(normalized["plan"])
        if normalized.get("action_type") is not None:
            normalized["action_type"] = OntologyActionType.model_validate(normalized["action_type"])
        normalized["evidence"] = EffectObservationEnvelope.model_validate(normalized["evidence"])
        reconciliation_id = _identity(
            "reconciliation",
            {
                "correlation_id": normalized["correlation_id"],
                "plan_digest": normalized["plan"].digest,
            },
        )
        observation_attempt_id = _identity(
            "reconciliation-attempt",
            {
                "reconciliation_id": reconciliation_id,
                "observation_id": normalized["evidence"].observation_id,
                "deadline": normalized["deadline"].isoformat().replace("+00:00", "Z"),
                "evaluated_at": normalized["evaluated_at"].isoformat().replace("+00:00", "Z"),
            },
        )
        prototype = cls.model_construct(
            **normalized,
            reconciliation_id=reconciliation_id,
            observation_attempt_id=observation_attempt_id,
            request_digest="sha256:" + "0" * 64,
        )
        return cls(
            **normalized,
            reconciliation_id=reconciliation_id,
            observation_attempt_id=observation_attempt_id,
            request_digest=reconciliation_content_digest(
                prototype.model_dump(mode="json", exclude={"request_digest"})
            ),
        )

    @model_validator(mode="after")
    def _request_is_canonical(self) -> EffectReconciliationRequest:
        _require_aware_times(deadline=self.deadline, evaluated_at=self.evaluated_at)
        if self.deadline <= self.plan.created_at:
            raise ValueError("reconciliation deadline MUST follow plan creation")
        if self.evaluated_at < self.evidence.recorded_at:
            raise ValueError("reconciliation evaluation MUST NOT precede evidence recording")
        if self.evidence.observed_at < self.plan.created_at:
            raise ValueError("effect observation MUST NOT precede plan creation")
        if self.evidence.observation_cutoff > self.evaluated_at:
            raise ValueError("effect observation cutoff MUST NOT follow evaluation")
        if self.evidence.observation_cutoff > self.deadline:
            raise ValueError("effect observation cutoff MUST NOT follow reconciliation deadline")
        if self.correlation_id != self.evidence.correlation_id:
            raise ValueError("reconciliation correlation id MUST match evidence")
        expected_id = _identity(
            "reconciliation",
            {"correlation_id": self.correlation_id, "plan_digest": self.plan.digest},
        )
        if self.reconciliation_id != expected_id:
            raise ValueError("reconciliation id does not match plan and correlation")
        expected_attempt_id = _identity(
            "reconciliation-attempt",
            {
                "reconciliation_id": self.reconciliation_id,
                "observation_id": self.evidence.observation_id,
                "deadline": self.deadline.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "evaluated_at": self.evaluated_at.astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z"),
            },
        )
        if self.observation_attempt_id != expected_attempt_id:
            raise ValueError("reconciliation attempt id does not match its observation")
        expected_digest = reconciliation_content_digest(
            self.model_dump(mode="json", exclude={"request_digest"})
        )
        if self.request_digest != expected_digest:
            raise ValueError("reconciliation request digest does not match its content")
        return self


class ReconciliationRecommendation(ContractBase):
    """Versioned event payload describing the sole allowed next step."""

    schema_version: SemVer = "1.0.0"
    event_type: Literal["ontology.reconciliation.next_step.v1"] = (
        "ontology.reconciliation.next_step.v1"
    )
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    observation_attempt_id: Annotated[str, Field(pattern=_ATTEMPT_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    ontology_release_ref: OntologyReleaseRef
    action_type_ref: OntologyTypeRef
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observation_id: Annotated[str, Field(pattern=_OBSERVATION_PATTERN)]
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observation_context_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verification_receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    idempotency_key: Annotated[str, Field(pattern=_RECOMMENDATION_PATTERN)]
    next_step: ReconciliationNextStep
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    target_agent: Literal["vidar"] | None = None
    proposal_only: Literal[True] = True
    grants_authority: Literal[False] = False

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Create a replay-stable proposal event bound to every decision reference."""

        normalized = dict(values)
        normalized["next_step"] = ReconciliationNextStep(normalized["next_step"])
        idempotency_key = _recommendation_idempotency_key(normalized)
        return cls(**normalized, idempotency_key=idempotency_key)

    @model_validator(mode="after")
    def _target_matches_next_step(self) -> ReconciliationRecommendation:
        requires_vidar = self.next_step is ReconciliationNextStep.REQUEST_VIDAR_RECOVERY
        if requires_vidar != (self.target_agent == "vidar"):
            raise ValueError("only recovery recommendations target Vidar")
        if self.idempotency_key != _recommendation_idempotency_key(
            self.model_dump(mode="python", exclude={"idempotency_key"})
        ):
            raise ValueError("reconciliation recommendation idempotency key does not match content")
        return self


class ReconciliationOutcome(ContractBase):
    """Immutable coordinator output containing no execution or publication side effect."""

    schema_version: SemVer = "1.0.0"
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    observation_attempt_id: Annotated[str, Field(pattern=_ATTEMPT_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observation_context_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    verification_receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    observation_context: AuthenticatedObservationContext
    request: EffectReconciliationRequest
    receipt: ReconciliationReceipt
    recommendation: ReconciliationRecommendation
    terminal: bool

    @model_validator(mode="after")
    def _output_is_bound(self) -> ReconciliationOutcome:
        if self.receipt_digest != reconciliation_content_digest(
            self.receipt.model_dump(mode="json")
        ):
            raise ValueError("reconciliation receipt digest does not match receipt")
        if self.observation_context_digest != self.observation_context.content_digest():
            raise ValueError("reconciliation observation context digest does not match content")
        if (
            self.verification_receipt_digest
            != self.observation_context.verification_receipt.receipt_digest
        ):
            raise ValueError("reconciliation verification receipt digest does not match content")
        request = self.request
        if (
            request.reconciliation_id != self.reconciliation_id
            or request.observation_attempt_id != self.observation_attempt_id
            or request.correlation_id != self.correlation_id
            or request.request_digest != self.request_digest
            or self.receipt.plan_digest != request.plan.digest
        ):
            raise ValueError("reconciliation outcome is not bound to its canonical request")
        if (
            self.recommendation.reconciliation_id != self.reconciliation_id
            or self.recommendation.observation_attempt_id != self.observation_attempt_id
            or self.recommendation.correlation_id != self.correlation_id
            or self.recommendation.ontology_release_ref != request.evidence.ontology_release_ref
            or self.recommendation.action_type_ref != request.plan.action_type_ref
            or self.recommendation.plan_digest != request.plan.digest
            or self.recommendation.observation_id != request.evidence.observation_id
            or self.recommendation.request_digest != self.request_digest
            or self.recommendation.receipt_digest != self.receipt_digest
            or self.recommendation.observation_context_digest != self.observation_context_digest
            or self.recommendation.verification_receipt_digest != self.verification_receipt_digest
        ):
            raise ValueError("reconciliation recommendation is not bound to its receipt")
        expected_next_step = {
            "matched": ReconciliationNextStep.CLOSE_MATCHED,
            "mismatched": ReconciliationNextStep.REQUEST_VIDAR_RECOVERY,
            "timed_out": ReconciliationNextStep.REQUEST_VIDAR_RECOVERY,
            "unscorable": ReconciliationNextStep.HOLD_UNSCORABLE,
        }[self.receipt.status.value]
        if self.recommendation.next_step is not expected_next_step:
            raise ValueError("reconciliation status does not match its exact next step")
        if self.terminal == (self.receipt.status.value == "unscorable"):
            raise ValueError("only matched, mismatched, and timed_out outcomes are terminal")
        return self


def reconciliation_content_digest(value: object) -> str:
    """Return the canonical digest shared by request, receipt, and duplicate identity."""

    encoded = _canonical_json_bytes(value)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_aware_times(**values: datetime) -> None:
    for name, value in values.items():
        if value.tzinfo is None:
            raise ValueError(f"{name} MUST be timezone-aware")


def _canonical_datetime(value: object, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} MUST be RFC3339") from exc
    else:
        raise ValueError(f"{name} MUST be a datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _recommendation_idempotency_key(values: dict[str, Any]) -> str:
    material = {
        "reconciliation_id": values["reconciliation_id"],
        "observation_attempt_id": values["observation_attempt_id"],
        "correlation_id": values["correlation_id"],
        "ontology_release_ref": OntologyReleaseRef.model_validate(
            values["ontology_release_ref"]
        ).model_dump(mode="json"),
        "action_type_ref": OntologyTypeRef.model_validate(values["action_type_ref"]).model_dump(
            mode="json"
        ),
        "plan_digest": values["plan_digest"],
        "observation_id": values["observation_id"],
        "request_digest": values["request_digest"],
        "receipt_digest": values["receipt_digest"],
        "observation_context_digest": values["observation_context_digest"],
        "verification_receipt_digest": values["verification_receipt_digest"],
        "next_step": ReconciliationNextStep(values["next_step"]).value,
        "reason_code": values["reason_code"],
        "target_agent": values.get("target_agent"),
    }
    return _identity("reconciliation-next-step", material)


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}:{reconciliation_content_digest(value).removeprefix('sha256:')}"


__all__ = [
    "AuthenticatedObservationContext",
    "EffectEvidenceAuthority",
    "EffectObservationEnvelope",
    "EffectReconciliationRequest",
    "ObservedEffectRecord",
    "ObservationVerificationReceipt",
    "ReconciliationNextStep",
    "ReconciliationOutcome",
    "ReconciliationRecommendation",
]
