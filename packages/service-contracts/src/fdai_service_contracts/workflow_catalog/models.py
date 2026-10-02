"""Workflow catalog model shared by Core and Operator."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from fdai_service_contracts.workflow_catalog.base import SemVer, WorkflowCatalogBase
from fdai_service_contracts.workflow_catalog.enums import (
    CeilingRole,
    Mode,
    WorkflowStepKind,
    WorkflowTriggerKind,
    WorkflowTriggerSignalReferenceKind,
)


class PromotionGate(WorkflowCatalogBase):
    min_shadow_days: Annotated[int, Field(ge=1)]
    min_samples: Annotated[int, Field(ge=1)]
    min_accuracy: Annotated[float, Field(ge=0.0, le=1.0)]
    max_policy_escapes: Annotated[int, Field(ge=0)]
    min_fidelity: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    max_recurrence_rate: Annotated[float, Field(ge=0.0, le=1.0)] | None = None


class WorkflowTrigger(WorkflowCatalogBase):
    """The event or schedule that starts a Workflow run."""

    kind: WorkflowTriggerKind
    signal_type: str | None = None
    signal_reference_kind: WorkflowTriggerSignalReferenceKind | None = None
    schedule: str | None = None

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> WorkflowTrigger:
        if self.kind is WorkflowTriggerKind.SIGNAL and not self.signal_type:
            raise ValueError("trigger.kind=signal requires a non-empty signal_type")
        if self.kind is WorkflowTriggerKind.SCHEDULE and not self.schedule:
            raise ValueError("trigger.kind=schedule requires a non-empty schedule")
        return self


class WorkflowStep(WorkflowCatalogBase):
    """One step in a Workflow declaration."""

    id: Annotated[str, Field(min_length=1)]
    kind: WorkflowStepKind = WorkflowStepKind.ACTION
    action_type_ref: Annotated[str, Field(min_length=1)] | None = None
    guard_rule_ref: str | None = None
    gate_ref: Annotated[str, Field(min_length=1)] | None = None
    compensated_by: str | None = None
    on_failure: str | None = None
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)
    wait_for: Annotated[str, Field(min_length=1)] | None = None
    timeout_seconds: Annotated[int, Field(ge=1)] | None = None
    approval_role: CeilingRole | None = None
    quorum: Annotated[int, Field(ge=1)] = 1
    no_self_approval: bool = True
    outcomes: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )
    branches: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _kind_contract(self) -> WorkflowStep:
        if not self.no_self_approval:
            raise ValueError(
                "no_self_approval MUST stay enabled; catalog data cannot authorize self-approval"
            )
        if self.kind is WorkflowStepKind.ACTION:
            if self.action_type_ref is None:
                raise ValueError("action step requires action_type_ref")
        elif self.action_type_ref is not None:
            raise ValueError(f"{self.kind.value} step MUST NOT declare action_type_ref")
        if self.kind is WorkflowStepKind.WAIT:
            if self.wait_for is None or self.timeout_seconds is None:
                raise ValueError("wait step requires wait_for and timeout_seconds")
        elif self.kind is WorkflowStepKind.APPROVAL:
            if self.approval_role is None or self.timeout_seconds is None:
                raise ValueError("approval step requires approval_role and timeout_seconds")
        elif self.kind is WorkflowStepKind.DECISION:
            if len(self.outcomes) < 2 or len(set(self.outcomes)) != len(self.outcomes):
                raise ValueError("decision step requires at least 2 unique outcomes")
        elif self.kind is WorkflowStepKind.PARALLEL:
            if len(self.branches) < 2 or len(set(self.branches)) != len(self.branches):
                raise ValueError("parallel step requires at least 2 unique branches")
        elif self.kind is WorkflowStepKind.GATE and self.gate_ref is None:
            raise ValueError("gate step requires gate_ref")
        elif self.kind is WorkflowStepKind.EVIDENCE:
            required = {"policy_id", "policy_version", "source_url"}
            missing = sorted(required - self.params.keys())
            if missing:
                raise ValueError(f"evidence step requires params: {', '.join(missing)}")
        if self.compensated_by is not None and self.kind is not WorkflowStepKind.ACTION:
            raise ValueError("compensated_by is supported only on action steps")
        return self


class Workflow(WorkflowCatalogBase):
    """A declarative business process."""

    schema_version: SemVer
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_\.\-]{0,79}$")]
    version: SemVer
    trigger: WorkflowTrigger
    default_mode: Mode = Mode.SHADOW
    promotion_gate: PromotionGate
    steps: Annotated[list[WorkflowStep], Field(min_length=1)]
    description: Annotated[str, Field(max_length=200)] | None = None
    anti_scope: str | None = None

    @model_validator(mode="after")
    def _structural_invariants(self) -> Workflow:
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"duplicate step id {step.id!r}")
            seen.add(step.id)
        index_by_id = {step.id: i for i, step in enumerate(self.steps)}
        for i, step in enumerate(self.steps):
            if step.on_failure is None:
                continue
            if step.on_failure == step.id:
                raise ValueError(
                    f"step {step.id!r} on_failure points at itself; "
                    "a step cannot be its own failure fallback"
                )
            if step.on_failure not in seen:
                raise ValueError(f"step {step.id!r} on_failure -> unknown step {step.on_failure!r}")
            if index_by_id[step.on_failure] <= i:
                raise ValueError(
                    f"step {step.id!r} on_failure -> {step.on_failure!r} must appear "
                    "later in the workflow; a backward fallback would re-run an "
                    "already-applied step"
                )
        return self


__all__ = ["PromotionGate", "Workflow", "WorkflowStep", "WorkflowTrigger"]
