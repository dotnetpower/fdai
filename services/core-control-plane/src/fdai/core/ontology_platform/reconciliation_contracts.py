"""Versioned wire contracts for independently observed effect reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from fdai.shared.contracts.models import (
    ContractBase,
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
_OBSERVATION_PATTERN = r"^effect-observation:[a-f0-9]{64}$"


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
    """Versioned Heimdall-owned evidence envelope for one effect observation cutoff."""

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
    conflicts: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = ()
    evidence_refs: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=512)], ...],
        Field(min_length=1),
    ]
    records: tuple[ObservedEffectRecord, ...] = ()

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
        return self


class EffectReconciliationRequest(ContractBase):
    """Replay-stable command input for one terminal reconciliation decision."""

    schema_version: SemVer = "1.0.0"
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    plan: MutationPlan
    evidence: EffectObservationEnvelope
    deadline: datetime
    evaluated_at: datetime
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @classmethod
    def create(cls, **values: Any) -> Self:
        """Create stable reconciliation and request identities for at-least-once delivery."""

        normalized = dict(values)
        normalized["plan"] = MutationPlan.model_validate(normalized["plan"])
        normalized["evidence"] = EffectObservationEnvelope.model_validate(normalized["evidence"])
        reconciliation_id = _identity(
            "reconciliation",
            {
                "correlation_id": normalized["correlation_id"],
                "plan_digest": normalized["plan"].digest,
            },
        )
        prototype = cls.model_construct(
            **normalized,
            reconciliation_id=reconciliation_id,
            request_digest="sha256:" + "0" * 64,
        )
        return cls(
            **normalized,
            reconciliation_id=reconciliation_id,
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
        if self.correlation_id != self.evidence.correlation_id:
            raise ValueError("reconciliation correlation id MUST match evidence")
        expected_id = _identity(
            "reconciliation",
            {"correlation_id": self.correlation_id, "plan_digest": self.plan.digest},
        )
        if self.reconciliation_id != expected_id:
            raise ValueError("reconciliation id does not match plan and correlation")
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
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    next_step: ReconciliationNextStep
    reason_code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    target_agent: Literal["vidar"] | None = None

    @model_validator(mode="after")
    def _target_matches_next_step(self) -> ReconciliationRecommendation:
        requires_vidar = self.next_step is ReconciliationNextStep.REQUEST_VIDAR_RECOVERY
        if requires_vidar != (self.target_agent == "vidar"):
            raise ValueError("only recovery recommendations target Vidar")
        return self


class ReconciliationOutcome(ContractBase):
    """Immutable coordinator output containing no execution or publication side effect."""

    schema_version: SemVer = "1.0.0"
    reconciliation_id: Annotated[str, Field(pattern=_IDENTITY_PATTERN)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    request_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    receipt: ReconciliationReceipt
    recommendation: ReconciliationRecommendation

    @model_validator(mode="after")
    def _output_is_bound(self) -> ReconciliationOutcome:
        if self.receipt_digest != reconciliation_content_digest(
            self.receipt.model_dump(mode="json")
        ):
            raise ValueError("reconciliation receipt digest does not match receipt")
        if (
            self.recommendation.reconciliation_id != self.reconciliation_id
            or self.recommendation.correlation_id != self.correlation_id
            or self.recommendation.receipt_digest != self.receipt_digest
        ):
            raise ValueError("reconciliation recommendation is not bound to its receipt")
        return self


def reconciliation_content_digest(value: object) -> str:
    """Return the canonical digest shared by request, receipt, and duplicate identity."""

    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_aware_times(**values: datetime) -> None:
    for name, value in values.items():
        if value.tzinfo is None:
            raise ValueError(f"{name} MUST be timezone-aware")


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}:{reconciliation_content_digest(value).removeprefix('sha256:')}"


__all__ = [
    "EffectEvidenceAuthority",
    "EffectObservationEnvelope",
    "EffectReconciliationRequest",
    "ObservedEffectRecord",
    "ReconciliationNextStep",
    "ReconciliationOutcome",
    "ReconciliationRecommendation",
]
