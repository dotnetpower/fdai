"""Public result records for HIL approval requests and resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from fdai.core.executor import ExecutionResult
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.shared.providers.hil_channel import HilApprovalReceipt


class RequestOutcome(StrEnum):
    """Result of a HIL approval request."""

    PARKED = "parked"
    """Action parked and the approval card dispatched."""

    PARKED_DISPATCH_FAILED = "parked_dispatch_failed"
    """Action parked but delivery failed; the action remains pending."""

    PARKED_DEFERRED = "parked_deferred"
    """Action remains durably parked while notification delivery is deferred."""

    ALREADY_PARKED = "already_parked"
    """An exact replay found the same approval request already parked."""

    APPROVAL_ID_CONFLICT = "approval_id_conflict"
    """The approval ID was already bound to a different request."""

    CONTACT_CONSENT_REQUIRED = "contact_consent_required"
    """A report-line route is parked but no approval notification was sent."""

    REPORT_LINE_ROUTE_UNAVAILABLE = "report_line_route_unavailable"
    """The current reporting graph cannot satisfy the approval policy."""

    CONTACT_DECLINED = "contact_declined"
    """The requester declined to send the report-line approval request."""


class ResolveOutcome(StrEnum):
    """Approval-resolution result; execution truth may remain pending."""

    EXECUTED = "executed"
    """The approved action was accepted by the executor."""

    EXECUTE_FAILED = "execute_failed"
    """The approved action reached a terminal execution failure."""

    EXECUTION_PENDING = "execution_pending"
    """The approved action still requires independent effect reconciliation."""

    EXECUTION_NOT_ATTEMPTED = "execution_not_attempted"
    """The approved action did not reach an effect boundary."""

    REJECTED = "rejected"
    """The request was rejected without execution."""

    TIMED_OUT = "timed_out"
    """The request expired as a fail-closed no-op."""

    ALREADY_RESOLVED = "already_resolved"
    """The park already reached a terminal state."""

    NOT_FOUND = "not_found"
    """No parked request exists for the approval ID."""

    SELF_APPROVAL_REFUSED = "self_approval_refused"
    """The requester attempted to approve their own action."""

    MISSING_CAPABILITY = "missing_capability"
    """The approver lacks the required capability."""

    CONFLICTING_DECISION = "conflicting_decision"
    """A different terminal decision was already recorded."""

    OWNED_ROUTE_HELD = "owned_route_held"
    """A separately owned approval route never uses the legacy direct dispatcher."""

    CONTACT_CONSENT_REQUIRED = "contact_consent_required"
    """The action remains parked before any report-line approval notification."""


@dataclass(frozen=True, slots=True)
class RequestApprovalResult:
    outcome: RequestOutcome
    approval_id: str
    receipt: HilApprovalReceipt | None = None


@dataclass(frozen=True, slots=True)
class ResolveResult:
    outcome: ResolveOutcome
    approval_id: str
    execution_result: (
        ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult | None
    ) = None
    reason: str | None = None
    delegated: bool = False
    """True when an authorized operator approved on the assignee's behalf."""
    assignee_oid: str | None = None
    """The operator the park was surfaced to, when recorded."""


__all__ = [
    "RequestApprovalResult",
    "RequestOutcome",
    "ResolveOutcome",
    "ResolveResult",
]
