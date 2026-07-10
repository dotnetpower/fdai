"""Plan authoring - readiness gating + pretest (SRE-agent slide 17).

Pure, deterministic evaluators:

- :func:`evaluate_readiness` reports which requirements a plan has not yet
  satisfied. A plan with any unmet requirement is **blocked** from
  activation.
- :func:`activate` enforces the gate: it returns an ACTIVE copy of the plan
  only when every requirement is satisfied, else raises.
- :func:`pretest_plan` replays a plan's trigger against similar historical
  incidents and reports how many the plan's steps would have addressed -
  the "pre-test with similar past incidents" the slide describes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from fdai.core.irp.models import (
    HistoricalIncident,
    PlanStatus,
    PretestReport,
    ReadinessReport,
    RequirementKind,
    ResponsePlan,
)


class PlanNotReadyError(RuntimeError):
    """Raised when activating a plan with unmet requirements."""


def evaluate_readiness(plan: ResponsePlan) -> ReadinessReport:
    """Report unmet mandatory requirements for ``plan`` (pure).

    Every :class:`RequirementKind` is mandatory. A requirement is unmet
    when it is either missing from the plan entirely OR present but not
    satisfied - both block activation. Deriving readiness from the full
    mandatory set (not just the requirements the author chose to declare)
    closes the "omit a requirement to skip the gate" bypass: an empty
    requirements tuple is maximally unsafe, never ready.
    """
    satisfied = {req.kind for req in plan.requirements if req.satisfied}
    unmet = tuple(kind for kind in RequirementKind if kind not in satisfied)
    return ReadinessReport(plan_id=plan.plan_id, ready=not unmet, unmet=unmet)


def activate(plan: ResponsePlan) -> ResponsePlan:
    """Return an ACTIVE copy of ``plan`` iff every requirement is satisfied.

    The gate: a plan that is missing a stop-condition, rollback, blast-radius
    bound, approver, or notify channel MUST NOT be activated.
    """
    report = evaluate_readiness(plan)
    if report.blocked:
        raise PlanNotReadyError(
            f"plan {plan.plan_id} blocked; unmet={[k.value for k in report.unmet]}"
        )
    return replace(plan, status=PlanStatus.ACTIVE)


def pretest_plan(plan: ResponsePlan, incidents: Sequence[HistoricalIncident]) -> PretestReport:
    """Estimate how well ``plan`` would have handled past incidents.

    Only incidents whose signals include the plan's ``trigger_signal`` count
    toward the total. An incident is "matched" when one of the plan's step
    ``action_ref`` values equals the incident's ``resolved_by_action`` -
    i.e. the plan already contains the action that resolved it.
    """
    step_actions = {step.action_ref for step in plan.steps}
    triggering = [inc for inc in incidents if plan.trigger_signal in inc.signals]

    matched = 0
    unmatched: list[str] = []
    for incident in triggering:
        if incident.resolved_by_action is not None and incident.resolved_by_action in step_actions:
            matched += 1
        else:
            unmatched.append(incident.incident_ref)

    return PretestReport(
        plan_id=plan.plan_id,
        matched=matched,
        total=len(triggering),
        unmatched_incident_refs=tuple(unmatched),
    )


__all__ = [
    "PlanNotReadyError",
    "activate",
    "evaluate_readiness",
    "pretest_plan",
]
