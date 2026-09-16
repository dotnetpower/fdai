"""Race-safe HIL request parking and initial delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.core.hil_resume.approval_records import on_call_detail, park_key
from fdai.core.hil_resume.delivery import dispatch_parked_approval
from fdai.core.hil_resume.escalation_supervisor import (
    EscalationRung,
    HumanNonResponseSupervisor,
)
from fdai.core.hil_resume.integrity import (
    action_payload_hash,
    approval_request_fingerprint,
)
from fdai.core.hil_resume.load_control import ApprovalLoadController
from fdai.core.hil_resume.report_line import ReportLineHilCoordinator
from fdai.core.hil_resume.results import RequestApprovalResult, RequestOutcome
from fdai.core.human_reporting import ReportLineRouteUnavailableError
from fdai.core.oncall import OnCallResolution, OnCallResolver
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.hil_channel import HilChannel
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.core.hil_resume.coordinator")
_STATUS_PENDING = "pending"


class HilRequestMixin:
    """Park immutable HIL requests before any notification is sent."""

    _approval_load_controller: ApprovalLoadController | None
    _default_escalation_rungs: tuple[EscalationRung, ...]
    _hil_channel: HilChannel | None
    _on_call_resolver: OnCallResolver | None
    _on_call_rotation: str | None
    _pending_index_writer: Callable[[StateStore, str], Awaitable[None]] | None
    _report_line_hil: ReportLineHilCoordinator | None
    _request_clock: Callable[[], datetime]
    _state_store: StateStore
    escalation_supervisor: HumanNonResponseSupervisor | None

    def _audit_entry(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> None:
        raise NotImplementedError

    async def _resolve_on_call(self) -> OnCallResolution | None:
        """Resolve the current on-call responder, or ``None`` when unconfigured."""

        if self._on_call_resolver is None or self._on_call_rotation is None:
            return None
        return await self._on_call_resolver.resolve(
            rotation=self._on_call_rotation,
            at=self._request_clock(),
        )

    async def request_approval(
        self,
        *,
        action: Action,
        rule: Rule,
        submitter_oid: str,
        correlation_id: str,
        reasons: Sequence[str] = (),
        blast_radius_summary: str = "",
        ttl_seconds: int = 1800,
        approval_id: str | None = None,
        assignee_oid: str | None = None,
        escalation_rungs: Sequence[EscalationRung] = (),
        escalation_context: Mapping[str, object] | None = None,
    ) -> RequestApprovalResult:
        """Park ``action`` before dispatching its approval request."""

        if not submitter_oid.strip():
            raise ValueError(
                "submitter_oid MUST be non-empty - it is the no-self-approval authority"
            )
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds MUST be > 0")
        if approval_id is not None and not approval_id.strip():
            raise ValueError("approval_id MUST be non-empty when supplied")
        aid = approval_id or uuid4().hex
        if len(aid) > 200:
            raise ValueError("approval_id exceeds cap (200)")
        normalized_submitter = submitter_oid.strip()
        parked_at = self._request_clock()
        action_payload = action.model_dump(mode="json")
        action_hash = action_payload_hash(action_payload)
        try:
            route_plan, contact_consent = (
                await self._report_line_hil.prepare_request(
                    action=action,
                    submitter_oid=normalized_submitter,
                    at=parked_at,
                )
                if self._report_line_hil is not None
                else (None, None)
            )
        except ReportLineRouteUnavailableError:
            await self._audit(
                action_kind="hil.report_line.route_unavailable",
                idempotency_key=f"{action.idempotency_key}:report_line_route_unavailable",
                approval_id=aid,
                correlation_id=correlation_id,
                detail={"action_type": action.action_type},
            )
            return RequestApprovalResult(
                outcome=RequestOutcome.REPORT_LINE_ROUTE_UNAVAILABLE,
                approval_id=aid,
            )
        if route_plan is not None and assignee_oid is not None:
            raise ValueError("explicit assignee cannot override a report-line route")
        on_call = None if route_plan is not None else await self._resolve_on_call()
        resolved_assignee = (
            route_plan.rungs[0].subject_ref
            if route_plan is not None
            else (assignee_oid or "").strip()
            or (on_call.primary_oid if on_call is not None else None)
        )
        resolved_escalation_rungs = (
            route_plan.rungs
            if route_plan is not None
            else tuple(escalation_rungs) or self._default_escalation_rungs
        )
        request_fingerprint = approval_request_fingerprint(
            action=action,
            rule=rule,
            submitter_oid=normalized_submitter,
            correlation_id=correlation_id,
            reasons=reasons,
            blast_radius_summary=blast_radius_summary,
            ttl_seconds=ttl_seconds,
            assignee_oid=resolved_assignee,
            route_digest=route_plan.digest if route_plan is not None else None,
        )
        parked = {
            "status": ("awaiting_contact_consent" if route_plan is not None else _STATUS_PENDING),
            "revision": 0,
            "approval_id": aid,
            "action": action_payload,
            "action_hash": action_hash,
            "rule_id": rule.id,
            "rule": rule.model_dump(mode="json"),
            "action_type": action.action_type,
            "severity": rule.severity.value,
            "category": rule.category.value,
            "submitter_oid": normalized_submitter,
            "assignee_oid": resolved_assignee,
            "correlation_id": correlation_id,
            "idempotency_key": action.idempotency_key,
            "request_fingerprint": request_fingerprint,
            "parked_at": parked_at.isoformat(),
            "approval_context": {
                "reasons": list(reasons),
                "blast_radius_summary": blast_radius_summary,
                "ttl_seconds": ttl_seconds,
                "expires_at": (parked_at + timedelta(seconds=ttl_seconds)).isoformat(),
            },
            "on_call": on_call_detail(on_call),
            "report_line_route": (route_plan.to_dict() if route_plan is not None else None),
            "contact_consent_id": (
                contact_consent.consent_id if contact_consent is not None else None
            ),
            "contact_consent_expires_at": (
                contact_consent.expires_at.isoformat() if contact_consent is not None else None
            ),
        }
        if resolved_escalation_rungs and route_plan is None:
            if self.escalation_supervisor is None:
                raise ValueError("escalation_rungs require an escalation supervisor")
            parked = await self.escalation_supervisor.attach_with_source(
                parked,
                rungs=resolved_escalation_rungs,
                now=parked_at,
                context=escalation_context,
            )
        effective_assignee = str(parked.get("assignee_oid") or "").strip() or None
        requested_audit = self._audit_entry(
            action_kind="hil.requested",
            idempotency_key=f"{action.idempotency_key}:hil_request",
            approval_id=aid,
            correlation_id=correlation_id,
            detail={
                "event_id": str(action.event_id),
                "action_id": str(action.action_id),
                "action_type": action.action_type,
                "workflow_action": (
                    action.workflow_action.model_dump(mode="json")
                    if action.workflow_action is not None
                    else None
                ),
                "rule_id": rule.id,
                "severity": rule.severity.value,
                "category": rule.category.value,
                "submitter_oid": normalized_submitter,
                "assignee_oid": effective_assignee,
                "on_call": on_call_detail(on_call),
                "report_line_route_digest": (route_plan.digest if route_plan is not None else None),
                "contact_consent_id": (
                    contact_consent.consent_id if contact_consent is not None else None
                ),
            },
        )
        created = await self._state_store.write_state_with_audit_if_absent(
            park_key(aid),
            parked,
            requested_audit,
        )
        if not created:
            existing = await self._state_store.read_state(park_key(aid))
            if existing is not None and existing.get("request_fingerprint") == request_fingerprint:
                await self._audit(
                    action_kind="hil.request.duplicate",
                    idempotency_key=f"{action.idempotency_key}:hil_request_duplicate",
                    approval_id=aid,
                    correlation_id=correlation_id,
                    detail={},
                )
                return RequestApprovalResult(
                    outcome=(
                        RequestOutcome.CONTACT_CONSENT_REQUIRED
                        if existing.get("status") == "awaiting_contact_consent"
                        else RequestOutcome.ALREADY_PARKED
                    ),
                    approval_id=aid,
                )
            await self._audit(
                action_kind="hil.request.approval_id_conflict",
                idempotency_key=f"{aid}:hil_request_conflict",
                approval_id=aid,
                correlation_id=correlation_id,
                detail={"attempted_action_id": str(action.action_id)},
            )
            return RequestApprovalResult(
                outcome=RequestOutcome.APPROVAL_ID_CONFLICT,
                approval_id=aid,
            )
        if self._pending_index_writer is not None:
            await self._pending_index_writer(self._state_store, aid)
        if route_plan is not None:
            return RequestApprovalResult(
                outcome=RequestOutcome.CONTACT_CONSENT_REQUIRED,
                approval_id=aid,
            )
        return await dispatch_parked_approval(
            parked=parked,
            action=action,
            rule=rule,
            approval_id=aid,
            correlation_id=correlation_id,
            channel=self._hil_channel,
            load_controller=self._approval_load_controller,
            escalation_supervisor=self.escalation_supervisor,
            escalation_rungs=resolved_escalation_rungs,
            audit=self._audit,
            logger=_LOGGER,
        )

    async def decide_report_line_contact(
        self,
        *,
        approval_id: str,
        requester_oid: str,
        consent: bool,
        expected_consent_revision: int,
        at: datetime | None = None,
    ) -> RequestApprovalResult:
        """Record requester contact consent and send only an unchanged route."""

        if self._report_line_hil is None:
            raise RuntimeError("report-line approval routing is not configured")
        return await self._report_line_hil.decide_contact(
            approval_id=approval_id,
            requester_oid=requester_oid,
            consent=consent,
            expected_consent_revision=expected_consent_revision,
            at=at,
        )


__all__ = ["HilRequestMixin"]
