"""Exact document intent contracts; text cannot grant observation or action authority."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class IntentServiceProperties(BaseModel):
    """The scalar BusinessService declaration, not arbitrary graph properties."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    id: Annotated[str, Field(pattern=r"^service:[A-Za-z0-9_.:-]{1,180}$")]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    criticality: Annotated[str, Field(min_length=1, max_length=64)]
    effective_from: datetime
    effective_to: datetime | None = None
    source_ref: Annotated[str, Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _time_bounds(self) -> IntentServiceProperties:
        if self.effective_from.tzinfo is None or (
            self.effective_to is not None
            and (self.effective_to.tzinfo is None or self.effective_to <= self.effective_from)
        ):
            raise ValueError("declared intent requires an ordered timezone-aware interval")
        return self


class DocumentIntentDiff(BaseModel):
    """A human approves this complete immutable diff, never an envelope's indexing permission."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    authority: Literal["declared_intent"] = "declared_intent"
    object_type: Literal["BusinessService"] = "BusinessService"
    operation: Literal["add", "update"]
    document_id: UUID
    version_id: UUID
    source_revision: Annotated[int, Field(strict=True, ge=1)]
    source_digest: Digest
    envelope_digest: Digest
    acl_digest: Digest
    ontology_release: Digest
    expected_revision: Annotated[int, Field(strict=True, ge=0)]
    scope_ref: Annotated[str, Field(min_length=1, max_length=512)]
    requester_ref: Annotated[str, Field(min_length=1, max_length=256)]
    properties: IntentServiceProperties

    @model_validator(mode="after")
    def _identity_and_operation(self) -> DocumentIntentDiff:
        if (self.operation == "add") != (self.expected_revision == 0):
            raise ValueError("intent operation must bind the exact prior target revision")
        if self.properties.source_ref != f"doc:{self.document_id}:{self.version_id}":
            raise ValueError("intent source reference must bind its immutable document version")
        return self

    @property
    def digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


INTENT_KIND = "document_intent_projection"
INTENT_OWNERS = {
    "source": ("Huginn", "object.event"),
    "ready": ("Muninn", "object.context-index"),
    "candidate": ("Norns", "object.rule-candidate"),
    "reviewed": ("Mimir", "object.rule"),
    "verdict": ("Forseti", "object.verdict"),
    "verdict_sealed": ("Saga", "object.audit-entry"),
    "approved_sealed": ("Saga", "object.audit-entry"),
    "applied": ("Muninn", "object.context-index"),
    "verified": ("Heimdall", "object.retrieval-validation"),
    "verified_sealed": ("Saga", "object.audit-entry"),
    "rolled_back": ("Vidar", "object.rollback"),
    "held": ("Muninn", "object.context-index"),
    "recovery_held": ("Vidar", "object.rollback"),
    "arbitration_requested": ("Forseti", "object.arbitration-request"),
    "arbitrated": ("Odin", "object.arbitration-decision"),
}


class DocumentIntentEvent(BaseModel):
    """Content-free owned transition; no document text or graph properties enter the bus."""

    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["document_intent_projection"] = "document_intent_projection"
    phase: Literal[
        "source",
        "ready",
        "candidate",
        "reviewed",
        "verdict",
        "verdict_sealed",
        "approved_sealed",
        "applied",
        "verified",
        "verified_sealed",
        "rolled_back",
        "held",
        "recovery_held",
        "arbitration_requested",
        "arbitrated",
    ]
    intent_digest: Digest
    correlation_id: Annotated[str, Field(min_length=1, max_length=256)]
    producer_principal: str
    idempotency_key: str
    resource_id: str
    outcome: Literal["pending", "matched", "mismatched", "rolled_back"] = "pending"
    applied_revision: Annotated[int, Field(strict=True, ge=0)] = 0

    @model_validator(mode="after")
    def _owner_and_identity(self) -> DocumentIntentEvent:
        if (
            INTENT_OWNERS[self.phase][0] != self.producer_principal
            or self.resource_id != "document-intent:" + self.intent_digest[7:]
            or self.idempotency_key
            != content_digest(
                {
                    "phase": self.phase,
                    "intent": self.intent_digest,
                    "correlation": self.correlation_id,
                    "outcome": self.outcome,
                    "revision": self.applied_revision,
                }
            )
        ):
            raise ValueError("document intent event owner or immutable identity mismatch")
        return self

    @property
    def topic(self) -> str:
        return INTENT_OWNERS[self.phase][1]

    @classmethod
    def create(
        cls,
        phase: str,
        digest: str,
        correlation: str,
        *,
        outcome: str = "pending",
        applied_revision: int = 0,
    ) -> DocumentIntentEvent:
        return cls.model_validate(
            {
                "phase": phase,
                "intent_digest": digest,
                "correlation_id": correlation,
                "producer_principal": INTENT_OWNERS[phase][0],
                "resource_id": "document-intent:" + digest[7:],
                "outcome": outcome,
                "applied_revision": applied_revision,
                "idempotency_key": content_digest(
                    {
                        "phase": phase,
                        "intent": digest,
                        "correlation": correlation,
                        "outcome": outcome,
                        "revision": applied_revision,
                    }
                ),
            }
        )
