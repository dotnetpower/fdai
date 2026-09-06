"""Bound untrusted adaptive answer plans, authored sections, and independent reviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fdai_service_contracts.ontology_query import EvidenceAuthority
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .adaptive_prompt import AdaptiveModel as AdaptiveModel

GoalId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")]
GoalKind = Literal["knowledge", "operational", "environment_example"]


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdaptiveGoal(_Candidate):
    """One candidate answer goal; its kind is not evidence or permission."""

    goal_id: GoalId
    kind: GoalKind
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    required: StrictBool


class AdaptivePlan(_Candidate):
    """Separate social expression from substantive goals without lexical routing."""

    route: Literal["legacy", "adaptive"]
    social_act: Literal["none", "greeting", "thanks", "farewell", "self_introduction"]
    context_dependency: Literal["none", "active_thread", "pending_decision"]
    action_requested: StrictBool
    goals: Annotated[tuple[AdaptiveGoal, ...], Field(max_length=6)]

    @model_validator(mode="after")
    def _goals_are_consistent(self) -> AdaptivePlan:
        if len({goal.goal_id for goal in self.goals}) != len(self.goals):
            raise ValueError("adaptive goal identifiers must be unique")
        if sum(goal.kind != "knowledge" for goal in self.goals) > 2:
            raise ValueError("adaptive plan permits at most two read goals")
        if any(goal.kind == "environment_example" and goal.required for goal in self.goals):
            raise ValueError("environment examples must remain optional")
        has_knowledge = any(goal.kind == "knowledge" and goal.required for goal in self.goals)
        if self.route == "adaptive" and not has_knowledge:
            raise ValueError("adaptive route requires a substantive knowledge goal")
        if (
            self.route == "legacy"
            and has_knowledge
            and not self.action_requested
            and self.context_dependency != "pending_decision"
        ):
            raise ValueError("knowledge goals require the adaptive route")
        return self


class AdaptiveSection(_Candidate):
    """Proposed prose for one goal, without model-authored evidence references."""

    goal_id: GoalId
    text: Annotated[str, Field(min_length=1, max_length=6000)]


class AdaptiveDraft(_Candidate):
    """Bounded authored sections, validated against the server's selected goal set."""

    sections: Annotated[tuple[AdaptiveSection, ...], Field(min_length=1, max_length=6)]

    @model_validator(mode="after")
    def _sections_are_unique(self) -> AdaptiveDraft:
        if len({section.goal_id for section in self.sections}) != len(self.sections):
            raise ValueError("adaptive answer sections must be unique")
        if sum(len(section.text) for section in self.sections) > 14000:
            raise ValueError("adaptive answer exceeds its text budget")
        return self


class AdaptiveReview(_Candidate):
    """Independent model critique; deterministic coverage checks remain mandatory."""

    safe: StrictBool
    complete: StrictBool
    supported_goal_ids: Annotated[tuple[GoalId, ...], Field(max_length=6)]
    issues: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=500)], ...],
        Field(max_length=8),
    ]


@dataclass(frozen=True, slots=True)
class AdaptiveEvidence:
    """A bounded, server-verified read result, not an inferred model claim."""

    status: Literal["answered", "unavailable", "held"]
    content: str = ""
    evidence_refs: tuple[str, ...] = ()
    limitation: str | None = None
    authorities: tuple[EvidenceAuthority, ...] = ()

    def __post_init__(self) -> None:
        if len(self.content) > 12000 or len(self.evidence_refs) > 12:
            raise ValueError("adaptive evidence exceeds its bound")
        if self.status == "answered" and (not self.evidence_refs or not self.content):
            raise ValueError("answered environment evidence requires content and references")
        if any(not ref.strip() or len(ref) > 256 for ref in self.evidence_refs):
            raise ValueError("adaptive evidence references must be bounded")
        if self.status != "answered" and (self.content or self.evidence_refs):
            raise ValueError("unavailable evidence must not carry answer content")
        if self.status != "answered" and (not self.limitation or len(self.limitation) > 2000):
            raise ValueError("unavailable evidence requires a bounded explicit limitation")
        if any(not isinstance(authority, EvidenceAuthority) for authority in self.authorities):
            raise ValueError("adaptive evidence requires canonical authority values")


@dataclass(frozen=True, slots=True)
class AdaptivePolicy:
    """Explicit per-turn limits; stronger models never receive more authority."""

    total_seconds: float = 60
    per_stage_seconds: float = 20
    max_calls: int = 5
    max_tokens: int = 48000
    max_input_bytes: int = 64000
    reserved_output_tokens: int = 4096
    refinement_enabled: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.per_stage_seconds <= self.total_seconds <= 120:
            raise ValueError("adaptive deadlines must be positive and bounded")
        if not 3 <= self.max_calls <= 5 or not 4096 <= self.max_tokens <= 96000:
            raise ValueError("adaptive model budgets are invalid")
        if not 4096 <= self.max_input_bytes <= 128000:
            raise ValueError("adaptive input budget is invalid")
        if not 256 <= self.reserved_output_tokens <= 4096:
            raise ValueError("adaptive output reservation is invalid")


DEFAULT_ADAPTIVE_POLICY = AdaptivePolicy()
