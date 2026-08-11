"""Typed no-authority records for Operator-to-Core semantic turns."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from fdai_service_contracts.ontology_query import QueryContract
from fdai_service_contracts.operator import OperatorRole

Digest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
BoundedId = Annotated[str, Field(min_length=1, max_length=256)]


class SemanticTurnDisposition(StrEnum):
    """Terminal outcomes accepted by the semantic conversation boundary."""

    ANSWERED = "answered"
    HELD = "held"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"
    ACTION_DRAFT = "action_draft"
    CANCELLED = "cancelled"


class SemanticTurnPrincipal(QueryContract):
    """Authenticated Operator identity and server-derived roles."""

    subject_id: BoundedId
    roles: Annotated[tuple[OperatorRole, ...], Field(min_length=1, max_length=4)]

    @model_validator(mode="after")
    def _roles_are_unique(self) -> SemanticTurnPrincipal:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("semantic turn principal roles MUST be unique")
        return self


class SemanticPriorTurn(QueryContract):
    """One bounded untrusted history item supplied for context resolution."""

    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=8_000)]


class SemanticTurnRequest(QueryContract):
    """One bounded ordinary-language request with no execution authority."""

    utterance: Annotated[str, Field(min_length=1, max_length=32_000)]
    principal: SemanticTurnPrincipal
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    locale: Annotated[str, Field(min_length=2, max_length=35)]
    purpose: Annotated[str, Field(min_length=1, max_length=128)]
    deadline_at: datetime
    view_context_digest: Digest | None = None
    prior_turns: Annotated[tuple[SemanticPriorTurn, ...], Field(max_length=12)] = ()
    cancelled: bool = False
    execution_authority: Literal[False] = False


class SemanticTurnResult(QueryContract):
    """One evidence-bound terminal semantic result with no action authority."""

    disposition: SemanticTurnDisposition
    reason_code: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")]
    session_id: BoundedId
    turn_id: BoundedId
    turn_sequence: Annotated[int, Field(ge=0)]
    ontology_release_digest: Digest | None = None
    principal_manifest_digest: Digest | None = None
    plan_digest: Digest | None = None
    execution_receipt_digest: Digest | None = None
    intent_graph: dict[str, Any] | None = None
    intent_graph_evidence: dict[str, Any] | None = None
    evidence_refs: Annotated[tuple[BoundedId, ...], Field(max_length=12)] = ()
    checks_completed: Annotated[int, Field(ge=0, le=64)] = 0
    checks_total: Annotated[int, Field(ge=0, le=64)] = 0
    answer: Annotated[str, Field(min_length=1, max_length=64_000)] | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _evidence_is_consistent(self) -> SemanticTurnResult:
        if self.checks_completed > self.checks_total:
            raise ValueError("semantic checks_completed MUST NOT exceed checks_total")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("semantic evidence_refs MUST be unique")
        exact = (
            self.ontology_release_digest,
            self.principal_manifest_digest,
            self.plan_digest,
            self.execution_receipt_digest,
        )
        if self.disposition is SemanticTurnDisposition.ANSWERED and (
            any(item is None for item in exact)
            or not self.evidence_refs
            or self.checks_total == 0
            or self.checks_completed != self.checks_total
            or self.answer is None
        ):
            raise ValueError("answered semantic results MUST carry complete verified evidence")
        return self


__all__ = [
    "SemanticPriorTurn",
    "SemanticTurnDisposition",
    "SemanticTurnPrincipal",
    "SemanticTurnRequest",
    "SemanticTurnResult",
]
