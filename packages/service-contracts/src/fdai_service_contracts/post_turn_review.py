"""Versioned Bragi-to-Norns post-turn review wire contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

POST_TURN_REVIEW_TOPIC: Final = "object.post-turn-review"
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

    @model_validator(mode="after")
    def _scope_and_repetition_are_bound(self) -> PostTurnReviewInputWire:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("post-turn completed_at MUST be timezone-aware")
        if (self.memory_scope_kind is None) != (self.memory_scope_ref is None):
            raise ValueError("memory scope kind and ref MUST be supplied together")
        if self.procedure_fingerprint is None and self.repeated_procedure_count:
            raise ValueError("repeated procedure count requires a fingerprint")
        return self

    def to_wire_mapping(self) -> dict[str, object]:
        """Return the legacy mapping shape consumed by Norns."""

        return {
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

    def to_wire_mapping(self) -> dict[str, object]:
        """Return a plain mapping suitable for JSON event-bus publication."""

        return {
            "producer_principal": self.producer_principal,
            "kind": self.kind,
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "review": self.review.to_wire_mapping(),
        }


def post_turn_review_event_payload(review: PostTurnReviewInputWire) -> dict[str, object]:
    """Build the shared Bragi-owned event payload for one validated input."""

    return BragiPostTurnReviewEnvelope(
        correlation_id=review.review_id,
        idempotency_key=f"post-turn-review:{review.review_id}",
        review=review,
    ).to_wire_mapping()


__all__ = [
    "BragiPostTurnReviewEnvelope",
    "POST_TURN_REVIEW_KIND",
    "POST_TURN_REVIEW_PRODUCER",
    "POST_TURN_REVIEW_TOPIC",
    "PostTurnReviewInputWire",
    "PostTurnToolReceipt",
    "post_turn_review_event_payload",
]
