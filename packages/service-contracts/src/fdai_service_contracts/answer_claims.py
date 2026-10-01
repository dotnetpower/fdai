"""Versioned proposition contracts for verified semantic answers."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract

MAX_ANSWER_CHARS = 16_000
MAX_CLAIMS = 64
_ID = r"^[a-z][a-z0-9_.-]{0,79}$"


class AnswerClaimKind(StrEnum):
    RESTATEMENT = "restatement"
    FACT = "fact"
    COUNT = "count"
    RELATION = "relation"
    STATE = "state"
    CHANGE = "change"
    CAUSE_HYPOTHESIS = "cause_hypothesis"
    LIMITATION = "limitation"
    NEXT_CHECK = "next_check"


class ClaimPolarity(StrEnum):
    AFFIRM = "affirm"
    DENY = "deny"


class ClaimQuantifier(StrEnum):
    EXACT = "exact"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    ANY = "any"
    ALL = "all"
    NONE = "none"


class ClaimModality(StrEnum):
    OBSERVED = "observed"
    POSSIBLE = "possible"
    HYPOTHESIS = "hypothesis"


class ClaimCausalClass(StrEnum):
    NONE = "none"
    ASSOCIATION = "association"
    TEMPORAL_PRECEDENCE = "temporal_precedence"
    CAUSAL_HYPOTHESIS = "causal_hypothesis"


class ClaimTemporalBasis(StrEnum):
    CURRENT = "current"
    WINDOW = "window"
    HISTORICAL = "historical"
    SNAPSHOT = "snapshot"


class AnswerClaimSpan(QueryContract):
    start: Annotated[int, Field(ge=0, le=32_000)]
    end: Annotated[int, Field(gt=0, le=32_000)]

    @model_validator(mode="after")
    def _ordered(self) -> AnswerClaimSpan:
        if self.end <= self.start:
            raise ValueError("answer claim span MUST be ordered")
        return self


class AnswerEvidenceRef(QueryContract):
    goal: Annotated[str, Field(pattern=r"^g[0-9]{1,2}$")]
    node: Annotated[str, Field(pattern=_ID)]
    row: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    field: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class AnswerLiteralBinding(QueryContract):
    """One literal shown in answer text and the exact evidence cell it renders."""

    span: AnswerClaimSpan
    value: str | int
    ref: AnswerEvidenceRef


class AnswerClaimProposition(QueryContract):
    """Canonical proposition fields shared by author, V-CLAIM, and reviewer."""

    subject: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    predicate: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    object: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    value: str | int | float | bool | None = None
    polarity: ClaimPolarity = ClaimPolarity.AFFIRM
    quantifier: ClaimQuantifier = ClaimQuantifier.EXACT
    unit: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    temporal_basis: ClaimTemporalBasis | None = None
    time_zone: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    modality: ClaimModality = ClaimModality.OBSERVED
    causal_class: ClaimCausalClass = ClaimCausalClass.NONE

    @model_validator(mode="after")
    def _causal_fields_are_consistent(self) -> AnswerClaimProposition:
        if self.causal_class is not ClaimCausalClass.NONE and (
            self.modality is not ClaimModality.HYPOTHESIS
        ):
            raise ValueError("causal claim propositions MUST be hypotheses")
        if self.currency is not None and self.unit is None:
            raise ValueError("currency claims MUST also declare a unit")
        return self


class AnswerClaim(QueryContract):
    id: Annotated[str, Field(pattern=r"^c[0-9]{1,2}$")]
    kind: AnswerClaimKind
    span: AnswerClaimSpan
    refs: Annotated[tuple[AnswerEvidenceRef, ...], Field(max_length=32)] = ()
    proposition: AnswerClaimProposition = AnswerClaimProposition()
    literals: Annotated[tuple[AnswerLiteralBinding, ...], Field(max_length=64)] = ()
    rows: Annotated[tuple[Annotated[str, Field(min_length=1)], ...], Field(max_length=1000)] = ()
    limitation_codes: Annotated[tuple[str, ...], Field(max_length=16)] = ()


class ComposedAnswer(QueryContract):
    """The author's prose and structured claims."""

    schema_version: Literal["1.0"] = "1.0"
    text: Annotated[str, Field(min_length=1, max_length=MAX_ANSWER_CHARS)]
    claims: Annotated[tuple[AnswerClaim, ...], Field(min_length=1, max_length=MAX_CLAIMS)]

    @model_validator(mode="after")
    def _spans_inside_text(self) -> ComposedAnswer:
        size = len(self.text)
        ids = [claim.id for claim in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("answer claim ids MUST be unique")
        for claim in self.claims:
            spans = [claim.span, *(item.span for item in claim.literals)]
            if any(item.end > size for item in spans):
                raise ValueError("answer claim span exceeds the answer text")
        return self


__all__ = [
    "AnswerClaim",
    "AnswerClaimKind",
    "AnswerClaimProposition",
    "AnswerClaimSpan",
    "AnswerEvidenceRef",
    "AnswerLiteralBinding",
    "ClaimCausalClass",
    "ClaimModality",
    "ClaimPolarity",
    "ClaimQuantifier",
    "ClaimTemporalBasis",
    "ComposedAnswer",
    "MAX_ANSWER_CHARS",
    "MAX_CLAIMS",
]
