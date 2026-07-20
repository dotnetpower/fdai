"""Incident-specific branch of the write-direction console chat route."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fdai.core.incident.intent import IncidentCreationProposal
from fdai.core.incident.lifecycle import IncidentConfirmationError, IncidentWorkflowResult
from fdai.core.incident.proposal_store import IncidentProposalStore
from fdai.core.incident.workflow import IncidentLifecycleWorkflow
from fdai.core.rbac.resolver import Principal
from fdai.core.rbac.roles import Role
from fdai.shared.contracts.models import IncidentSeverity, IncidentState

_UUID = r"(?P<incident_id>[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})"
_STATE = r"(?P<state>open|triaging|mitigated|resolved|closed)"
_TRANSITION_PATTERNS = (
    re.compile(
        rf"^(?:transition|set)\s+incident\s+{_UUID}\s+(?:to|state)\s+{_STATE}$",
        re.I,
    ),
    re.compile(rf"^incident\s+{_UUID}\s+상태\s+{_STATE}(?:으로|로)?\s+변경$", re.I),
)
_ASSIGN_PATTERNS = (
    re.compile(rf"^assign\s+incident\s+{_UUID}\s+to\s+(?P<assignee>\S+)$", re.I),
    re.compile(rf"^incident\s+{_UUID}\s+담당자\s+(?P<assignee>\S+)\s+지정$", re.I),
)


@dataclass(frozen=True, slots=True)
class _IncidentPrincipal:
    """Read-API principal projected onto the incident workflow contract."""

    id: str
    role: str


async def submit_incident_chat(
    *,
    workflow: IncidentLifecycleWorkflow,
    proposals: IncidentProposalStore,
    question: str,
    principal: Principal,
    session_id: str | None,
    correlation_id: str,
    max_question_chars: int,
) -> dict[str, Any] | None:
    """Prepare or confirm an incident request; return None for other intents."""
    if _is_ticket_action_request(question):
        return None
    session_key = (session_id or "").strip()
    workflow_principal = _workflow_principal(principal)
    lifecycle_command = _parse_lifecycle_command(question)
    if lifecycle_command is not None:
        if not session_key:
            return _session_required(correlation_id)
        return await _apply_lifecycle_command(
            workflow=workflow,
            principal=workflow_principal,
            correlation_id=correlation_id,
            command=lifecycle_command,
        )
    decision = _confirmation_decision(question)
    if decision is not None:
        if not session_key:
            return _session_required(correlation_id)
        return await _consume_confirmation(
            workflow=workflow,
            proposals=proposals,
            question=question,
            principal=principal,
            workflow_principal=workflow_principal,
            session_key=session_key,
            correlation_id=correlation_id,
            decision=decision,
        )

    turn = workflow.prepare_chat(
        text=question[:max_question_chars],
        principal=workflow_principal,
    )
    if turn.status == "not_incident":
        return None
    if not session_key:
        return _session_required(correlation_id)
    if turn.status == "needs_details":
        return {
            "submitted": False,
            "reason": "incident_details_required",
            "correlation_id": correlation_id,
            "action_type": "incident.create",
            "message": turn.response,
        }
    proposal = cast(IncidentCreationProposal, turn.proposal)
    await proposals.save(
        operator_id=principal.oid,
        session_id=session_key,
        proposal=proposal,
    )
    return {
        "submitted": False,
        "reason": "incident_confirmation_required",
        "correlation_id": correlation_id,
        "action_type": "incident.create",
        "severity": proposal.severity.value,
        "correlation_keys": list(proposal.correlation_keys),
        "expires_at": proposal.expires_at.isoformat(),
        "message": turn.response,
    }


async def open_investigation_incident(
    *,
    workflow: IncidentLifecycleWorkflow,
    principal: Principal,
    session_id: str,
    resource_kind: str,
    resource_ref: str,
    severity: IncidentSeverity,
) -> IncidentWorkflowResult:
    """Open or reuse the Incident confirmed by an explicit investigation command."""
    return await workflow.open_confirmed_operator(
        principal=_workflow_principal(principal),
        correlation_keys=(
            f"resource:{resource_ref}",
            f"investigation:{resource_kind}",
            f"session:{session_id}",
        ),
        severity=severity,
    )


async def _consume_confirmation(
    *,
    workflow: IncidentLifecycleWorkflow,
    proposals: IncidentProposalStore,
    question: str,
    principal: Principal,
    workflow_principal: _IncidentPrincipal,
    session_key: str,
    correlation_id: str,
    decision: str,
) -> dict[str, Any] | None:
    now = datetime.now(tz=UTC)
    taken = await proposals.take(
        operator_id=principal.oid,
        session_id=session_key,
        now=now,
    )
    if taken.status == "expired":
        return {
            "submitted": False,
            "reason": "incident_confirmation_expired",
            "correlation_id": correlation_id,
            "action_type": "incident.create",
            "message": "Incident proposal expired; prepare a new request.",
        }
    if taken.status == "missing":
        return None
    pending = cast(IncidentCreationProposal, taken.proposal)
    if decision == "cancel":
        return {
            "submitted": False,
            "reason": "incident_creation_cancelled",
            "correlation_id": correlation_id,
            "action_type": "incident.create",
            "message": "Incident creation cancelled.",
        }
    try:
        result = await workflow.confirm_chat(
            proposal=pending,
            principal=workflow_principal,
            confirmation=question,
            now=now,
        )
    except IncidentConfirmationError as exc:
        return {
            "submitted": False,
            "reason": "incident_confirmation_invalid",
            "correlation_id": correlation_id,
            "action_type": "incident.create",
            "message": str(exc),
        }
    return {
        "submitted": True,
        "correlation_id": str(result.incident.incident_id),
        "action_type": "incident.create",
        "incident_id": str(result.incident.incident_id),
        "incident_state": result.incident.state.value,
        "created": result.created,
        "message": result.response,
    }


def _workflow_principal(principal: Principal) -> _IncidentPrincipal:
    if Role.OWNER in principal.roles:
        role = "owner"
    elif Role.APPROVER in principal.roles:
        role = "approver"
    elif Role.CONTRIBUTOR in principal.roles:
        role = "contributor"
    else:
        role = "reader"
    return _IncidentPrincipal(id=principal.oid, role=role)


def _confirmation_decision(question: str) -> str | None:
    normalized = question.strip().lower()
    if normalized in {"confirm", "confirmed", "yes", "proceed", "확인", "생성", "진행"}:
        return "confirm"
    if normalized in {"cancel", "no", "stop", "취소", "아니", "중지"}:
        return "cancel"
    return None


def _is_ticket_action_request(question: str) -> bool:
    normalized = question.strip().lower()
    return "ticket" in normalized and any(
        term in normalized for term in {"incident", "case", "인시던트", "케이스", "장애"}
    )


@dataclass(frozen=True, slots=True)
class _LifecycleCommand:
    kind: str
    incident_id: UUID
    state: IncidentState | None = None
    assignee: str | None = None


def _parse_lifecycle_command(question: str) -> _LifecycleCommand | None:
    normalized = question.strip()
    for pattern in _TRANSITION_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            return _LifecycleCommand(
                kind="transition",
                incident_id=UUID(match.group("incident_id")),
                state=IncidentState(match.group("state").lower()),
            )
    for pattern in _ASSIGN_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is not None:
            assignee = match.group("assignee")
            return _LifecycleCommand(
                kind="assign",
                incident_id=UUID(match.group("incident_id")),
                assignee=None if assignee.lower() in {"none", "unassigned", "없음"} else assignee,
            )
    return None


async def _apply_lifecycle_command(
    *,
    workflow: IncidentLifecycleWorkflow,
    principal: _IncidentPrincipal,
    correlation_id: str,
    command: _LifecycleCommand,
) -> dict[str, Any]:
    try:
        if command.kind == "transition":
            result = await workflow.transition_as_operator(
                incident_id=command.incident_id,
                to_state=cast(IncidentState, command.state),
                principal=principal,
                reason="operator_chat_command",
            )
        else:
            result = await workflow.assign_as_operator(
                incident_id=command.incident_id,
                assignee_oid=command.assignee,
                principal=principal,
            )
    except (KeyError, ValueError) as exc:
        return {
            "submitted": False,
            "reason": "incident_lifecycle_rejected",
            "correlation_id": correlation_id,
            "action_type": f"incident.{command.kind}",
            "message": str(exc),
        }
    return {
        "submitted": True,
        "correlation_id": str(result.incident.incident_id),
        "action_type": f"incident.{command.kind}",
        "incident_id": str(result.incident.incident_id),
        "incident_state": result.incident.state.value,
        "created": False,
        "message": result.response,
    }


def _session_required(correlation_id: str) -> dict[str, Any]:
    return {
        "submitted": False,
        "reason": "incident_session_required",
        "correlation_id": correlation_id,
        "action_type": "incident.create",
        "message": (
            "Incident creation requires a conversation session. "
            "Start or reopen a conversation and retry."
        ),
    }


__all__ = ["open_investigation_incident", "submit_incident_chat"]
