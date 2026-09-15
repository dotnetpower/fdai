"""Content-free references to inert handover semantic review packages, never activation authority."""

from __future__ import annotations

from typing import (
    Annotated,
    Literal,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class HandoverSemanticReceipt(BaseModel):
    """Bind exact source and compiler inputs without exposing document text or candidate bodies.

    A reference is not a review. The consumer must independently load the immutable package,
    recheck current sources, and verify its digest before storing its own review disposition.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_id: Digest
    source_revision: Annotated[int, Field(strict=True, ge=1)]
    source_digest: Digest
    compiler_digest: Digest
    package_ref: Annotated[str, Field(pattern=r"^human_assignment:semantic-package:[a-f0-9]{64}$")]
    package_digest: Digest
    disposition: Literal["review_required", "held", "withdrawn"]
    reason: Literal[
        "candidates_compiled",
        "source_unavailable",
        "source_changed",
        "source_withdrawn",
        "acceptance_required",
        "binding_unavailable",
        "no_supported_candidates",
        "verification_held",
        "attempt_interrupted",
    ]
    rule_count: Annotated[int, Field(strict=True, ge=0, le=20)] = 0
    ontology_count: Annotated[int, Field(strict=True, ge=0, le=20)] = 0
    review_required: Literal[True] = True
    execution_authority: Literal[False] = False
    projection_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @field_validator(
        "execution_authority", "projection_authority", "promotion_authority", mode="before"
    )
    @classmethod
    def _no_authority(cls, value: object) -> object:
        if value is not False:
            raise ValueError("semantic candidate receipts cannot grant authority")
        return value

    @field_validator("review_required", mode="before")
    @classmethod
    def _review_required(cls, value: object) -> object:
        if value is not True:
            raise ValueError("semantic candidates always require independent review")
        return value

    @model_validator(mode="after")
    def _counts(self) -> HandoverSemanticReceipt:
        allowed = {
            "review_required": {"candidates_compiled"},
            "withdrawn": {"source_withdrawn"},
            "held": {
                "source_unavailable",
                "source_changed",
                "acceptance_required",
                "binding_unavailable",
                "no_supported_candidates",
                "verification_held",
                "attempt_interrupted",
            },
        }
        if self.reason not in allowed[self.disposition]:
            raise ValueError("semantic disposition does not match its reason")
        if self.disposition == "review_required" and self.rule_count + self.ontology_count == 0:
            raise ValueError("semantic success requires at least one actual candidate")
        if self.disposition != "review_required" and self.rule_count + self.ontology_count:
            raise ValueError("held semantic receipt cannot advertise available candidates")
        if self.rule_count + self.ontology_count > 20:
            raise ValueError("semantic receipt exceeds its combined candidate bound")
        return self


__all__ = ["HandoverSemanticReceipt"]
