"""IRP execution coordinator - alert -> investigate -> propose -> approve.

Slide 18: when an alert fires, the coordinator runs a fast (budgeted)
investigation, proposes a mitigation from the top recommendation, routes it
to a human approver (HIL - never auto-executes), and notifies Teams/Slack of
the decision. The executor + risk gate remain the sole authority over
"execute"; this coordinator only proposes and routes.

Fail-closed by construction: the upstream default approval gate
(:class:`DenyByDefaultApprovalGate`) rejects, so a mis-wired coordinator
never executes a change without a real approver bound.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import uuid4

from fdai.core.investigation import (
    InvestigationCoordinator,
    InvestigationOutcome,
    InvestigationReport,
    InvestigationRequest,
    Priority,
    Recommendation,
)
from fdai.core.irp.models import ResponsePlan

_LOGGER = logging.getLogger(__name__)

_DEFAULT_INVESTIGATION_BUDGET = 60.0
_DEFAULT_APPROVER_ROLE = "approver"

# A wedged investigator is bounded at this multiple of the budget. The grace
# above 1x lets a slow-but-finishing run return its partial findings (marked
# BUDGET_EXCEEDED) instead of being killed at exactly the budget, while still
# guaranteeing respond() cannot block forever on an infinite hang.
_HANG_GRACE = 2.0


class ApprovalDecision(StrEnum):
    """A human approver's decision on a proposed mitigation."""

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class IrpOutcome(StrEnum):
    """Terminal outcome of one alert response."""

    NO_FINDING = "no_finding"
    """Investigation produced no actionable recommendation - nothing proposed."""

    APPROVED = "approved"
    """Mitigation proposed and approved; routed to the pipeline (not executed here)."""

    REJECTED = "rejected"
    """Mitigation proposed but the approver rejected it - no-op."""

    TIMEOUT = "timeout"
    """Approval request timed out - no-op, fail closed."""


@dataclass(frozen=True, slots=True)
class Alert:
    """An inbound alert that drives an incident response."""

    alert_id: str
    signal: str
    resources: tuple[tuple[str, str], ...]
    fired_at: datetime

    def __post_init__(self) -> None:
        if not self.alert_id:
            raise ValueError("Alert.alert_id MUST be non-empty")
        if not self.resources:
            raise ValueError("Alert.resources MUST be non-empty")


@dataclass(frozen=True, slots=True)
class MitigationProposal:
    """A proposed, grounded mitigation awaiting human approval."""

    proposal_id: str
    alert_id: str
    remediation_ref: str
    detail: str
    priority: Priority
    approver_role: str
    citations: tuple[str, ...]
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class IrpResult:
    """Audit-shaped record of one alert response."""

    alert_id: str
    outcome: IrpOutcome
    report: InvestigationReport
    proposal: MitigationProposal | None
    decision: ApprovalDecision | None
    notified_channels: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
    investigation_within_budget: bool


@runtime_checkable
class ApprovalGate(Protocol):
    """Route a proposal to a human approver and return the decision."""

    async def request(self, proposal: MitigationProposal) -> ApprovalDecision: ...


@runtime_checkable
class IrpNotifier(Protocol):
    """Deliver a decision notification to operator channels."""

    async def notify(self, *, channels: Sequence[str], subject: str, body: str) -> None: ...


class DenyByDefaultApprovalGate:
    """Fail-closed default - rejects every proposal (no approver wired)."""

    async def request(self, proposal: MitigationProposal) -> ApprovalDecision:  # noqa: ARG002
        return ApprovalDecision.REJECTED


class NullNotifier:
    """Default notifier - drops notifications (records nothing)."""

    async def notify(self, *, channels: Sequence[str], subject: str, body: str) -> None:  # noqa: ARG002
        return None


class IrpCoordinator:
    """Wire an alert through investigate -> propose -> approve -> notify."""

    __slots__ = (
        "_approval",
        "_budget",
        "_default_channels",
        "_investigator",
        "_notifier",
        "_wall_clock",
    )

    def __init__(
        self,
        *,
        investigator: InvestigationCoordinator,
        approval_gate: ApprovalGate | None = None,
        notifier: IrpNotifier | None = None,
        default_channels: Sequence[str] = (),
        investigation_budget_seconds: float = _DEFAULT_INVESTIGATION_BUDGET,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._investigator = investigator
        self._approval: ApprovalGate = approval_gate or DenyByDefaultApprovalGate()
        self._notifier: IrpNotifier = notifier or NullNotifier()
        self._default_channels = tuple(default_channels)
        self._budget = investigation_budget_seconds
        self._wall_clock: Callable[[], datetime] = wall_clock or (lambda: datetime.now(tz=UTC))

    async def respond(self, alert: Alert, *, plan: ResponsePlan | None = None) -> IrpResult:
        started = self._wall_clock()
        channels = plan.notify_channels if plan and plan.notify_channels else self._default_channels
        approver_role = plan.approver_role if plan else _DEFAULT_APPROVER_ROLE

        request = InvestigationRequest(
            requested_by=f"irp:{alert.alert_id}",
            resources=alert.resources,
            budget_seconds=self._budget,
        )
        try:
            report = await asyncio.wait_for(
                self._investigator.investigate(request),
                timeout=self._budget * _HANG_GRACE,
            )
        except TimeoutError:
            _LOGGER.warning("irp_investigation_timed_out", extra={"alert_id": alert.alert_id})
            report = self._timed_out_report(request, started)
            await self._notify(
                channels,
                subject=f"[IRP] {alert.alert_id}: investigation timed out",
                body=(
                    f"Investigation exceeded {self._budget * _HANG_GRACE:g}s "
                    "(wedged backend); no action taken."
                ),
            )
            return self._result(alert, IrpOutcome.NO_FINDING, report, None, None, channels, started)

        top = self._top_actionable(report)
        if top is None:
            await self._notify(
                channels,
                subject=f"[IRP] {alert.alert_id}: no actionable finding",
                body=f"Investigation completed with no actionable recommendation "
                f"({len(report.findings)} finding(s)).",
            )
            return self._result(alert, IrpOutcome.NO_FINDING, report, None, None, channels, started)

        proposal = MitigationProposal(
            proposal_id=f"prop-{uuid4().hex[:12]}",
            alert_id=alert.alert_id,
            remediation_ref=top.remediation_ref or "",
            detail=top.detail,
            priority=top.priority,
            approver_role=approver_role,
            citations=top.citations,
            requested_at=self._wall_clock(),
        )
        decision = await self._approval.request(proposal)
        outcome = _DECISION_TO_OUTCOME[decision]

        await self._notify(
            channels,
            subject=f"[IRP] {alert.alert_id}: mitigation {decision.value}",
            body=(
                f"Proposed {proposal.remediation_ref} ({proposal.priority.value}); "
                f"decision={decision.value}. "
                + (
                    "Routing to the executor pipeline for gated execution."
                    if decision is ApprovalDecision.APPROVED
                    else "No action taken."
                )
            ),
        )
        return self._result(alert, outcome, report, proposal, decision, channels, started)

    @staticmethod
    def _top_actionable(report: InvestigationReport) -> Recommendation | None:
        """The highest-priority recommendation that names a remediation."""
        for rec in report.recommendations:
            if rec.remediation_ref:
                return rec
        return None

    def _timed_out_report(
        self, request: InvestigationRequest, started: datetime
    ) -> InvestigationReport:
        """Synthesize an empty BUDGET_EXCEEDED report for a wedged investigation."""
        bound = self._budget * _HANG_GRACE
        return InvestigationReport(
            investigation_id=f"inv-timeout-{uuid4().hex[:8]}",
            requested_by=request.requested_by,
            requested_at=started,
            window_seconds=request.window_seconds,
            resources=request.resources,
            outcome=InvestigationOutcome.BUDGET_EXCEEDED,
            findings=(),
            timeline=(),
            correlation=(),
            root_cause=None,
            recommendations=(),
            elapsed_seconds=bound,
            budget_seconds=request.budget_seconds,
            analyzer_errors=(("*", "investigation_timeout"),),
        )

    async def _notify(self, channels: Sequence[str], *, subject: str, body: str) -> None:
        if not channels:
            return
        try:
            await self._notifier.notify(channels=channels, subject=subject, body=body)
        except Exception:  # noqa: BLE001 - a notify failure must not abort the response
            _LOGGER.error("irp_notify_failed", extra={"subject": subject})

    def _result(
        self,
        alert: Alert,
        outcome: IrpOutcome,
        report: InvestigationReport,
        proposal: MitigationProposal | None,
        decision: ApprovalDecision | None,
        channels: Sequence[str],
        started: datetime,
    ) -> IrpResult:
        return IrpResult(
            alert_id=alert.alert_id,
            outcome=outcome,
            report=report,
            proposal=proposal,
            decision=decision,
            notified_channels=tuple(channels),
            started_at=started,
            ended_at=self._wall_clock(),
            investigation_within_budget=report.within_budget,
        )


_DECISION_TO_OUTCOME: dict[ApprovalDecision, IrpOutcome] = {
    ApprovalDecision.APPROVED: IrpOutcome.APPROVED,
    ApprovalDecision.REJECTED: IrpOutcome.REJECTED,
    ApprovalDecision.TIMEOUT: IrpOutcome.TIMEOUT,
}


__all__ = [
    "Alert",
    "ApprovalDecision",
    "ApprovalGate",
    "DenyByDefaultApprovalGate",
    "IrpCoordinator",
    "IrpNotifier",
    "IrpOutcome",
    "IrpResult",
    "MitigationProposal",
    "NullNotifier",
]
