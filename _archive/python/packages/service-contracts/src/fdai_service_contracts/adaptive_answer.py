"""Immutable advisory answers with goal-local support and no execution authority."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.ontology_query import QueryContract

AdaptiveAgentName = Literal[
    "Odin",
    "Heimdall",
    "Huginn",
    "Forseti",
    "Var",
    "Thor",
    "Vidar",
    "Saga",
    "Bragi",
    "Njord",
    "Freyr",
    "Loki",
    "Mimir",
    "Norns",
    "Muninn",
]


class AdaptiveGoalResult(QueryContract):
    """Classify one advisory goal without attributing evidence to general knowledge."""

    goal_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")]
    kind: Literal["knowledge", "operational", "environment_example"]
    status: Literal["answered", "unavailable", "held"]
    required: Annotated[bool, Field(strict=True)]
    evidence_refs: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=256)], ...],
        Field(max_length=12),
    ] = ()
    limitation: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None

    @model_validator(mode="after")
    def _support_is_goal_local(self) -> AdaptiveGoalResult:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("adaptive goal evidence references MUST be unique")
        if self.kind == "knowledge" and self.evidence_refs:
            raise ValueError("general knowledge MUST NOT claim operational evidence")
        if self.kind != "knowledge" and self.status == "answered" and not self.evidence_refs:
            raise ValueError("answered environment goals require verified evidence references")
        if self.status != "answered" and self.evidence_refs:
            raise ValueError("unanswered adaptive goals MUST NOT claim supporting evidence")
        if self.status != "answered" and self.limitation is None:
            raise ValueError("unanswered adaptive goals require an explicit limitation")
        return self


class AdaptiveAnswer(QueryContract):
    """Bounded advice, not a query execution receipt, approval, or action result."""

    answer: Annotated[str, Field(min_length=1, max_length=16_000)]
    goals: Annotated[tuple[AdaptiveGoalResult, ...], Field(min_length=1, max_length=8)]
    role_agent: AdaptiveAgentName
    quality_status: Literal["passed", "limited"]
    refinements: Annotated[int, Field(strict=True, ge=0, le=1)] = 0
    execution_authority: Literal[False] = False

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _authority_is_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("adaptive answers MUST NOT carry execution authority")
        return value

    @model_validator(mode="after")
    def _goals_are_consistent(self) -> AdaptiveAnswer:
        if len({goal.goal_id for goal in self.goals}) != len(self.goals):
            raise ValueError("adaptive goal identifiers MUST be unique")
        if self.quality_status == "passed" and any(
            goal.required and goal.status != "answered" for goal in self.goals
        ):
            raise ValueError("unresolved required goals require limited answer quality")
        return self
