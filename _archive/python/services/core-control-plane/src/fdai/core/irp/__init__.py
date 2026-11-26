"""Incident Response Plan (IRP) - authoring gate + alert response.

Slides 17-18 of the SRE-agent session notes:

- slide 17 - author a plan, gate its activation on satisfied requirements,
  and pretest it against similar historical incidents
  (:mod:`fdai.core.irp.authoring`).
- slide 18 - respond to an alert: budgeted investigation -> proposed
  mitigation -> HIL approval -> Teams/Slack notification
  (:class:`IrpCoordinator`). Never auto-executes.
"""

from __future__ import annotations

from fdai.core.irp.authoring import (
    PlanNotReadyError,
    activate,
    evaluate_readiness,
    pretest_plan,
)
from fdai.core.irp.coordinator import (
    Alert,
    ApprovalDecision,
    ApprovalGate,
    DenyByDefaultApprovalGate,
    IrpCoordinator,
    IrpNotifier,
    IrpOutcome,
    IrpResult,
    MitigationProposal,
    NullNotifier,
    ProposalRouter,
)
from fdai.core.irp.hil_gate import HilChannelApprovalGate
from fdai.core.irp.models import (
    HistoricalIncident,
    PlanRequirement,
    PlanStatus,
    PretestReport,
    ReadinessReport,
    RequirementKind,
    ResponsePlan,
    ResponseStep,
)

__all__ = [
    "Alert",
    "ApprovalDecision",
    "ApprovalGate",
    "DenyByDefaultApprovalGate",
    "HilChannelApprovalGate",
    "HistoricalIncident",
    "IrpCoordinator",
    "IrpNotifier",
    "IrpOutcome",
    "IrpResult",
    "MitigationProposal",
    "NullNotifier",
    "ProposalRouter",
    "PlanNotReadyError",
    "PlanRequirement",
    "PlanStatus",
    "PretestReport",
    "ReadinessReport",
    "RequirementKind",
    "ResponsePlan",
    "ResponseStep",
    "activate",
    "evaluate_readiness",
    "pretest_plan",
]
