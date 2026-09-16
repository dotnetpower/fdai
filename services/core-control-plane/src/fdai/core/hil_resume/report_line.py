"""Report-line planning, requester contact consent, and route freshness checks."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fdai.core.hil_resume.approval_records import park_key
from fdai.core.hil_resume.delivery import HilAudit, dispatch_parked_approval
from fdai.core.hil_resume.escalation_supervisor import HumanNonResponseSupervisor
from fdai.core.hil_resume.integrity import (
    action_payload_hash,
    parked_action_integrity_matches,
)
from fdai.core.hil_resume.load_control import ApprovalLoadController
from fdai.core.hil_resume.results import (
    RequestApprovalResult,
    RequestOutcome,
    ResolveOutcome,
    ResolveResult,
)
from fdai.core.hil_resume.rule_source import resolve_parked_rule
from fdai.core.human_reporting.consent import (
    ApprovalContactConsent,
    ApprovalContactConsentExpiredError,
    ApprovalContactConsentService,
    ApprovalContactConsentState,
)
from fdai.core.human_reporting.routing import (
    ReportLineApprovalRouter,
    ReportLineRoutePlan,
    ReportLineRouteUnavailableError,
)
from fdai.core.rbac.roles import Role
from fdai.core.workflow.approval import approval_role_for_action
from fdai.shared.contracts.models import Action, OntologyActionType, Rule
from fdai.shared.providers.hil_channel import HilChannel, HilDecision
from fdai.shared.providers.state_store import StateStore


class MarkResolved(Protocol):
    """Atomically resolve a parked HIL item with its audit record."""

    async def __call__(
        self,
        parked: Mapping[str, Any],
        *,
        decision: HilDecision,
        approver_oid: str,
        action_kind: str,
        detail: Mapping[str, Any],
    ) -> bool: ...


class RaceResult(Protocol):
    """Read the winning terminal result after a compare-and-set race."""

    async def __call__(
        self,
        approval_id: str,
        *,
        attempted: HilDecision,
    ) -> ResolveResult: ...


@dataclass(frozen=True, slots=True)
class ReportLineHilCoordinator:
    """Own report-line-specific HIL preparation without executing an action."""

    store: StateStore
    router: ReportLineApprovalRouter
    consent: ApprovalContactConsentService
    escalation: HumanNonResponseSupervisor
    channel: HilChannel | None
    load_controller: ApprovalLoadController | None
    action_types: Mapping[str, OntologyActionType]
    rules: Mapping[str, Rule]
    audit: HilAudit
    mark_resolved: MarkResolved
    race_result: RaceResult
    logger: logging.Logger

    async def plan(
        self,
        *,
        action: Action,
        submitter_oid: str,
        at: datetime,
    ) -> ReportLineRoutePlan | None:
        """Resolve a selected ActionType through current reporting evidence."""

        if not self.router.policy.selects(action.action_type):
            return None
        action_type = self.action_types.get(action.action_type)
        role = approval_role_for_action(action_type) if action_type is not None else None
        minimum_role = Role.OWNER.value if role is Role.OWNER else Role.APPROVER.value
        return await self.router.plan(
            requester_ref=submitter_oid,
            action_type=action.action_type,
            scope_ref=action.target_resource_ref,
            minimum_role=minimum_role,
            at=at,
        )

    async def route_is_current(
        self,
        *,
        parked: Mapping[str, Any],
        action: Action,
        approver_oid: str,
        at: datetime,
    ) -> bool:
        """Recheck the exact graph route and current assignee before approval."""

        route_value = parked.get("report_line_route")
        if not isinstance(route_value, Mapping):
            return True
        try:
            current = await self.plan(
                action=action,
                submitter_oid=str(parked.get("submitter_oid") or ""),
                at=at,
            )
        except ReportLineRouteUnavailableError:
            return False
        return (
            current is not None
            and current.digest == route_value.get("route_digest")
            and current.path_revision == route_value.get("path_revision")
            and approver_oid.strip().casefold()
            == str(parked.get("assignee_oid") or "").strip().casefold()
        )

    async def prepare_request(
        self,
        *,
        action: Action,
        submitter_oid: str,
        at: datetime,
    ) -> tuple[ReportLineRoutePlan | None, ApprovalContactConsent | None]:
        """Plan a selected route and create its exact contact-consent record."""

        route = await self.plan(action=action, submitter_oid=submitter_oid, at=at)
        if route is None:
            return None, None
        consent = await self.consent.request(
            requester_ref=submitter_oid,
            action_digest=action_payload_hash(action.model_dump(mode="json")),
            route_digest=route.digest,
            path_revision=route.path_revision,
            now=at,
        )
        return route, consent

    @staticmethod
    def contact_consent_expired(
        parked: Mapping[str, Any],
        *,
        at: datetime,
    ) -> bool:
        """Fail closed when a parked contact deadline is absent, malformed, or due."""

        raw = parked.get("contact_consent_expires_at")
        if not isinstance(raw, str) or not raw:
            return True
        try:
            expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return True
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            return True
        return at.astimezone(UTC) >= expires_at.astimezone(UTC)

    async def guard_approval(
        self,
        *,
        parked: Mapping[str, Any],
        action: Action,
        approval_id: str,
        approver_oid: str,
    ) -> ResolveResult | None:
        """Return a terminal no-op when a pinned report-line route is no longer current."""

        if not isinstance(parked.get("report_line_route"), Mapping):
            return None
        if await self.route_is_current(
            parked=parked,
            action=action,
            approver_oid=approver_oid,
            at=datetime.now(tz=UTC),
        ):
            return None
        claimed = await self.mark_resolved(
            parked,
            decision=HilDecision.TIMEOUT,
            approver_oid=approver_oid,
            action_kind="hil.report_line.route_stale",
            detail={"attempted_decision": HilDecision.APPROVE.value},
        )
        if not claimed:
            return await self.race_result(
                approval_id,
                attempted=HilDecision.APPROVE,
            )
        return ResolveResult(
            outcome=ResolveOutcome.TIMED_OUT,
            approval_id=approval_id,
            reason="report_line_route_stale",
            assignee_oid=str(parked.get("assignee_oid") or "") or None,
        )

    async def decide_contact(
        self,
        *,
        approval_id: str,
        requester_oid: str,
        consent: bool,
        expected_consent_revision: int,
        at: datetime | None = None,
    ) -> RequestApprovalResult:
        """Record contact consent and send only a still-current eligible route."""

        parked = await self.store.read_state(park_key(approval_id))
        if parked is None:
            return RequestApprovalResult(
                outcome=RequestOutcome.REPORT_LINE_ROUTE_UNAVAILABLE,
                approval_id=approval_id,
            )
        if parked.get("status") == "pending":
            return RequestApprovalResult(
                outcome=RequestOutcome.ALREADY_PARKED,
                approval_id=approval_id,
            )
        if parked.get("status") != "awaiting_contact_consent":
            return RequestApprovalResult(
                outcome=RequestOutcome.CONTACT_DECLINED,
                approval_id=approval_id,
            )
        consent_id = parked.get("contact_consent_id")
        route_value = parked.get("report_line_route")
        if not isinstance(consent_id, str) or not isinstance(route_value, Mapping):
            raise ValueError("report-line approval park is missing consent or route evidence")
        correlation_id = str(parked.get("correlation_id") or approval_id)
        idempotency_key = str(parked.get("idempotency_key") or approval_id)
        decided_at = at or datetime.now(tz=UTC)
        try:
            decision = await self.consent.decide(
                consent_id=consent_id,
                requester_ref=requester_oid,
                consent=consent,
                expected_revision=expected_consent_revision,
                now=decided_at,
            )
        except ApprovalContactConsentExpiredError:
            claimed = await self.mark_resolved(
                parked,
                decision=HilDecision.TIMEOUT,
                approver_oid=requester_oid,
                action_kind="hil.report_line.contact_consent_expired",
                detail={"contact_consent_id": consent_id},
            )
            return RequestApprovalResult(
                outcome=(
                    RequestOutcome.CONTACT_CONSENT_EXPIRED
                    if claimed
                    else RequestOutcome.ALREADY_PARKED
                ),
                approval_id=approval_id,
            )
        if decision.state is ApprovalContactConsentState.DECLINED:
            claimed = await self.mark_resolved(
                parked,
                decision=HilDecision.TIMEOUT,
                approver_oid=requester_oid,
                action_kind="hil.report_line.contact_declined",
                detail={"contact_consent_id": consent_id},
            )
            return RequestApprovalResult(
                outcome=(
                    RequestOutcome.CONTACT_DECLINED if claimed else RequestOutcome.ALREADY_PARKED
                ),
                approval_id=approval_id,
            )
        action_value = parked.get("action")
        if not isinstance(action_value, Mapping) or not parked_action_integrity_matches(parked):
            raise ValueError("report-line approval action integrity is invalid")
        action = Action.model_validate(action_value)
        rule = resolve_parked_rule(parked, action=action, rules_by_id=self.rules)
        if rule is None:
            raise ValueError("report-line approval rule is unavailable")
        try:
            route = await self.plan(
                action=action,
                submitter_oid=str(parked.get("submitter_oid") or ""),
                at=decided_at,
            )
        except ReportLineRouteUnavailableError:
            route = None
        if not _same_route(route, route_value, decision, parked):
            await self.mark_resolved(
                parked,
                decision=HilDecision.TIMEOUT,
                approver_oid=requester_oid,
                action_kind="hil.report_line.route_changed",
                detail={"contact_consent_id": consent_id},
            )
            return RequestApprovalResult(
                outcome=RequestOutcome.REPORT_LINE_ROUTE_UNAVAILABLE,
                approval_id=approval_id,
            )
        if route is None:  # pragma: no cover - narrowed by _same_route
            raise RuntimeError("report-line route disappeared after validation")
        updated = await self.escalation.attach_with_source(
            parked,
            rungs=route.rungs,
            now=decided_at,
            context=None,
        )
        revision = _revision(parked)
        updated["status"] = "pending"
        updated["revision"] = revision + 1
        updated["contact_consent"] = decision.to_dict()
        applied = await self.store.compare_and_set_state_with_audit(
            park_key(approval_id),
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": requester_oid.casefold(),
                "action_kind": "hil.report_line.contact_consented",
                "approval_id": approval_id,
                "correlation_id": correlation_id,
                "idempotency_key": f"{idempotency_key}:report_line_contact_consented",
                "route_digest": route.digest,
                "graph_revision": route.graph_revision,
                "path_revision": route.path_revision,
                "recorded_at": decided_at.isoformat(),
                "mode": "shadow",
                "approval_authority": False,
                "execution_authority": False,
            },
        )
        if not applied:
            current = await self.store.read_state(park_key(approval_id))
            if current is not None and current.get("status") == "pending":
                return RequestApprovalResult(
                    outcome=RequestOutcome.ALREADY_PARKED,
                    approval_id=approval_id,
                )
            if (
                current is not None
                and current.get("status") == "resolved"
                and current.get("decision") == HilDecision.TIMEOUT.value
                and current.get("approver_oid") == "system:contact-consent-expiry"
            ):
                return RequestApprovalResult(
                    outcome=RequestOutcome.CONTACT_CONSENT_EXPIRED,
                    approval_id=approval_id,
                )
            raise ValueError("report-line approval park changed during contact consent")
        return await dispatch_parked_approval(
            parked=updated,
            action=action,
            rule=rule,
            approval_id=approval_id,
            correlation_id=correlation_id,
            channel=self.channel,
            load_controller=self.load_controller,
            escalation_supervisor=self.escalation,
            escalation_rungs=route.rungs,
            audit=self.audit,
            logger=self.logger,
        )


def _revision(parked: Mapping[str, Any]) -> int:
    revision = parked.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("report-line approval revision MUST be non-negative")
    return int(revision)


def _same_route(
    route: ReportLineRoutePlan | None,
    retained: Mapping[str, Any],
    consent: ApprovalContactConsent,
    parked: Mapping[str, Any],
) -> bool:
    return (
        route is not None
        and route.quorum == 1
        and route.digest == retained.get("route_digest")
        and route.path_revision == retained.get("path_revision")
        and route.path_revision == consent.path_revision
        and route.digest == consent.route_digest
        and consent.action_digest == str(parked.get("action_hash") or "")
    )


__all__ = ["ReportLineHilCoordinator"]
