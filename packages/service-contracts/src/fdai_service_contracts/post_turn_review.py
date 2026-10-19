"""Versioned Bragi-to-Norns post-turn review wire contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

POST_TURN_REVIEW_TOPIC: Final = "object.post-turn-review"
POST_TURN_REVIEW_REQUEST_TOPIC: Final = "operator.post-turn-review.requests"
POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP: Final = "core-post-turn-review-v1"
POST_TURN_REVIEW_KIND: Final = "post_turn_review"
POST_TURN_REVIEW_PRODUCER: Final = "Bragi"

BoundedId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9._:-]+$")]
BoundedBody = Annotated[str, Field(min_length=1, max_length=16_000)]
MemoryScopeKind = Literal["resource-group", "resource"]


class PostTurnToolReceipt(BaseModel):
    """Safe metadata from one tool receipt; raw tool output is excluded."""

    model_config = ConfigDict(frozen=True)

    tool_name: BoundedId
    status: BoundedId
    evidence_ref: BoundedId


ProcedureDigest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class PostTurnProcedureReceipt(BaseModel):
    """Content-free shape evidence from one fully executed human query plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    kind: Literal["verified_ontology_query_shape"] = "verified_ontology_query_shape"
    principal_scope: ProcedureDigest
    turn_id: Annotated[str, Field(min_length=1, max_length=256)]
    ontology_release_digest: ProcedureDigest
    semantic_catalog_digest: ProcedureDigest
    plan_digest: ProcedureDigest
    execution_receipt_digest: ProcedureDigest
    shape_digest: ProcedureDigest
    tool_receipts: Annotated[tuple[PostTurnToolReceipt, ...], Field(max_length=64)]

    @property
    def procedure_fingerprint(self) -> str:
        return f"query-shape-v1:{self.shape_digest.removeprefix('sha256:')}"


class PostTurnReviewInputWire(BaseModel):
    """Consent-filtered bounded projection of one completed operator turn."""

    model_config = ConfigDict(frozen=True)

    review_id: BoundedId
    principal_scope: BoundedId
    operator_turn_id: BoundedId
    assistant_turn_id: BoundedId
    completed_at: datetime
    operator_body: BoundedBody | None = None
    assistant_body: BoundedBody | None = None
    tool_receipts: Annotated[tuple[PostTurnToolReceipt, ...], Field(max_length=64)] = ()
    validation_outcomes: Annotated[tuple[BoundedId, ...], Field(max_length=32)] = ()
    explicit_corrections: Annotated[tuple[BoundedBody, ...], Field(max_length=8)] = ()
    evidence_refs: Annotated[tuple[BoundedId, ...], Field(max_length=64)] = ()
    memory_scope_kind: MemoryScopeKind | None = None
    memory_scope_ref: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    failure_recovered: bool = False
    procedure_fingerprint: BoundedId | None = None
    repeated_procedure_count: Annotated[int, Field(ge=0)] = 0
    procedure_receipt: PostTurnProcedureReceipt | None = None

    @model_validator(mode="after")
    def _scope_and_repetition_are_bound(self) -> PostTurnReviewInputWire:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("post-turn completed_at MUST be timezone-aware")
        if (self.memory_scope_kind is None) != (self.memory_scope_ref is None):
            raise ValueError("memory scope kind and ref MUST be supplied together")
        if self.procedure_fingerprint is None and self.repeated_procedure_count:
            raise ValueError("repeated procedure count requires a fingerprint")
        if self.procedure_receipt is not None and (
            self.procedure_receipt.principal_scope != self.principal_scope
            or self.procedure_receipt.procedure_fingerprint != self.procedure_fingerprint
            or self.procedure_receipt.tool_receipts != self.tool_receipts
            or self.repeated_procedure_count != 0
        ):
            raise ValueError(
                "post-turn procedure receipt MUST match its metadata without claimed counts"
            )
        return self

    def to_wire_mapping(self) -> dict[str, object]:
        """Return the legacy mapping shape consumed by Norns."""

        result: dict[str, object] = {
            "review_id": self.review_id,
            "principal_scope": self.principal_scope,
            "operator_turn_id": self.operator_turn_id,
            "assistant_turn_id": self.assistant_turn_id,
            "completed_at": self.completed_at.isoformat(),
            "operator_body": self.operator_body,
            "assistant_body": self.assistant_body,
            "tool_receipts": [receipt.model_dump(mode="json") for receipt in self.tool_receipts],
            "validation_outcomes": list(self.validation_outcomes),
            "explicit_corrections": list(self.explicit_corrections),
            "evidence_refs": list(self.evidence_refs),
            "memory_scope_kind": self.memory_scope_kind,
            "memory_scope_ref": self.memory_scope_ref,
            "failure_recovered": self.failure_recovered,
            "procedure_fingerprint": self.procedure_fingerprint,
            "repeated_procedure_count": self.repeated_procedure_count,
        }
        if self.procedure_receipt is not None:
            result["procedure_receipt"] = self.procedure_receipt.model_dump(mode="json")
        return result


class PostTurnBodyConsent(BaseModel):
    """Recorded learner-sharing consent for raw post-turn bodies."""

    model_config = ConfigDict(frozen=True)

    share_with_learner: Literal[True] = True
    principal_scope: BoundedId
    consent_ref: Annotated[str, Field(min_length=1, max_length=512)]


class BragiPostTurnReviewEnvelope(BaseModel):
    """Bragi-owned event-bus envelope accepted by Norns."""

    model_config = ConfigDict(frozen=True)

    producer_principal: Literal["Bragi"] = "Bragi"
    kind: Literal["post_turn_review"] = "post_turn_review"
    correlation_id: BoundedId
    idempotency_key: Annotated[
        str,
        Field(min_length=1, max_length=300, pattern=r"^post-turn-review:[A-Za-z0-9._:-]+$"),
    ]
    review: PostTurnReviewInputWire
    body_consent: PostTurnBodyConsent | None = None

    def to_wire_mapping(self) -> dict[str, object]:
        """Return a plain mapping suitable for JSON event-bus publication."""

        payload: dict[str, object] = {
            "producer_principal": self.producer_principal,
            "kind": self.kind,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "review": self.review.to_wire_mapping(),
        }
        if self.body_consent is not None:
            payload["body_consent"] = self.body_consent.model_dump(mode="json")
        return payload


class OperatorPostTurnReviewRequestEnvelope(BaseModel):
    """Operator-to-Core request for Bragi-owned post-turn publication."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["post_turn_review_request"] = "post_turn_review_request"
    idempotency_key: Annotated[
        str,
        Field(
            min_length=1,
            max_length=300,
            pattern=r"^operator-post-turn-review:[A-Za-z0-9._:-]+$",
        ),
    ]
    review: PostTurnReviewInputWire

    @property
    def request_id(self) -> str:
        return self.idempotency_key.removeprefix("operator-post-turn-review:")

    def to_wire_mapping(self) -> dict[str, object]:
        """Return a plain mapping suitable for Operator-to-Core transport."""

        return {
            "kind": self.kind,
            "idempotency_key": self.idempotency_key,
            "review": self.review.to_wire_mapping(),
        }


def post_turn_review_event_payload(
    review: PostTurnReviewInputWire,
    *,
    body_consent: PostTurnBodyConsent | None = None,
) -> dict[str, object]:
    """Build the shared Bragi-owned event payload for one validated input."""

    return BragiPostTurnReviewEnvelope(
        correlation_id=review.review_id,
        idempotency_key=f"post-turn-review:{review.review_id}",
        review=review,
        body_consent=body_consent,
    ).to_wire_mapping()


def post_turn_review_request_payload(review: PostTurnReviewInputWire) -> dict[str, object]:
    """Build the Operator-owned request payload for Core Bragi ingress."""

    return OperatorPostTurnReviewRequestEnvelope(
        idempotency_key=f"operator-post-turn-review:{review.review_id}",
        review=review,
    ).to_wire_mapping()


__all__ = [
    "BragiPostTurnReviewEnvelope",
    "OperatorPostTurnReviewRequestEnvelope",
    "POST_TURN_REVIEW_REQUEST_CONSUMER_GROUP",
    "POST_TURN_REVIEW_REQUEST_TOPIC",
    "POST_TURN_REVIEW_KIND",
    "POST_TURN_REVIEW_PRODUCER",
    "POST_TURN_REVIEW_TOPIC",
    "PostTurnBodyConsent",
    "PostTurnProcedureReceipt",
    "PostTurnReviewInputWire",
    "PostTurnToolReceipt",
    "post_turn_review_event_payload",
    "post_turn_review_request_payload",
]
