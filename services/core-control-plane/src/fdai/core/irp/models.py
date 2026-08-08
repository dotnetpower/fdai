"""Incident Response Plan (IRP) models (SRE-agent slides 17-18).

An IRP is a **pre-authored, gated response** to a class of alert. Slide 17
covers authoring: a plan names its trigger signal, an ordered set of
response steps, a set of **requirements that MUST be satisfied before the
plan can be activated** (the gate), and the approver + notify channels.
Slide 18 covers execution: an alert drives a fast investigation, a proposed
mitigation, HIL approval, and a Teams/Slack notification.

Everything here is inert data + pure evaluation. Activation gating and
pretest are deterministic; the coordinator (slide 18) never auto-executes -
it proposes and routes to approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RequirementKind(StrEnum):
    """A safety requirement a plan MUST satisfy before activation.

    Mirrors the action-level stop, rollback, and impact declarations plus
    the approval and notification wiring the IRP needs before it can enter
    a seven-safeguard execution path.
    """

    STOP_CONDITION = "stop_condition"
    ROLLBACK_DEFINED = "rollback_defined"
    BLAST_RADIUS_BOUNDED = "blast_radius_bounded"
    APPROVER_ASSIGNED = "approver_assigned"
    NOTIFY_CHANNEL = "notify_channel"


class PlanStatus(StrEnum):
    """Lifecycle state of a response plan."""

    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class PlanRequirement:
    """One gating requirement and whether the author satisfied it."""

    kind: RequirementKind
    description: str
    satisfied: bool = False


@dataclass(frozen=True, slots=True)
class ResponseStep:
    """One step in a response plan - names an ActionType, never executes it."""

    step_id: str
    action_ref: str
    description: str

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("ResponseStep.step_id MUST be non-empty")
        if not self.action_ref:
            raise ValueError("ResponseStep.action_ref MUST be non-empty")


@dataclass(frozen=True, slots=True)
class ResponsePlan:
    """A pre-authored incident response plan.

    ``trigger_signal`` is the detection signal that fires the plan (matching
    the investigation analyzers' ``signal`` vocabulary). ``approver_role``
    is the RBAC role that MUST approve execution - a plan never
    auto-executes.
    """

    plan_id: str
    name: str
    trigger_signal: str
    steps: tuple[ResponseStep, ...]
    requirements: tuple[PlanRequirement, ...]
    approver_role: str
    notify_channels: tuple[str, ...]
    created_by: str
    created_at: datetime
    status: PlanStatus = PlanStatus.DRAFT
    similar_incident_refs: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("ResponsePlan.plan_id MUST be non-empty")
        if not self.trigger_signal:
            raise ValueError("ResponsePlan.trigger_signal MUST be non-empty")
        if not self.created_by:
            raise ValueError("ResponsePlan.created_by MUST be non-empty")


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """The outcome of the activation gate for one plan."""

    plan_id: str
    ready: bool
    unmet: tuple[RequirementKind, ...]

    @property
    def blocked(self) -> bool:
        return not self.ready


@dataclass(frozen=True, slots=True)
class HistoricalIncident:
    """A resolved incident used to pretest a plan (customer-agnostic)."""

    incident_ref: str
    signals: tuple[str, ...]
    resolved_by_action: str | None = None


@dataclass(frozen=True, slots=True)
class PretestReport:
    """Coverage of a plan against a set of similar historical incidents."""

    plan_id: str
    matched: int
    total: int
    unmatched_incident_refs: tuple[str, ...]

    @property
    def coverage(self) -> float:
        """Fraction of triggering incidents the plan's steps would address."""
        if self.total == 0:
            return 0.0
        return self.matched / self.total


__all__ = [
    "HistoricalIncident",
    "PlanRequirement",
    "PlanStatus",
    "PretestReport",
    "ReadinessReport",
    "RequirementKind",
    "ResponsePlan",
    "ResponseStep",
]
