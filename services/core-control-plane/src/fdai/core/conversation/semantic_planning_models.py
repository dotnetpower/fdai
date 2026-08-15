"""Contracts and injected seams for no-authority semantic planning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol

from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.core.ontology_platform import QueryManifest

from .session import Principal


class SemanticPlanningDisposition(StrEnum):
    PLANNED = "planned"
    CLARIFICATION = "clarification"
    ACTION_DRAFT = "action_draft"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class ClarificationRequirement(StrEnum):
    """Typed context category that a semantic frame still needs."""

    SUBJECT = "subject"
    MEASURE = "measure"
    TEMPORAL_SCOPE = "temporal_scope"
    COMPARISON_BASELINE = "comparison_baseline"
    OUTPUT_SHAPE = "output_shape"
    INCIDENT_REFERENCE = "incident_reference"
    RESOURCE_IDENTITY = "resource_identity"
    PRINCIPAL_SCOPE = "principal_scope"
    PURPOSE = "purpose"


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SemanticFrameProposal(_Proposal):
    """Untrusted model proposal without server-owned identity or authority fields."""

    operation: SemanticOperation
    subject_constraints: tuple[str, ...] = Field(default=(), max_length=32)
    measure_concepts: tuple[str, ...] = Field(default=(), max_length=16)
    temporal_scope: dict[str, Any] = Field(default_factory=dict)
    output_shape: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    evidence_requirements: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")], ...
    ] = Field(default=(), max_length=32)
    unresolved_terms: tuple[str, ...] = Field(default=(), max_length=8)
    clarification_requirements: tuple[ClarificationRequirement, ...] = Field(
        default=(), max_length=8
    )
    clarification: str | None = Field(default=None, min_length=1, max_length=512)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "subject_constraints",
        "measure_concepts",
        "evidence_requirements",
        "unresolved_terms",
    )
    @classmethod
    def _unique_bounded_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("semantic proposal terms MUST be unique")
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("semantic proposal terms MUST be bounded")
        return values

    @field_validator("clarification")
    @classmethod
    def _one_question(cls, value: str | None) -> str | None:
        if value is not None and ("\n" in value or "\r" in value or not value.endswith("?")):
            raise ValueError("semantic clarification MUST be one question")
        return value

    @model_validator(mode="after")
    def _clarification_is_typed(self) -> SemanticFrameProposal:
        if bool(self.unresolved_terms) != bool(self.clarification_requirements):
            raise ValueError("semantic unresolved terms require typed clarification requirements")
        if self.clarification is not None and not self.unresolved_terms:
            raise ValueError("semantic clarification requires unresolved terms")
        if len(self.clarification_requirements) != len(set(self.clarification_requirements)):
            raise ValueError("semantic clarification requirements MUST be unique")
        return self


class QueryNodeProposal(_Proposal):
    """One model-proposed node before canonical JSON serialization."""

    node_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    kind: QueryNodeKind
    depends_on: tuple[str, ...] = Field(default=(), max_length=8)
    arguments: dict[str, Any] = Field(default_factory=dict)
    output_kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")


class QueryPlanProposal(_Proposal):
    """Untrusted typed DAG proposal without release, principal, or digest fields."""

    nodes: tuple[QueryNodeProposal, ...] = Field(min_length=1, max_length=8)
    output_node_ids: tuple[str, ...] = Field(min_length=1, max_length=8)


class SemanticPlanningModel(Protocol):
    """Propose structured meaning and a typed DAG without executing either."""

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
    ) -> Mapping[str, Any] | None: ...

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
        evaluation_time: datetime,
    ) -> Mapping[str, Any] | None: ...


class QueryManifestProvider(Protocol):
    """Return one exact principal-scoped immutable query manifest."""

    def manifest_for(self, *, principal: Principal, purpose: str) -> QueryManifest: ...


class SemanticDescriptorSelector(Protocol):
    """Select bounded candidate descriptors without asserting semantic truth."""

    def select(
        self,
        *,
        utterance: str,
        manifest: QueryManifest,
        limit: int,
    ) -> Sequence[Mapping[str, Any]]: ...


class CompleteManifestSelector:
    """Use the complete manifest only while it fits the explicit descriptor bound."""

    def select(
        self,
        *,
        utterance: str,
        manifest: QueryManifest,
        limit: int,
    ) -> Sequence[Mapping[str, Any]]:
        del utterance
        if len(manifest.descriptors) > limit:
            raise ValueError("query manifest requires a semantic descriptor index")
        return manifest.descriptors


@dataclass(frozen=True, slots=True)
class SemanticPlanningOutcome:
    """One terminal planning disposition with no execution authority."""

    disposition: SemanticPlanningDisposition
    reason: str
    manifest_digest: str | None = None
    frame: SemanticProblemFrame | None = None
    plan: OntologyQueryPlan | None = None
    intent_graph: IntentGraph | None = None
    clarification: str | None = None
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority:
            raise ValueError("semantic planning outcome MUST NOT carry execution authority")
        planned = self.disposition is SemanticPlanningDisposition.PLANNED
        has_plan = (
            self.frame is not None and self.plan is not None and self.intent_graph is not None
        )
        if planned != has_plan:
            raise ValueError("planned semantic outcome requires frame, plan, and intent graph")
        clarification = self.disposition is SemanticPlanningDisposition.CLARIFICATION
        if clarification != (self.clarification is not None):
            raise ValueError("clarification disposition requires exactly one question")


__all__ = [
    "ClarificationRequirement",
    "CompleteManifestSelector",
    "QueryManifestProvider",
    "QueryNodeProposal",
    "QueryPlanProposal",
    "SemanticDescriptorSelector",
    "SemanticFrameProposal",
    "SemanticPlanningDisposition",
    "SemanticPlanningModel",
    "SemanticPlanningOutcome",
]
