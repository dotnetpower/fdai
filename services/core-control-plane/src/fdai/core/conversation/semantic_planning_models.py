"""Contracts and injected seams for no-authority semantic planning."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from fdai_service_contracts.ontology_query import (
    IntentGraph,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_turn import (
    SemanticDirectResponseIntent,
    context_selection_digest,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fdai.core.ontology_platform import QueryManifest

from .conversation_preflight import SocialAct
from .semantic_investigation import (
    InvestigationIntentProposal,
    VerifiedInvestigationIntent,
)
from .semantic_judgment import SemanticJudgmentObservation
from .session import Principal


class SemanticPlanningDisposition(StrEnum):
    PLANNED = "planned"
    DIRECT_RESPONSE = "direct_response"
    ADVISORY_RESPONSE = "advisory_response"
    CLARIFICATION = "clarification"
    ACTION_DRAFT = "action_draft"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BoundIncident:
    """Trusted incident identity carried by the conversation, never proposed by a model."""

    incident_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if not self.incident_id.strip() or not self.correlation_id.strip():
            raise ValueError("bound incident identifiers MUST NOT be empty")


@dataclass(frozen=True, slots=True)
class BoundResourceContext:
    """Trusted exact screen or resource-group scope for contextual reads."""

    kind: Literal["screen", "resource_group"]
    resource_ids: tuple[str, ...]
    screen_id: str | None = None
    resource_group_id: str | None = None
    principal_id: str = ""
    principal_scope_digest: str = ""
    ontology_release_digest: str = ""
    source_generation: str = ""
    selection_digest: str = ""
    selection_token: str = ""
    complete: bool = False

    def __post_init__(self) -> None:
        if (
            not self.resource_ids
            or self.resource_ids != tuple(dict.fromkeys(self.resource_ids))
            or not all(
                value.strip()
                for value in (
                    self.principal_id,
                    self.principal_scope_digest,
                    self.ontology_release_digest,
                    self.source_generation,
                    self.selection_digest,
                )
            )
            or not self.complete
        ):
            raise ValueError("bound resource context requires a complete server-issued identity")
        if self.kind == "screen" and not self.screen_id:
            raise ValueError("screen context requires screen_id")
        if self.kind == "resource_group" and not self.resource_group_id:
            raise ValueError("resource-group context requires resource_group_id")
        if self.selection_digest != context_selection_digest(
            kind=self.kind,
            principal_id=self.principal_id,
            principal_scope_digest=self.principal_scope_digest,
            ontology_release_digest=self.ontology_release_digest,
            source_generation=self.source_generation,
            complete=self.complete,
            screen_id=self.screen_id,
            resource_group_id=self.resource_group_id,
            resource_ids=self.resource_ids,
        ):
            raise ValueError("bound resource context selection digest does not match its identity")


@dataclass(frozen=True, slots=True)
class BoundInvestigationContinuation:
    """Trusted prior investigation identity resolved by Operator persistence."""

    source_session_id: str
    source_turn_id: str
    source_turn_sequence: int
    target_type: str
    target_value: str
    recovery_measure_concepts: tuple[str, ...]
    baseline_start: datetime
    baseline_end: datetime
    initial_observation_cutoff: datetime
    ontology_release_digest: str
    principal_manifest_digest: str
    source_frame_digest: str
    source_plan_digest: str
    source_execution_receipt_digest: str

    def __post_init__(self) -> None:
        if (
            not self.source_session_id.strip()
            or not self.source_turn_id.strip()
            or self.source_turn_sequence < 0
            or not self.target_type.strip()
            or not self.target_value.strip()
        ):
            raise ValueError("bound investigation continuation identity is invalid")
        if self.recovery_measure_concepts != tuple(sorted(set(self.recovery_measure_concepts))):
            raise ValueError("bound investigation continuation measures MUST be ordered")
        times = (self.baseline_start, self.baseline_end, self.initial_observation_cutoff)
        if any(value.tzinfo is None or value.utcoffset() is None for value in times):
            raise ValueError("bound investigation continuation times MUST be timezone-aware")
        if not self.baseline_start < self.baseline_end <= self.initial_observation_cutoff:
            raise ValueError("bound investigation continuation windows MUST be ordered")


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


class SemanticOutputShape(StrEnum):
    """Bind one frame digest to a deterministic query capability family."""

    ACTION_DRAFT = "action_draft"
    AGGREGATION_TABLE = "aggregation_table"
    CAUSAL_EVIDENCE = "causal_evidence"
    EVIDENCE_VALIDATION = "evidence_validation"
    INCIDENT_EVIDENCE = "incident_evidence"
    INVENTORY_IMPACT = "inventory_impact"
    ONTOLOGY_DECLARATION = "ontology_declaration"
    ONTOLOGY_MANIFEST = "ontology_manifest"
    ONTOLOGY_RELATIONSHIPS = "ontology_relationships"
    ONTOLOGY_RELEASE_EVIDENCE_HEALTH = "ontology_release_evidence_health"
    CONTEXTUAL_RESOURCE_LIST = "contextual_resource_list"
    PROPERTY_FILTERED_RESOURCES = "property_filtered_resources"
    RESOURCE_LIST = "resource_list"
    RESOURCE_EVENT_HISTORY = "resource_event_history"
    RESOURCE_CONDITION_SECTIONS = "resource_condition_sections"
    RESOURCE_HEALTH_LIST = "resource_health_list"
    RESOURCE_METRIC_LIST = "resource_metric_list"
    RESOURCE_STATE_LIST = "resource_state_list"
    RESOURCE_STATE_TRANSITIONS = "resource_state_transitions"
    RESOURCE_TARGET_CANDIDATES = "resource_target_candidates"
    SUBSCRIPTION_SCOPE_IDENTITY = "subscription_scope_identity"
    SUBSCRIPTION_SERVICE_HEALTH = "subscription_service_health"
    TARGET_ACTIVITY = "target_activity"
    TARGET_CURRENT_STATE = "target_current_state"
    TARGET_ERROR_ACTIVITY_CORRELATION = "target_error_activity_correlation"
    TARGET_HEALTH_ASSESSMENT = "target_health_assessment"
    TARGET_INGRESS_CONFIGURATION = "target_ingress_configuration"
    TARGET_RESOURCE_METRIC = "target_resource_metric"
    TARGET_RESOURCE_METRIC_SERIES = "target_resource_metric_series"
    TEMPORAL_COMPARISON = "temporal_comparison"
    TOPOLOGY_GRAPH = "topology_graph"


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SemanticFrameProposal(_Proposal):
    """Untrusted model proposal without server-owned identity or authority fields."""

    operation: SemanticOperation
    subject_constraints: tuple[str, ...] = Field(default=(), max_length=32)
    measure_concepts: tuple[str, ...] = Field(default=(), max_length=16)
    temporal_scope: dict[str, Any] = Field(default_factory=dict)
    output_shape: SemanticOutputShape
    evidence_requirements: tuple[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")], ...
    ] = Field(default=(), max_length=32)
    unresolved_terms: tuple[str, ...] = Field(default=(), max_length=8)
    clarification_requirements: tuple[ClarificationRequirement, ...] = Field(
        default=(), max_length=8
    )
    clarification: str | None = Field(default=None, min_length=1, max_length=512)
    investigation: InvestigationIntentProposal | None
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


@dataclass(frozen=True, slots=True)
class SemanticPlanningModelResponse(Mapping[str, Any]):
    """Carry one planning proposal with its bounded model observation."""

    proposal: Mapping[str, Any]
    observation: SemanticJudgmentObservation

    def __getitem__(self, key: str) -> Any:
        return self.proposal[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.proposal)

    def __len__(self) -> int:
        return len(self.proposal)


class SemanticPlanningModel(Protocol):
    """Propose structured meaning and a typed DAG without executing either."""

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        semantic_judgment: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None: ...

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        evaluation_time: datetime,
    ) -> Mapping[str, Any] | None: ...


@runtime_checkable
class SemanticPlanningEscalationModel(Protocol):
    """Accept compact server-owned recovery context for a T2 retry."""

    def propose_escalated_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        semantic_judgment: Mapping[str, Any] | None,
        recovery_context: Mapping[str, str],
    ) -> Mapping[str, Any] | None: ...

    def propose_escalated_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        evaluation_time: datetime,
        recovery_context: Mapping[str, str],
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
    investigation_intent: VerifiedInvestigationIntent | None = None
    clarification: str | None = None
    direct_response_intent: SemanticDirectResponseIntent | None = None
    direct_response_answer: str | None = None
    social_act: SocialAct = SocialAct.NONE
    model_observations: tuple[SemanticJudgmentObservation, ...] = ()
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
        if self.investigation_intent is not None and not planned:
            raise ValueError("verified investigation intent requires a planned outcome")
        clarification = self.disposition is SemanticPlanningDisposition.CLARIFICATION
        if clarification != (self.clarification is not None):
            raise ValueError("clarification disposition requires exactly one question")
        direct_response = self.disposition is SemanticPlanningDisposition.DIRECT_RESPONSE
        if direct_response != (
            self.direct_response_intent is not None and self.direct_response_answer is not None
        ):
            raise ValueError(
                "direct response disposition requires exactly one model-authored answer"
            )
        if not direct_response and self.direct_response_answer is not None:
            raise ValueError("non-direct semantic outcome MUST NOT carry a direct response answer")


__all__ = [
    "BoundIncident",
    "BoundInvestigationContinuation",
    "BoundResourceContext",
    "ClarificationRequirement",
    "CompleteManifestSelector",
    "QueryManifestProvider",
    "QueryNodeProposal",
    "QueryPlanProposal",
    "SemanticDescriptorSelector",
    "SemanticDirectResponseIntent",
    "SemanticFrameProposal",
    "SemanticOutputShape",
    "SemanticPlanningDisposition",
    "SemanticPlanningEscalationModel",
    "SemanticPlanningModel",
    "SemanticPlanningOutcome",
]
