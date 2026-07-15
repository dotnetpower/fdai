"""Built-in incident creation, lifecycle, roster, and notification workflow."""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable
from datetime import UTC, datetime
from uuid import UUID

from fdai.shared.contracts.models import Incident, IncidentSeverity, IncidentState

from .intent import IncidentChatTurn, IncidentCreationProposal, prepare_incident_chat
from .lifecycle import (
    IncidentConfirmationError,
    IncidentLifecycleNotice,
    IncidentLifecycleNotifier,
    IncidentNoticeKind,
    IncidentNotificationDeferred,
    IncidentOperatorPrincipal,
    IncidentRosterResult,
    IncidentWorkflowError,
    IncidentWorkflowForbiddenError,
    IncidentWorkflowResult,
    NullIncidentLifecycleNotifier,
)
from .registry import IncidentRegistry
from .workflow_support import manual_incident_event_id, require_incident_operator

_CONFIRMATIONS = frozenset({"confirm", "confirmed", "yes", "proceed", "확인", "생성", "진행"})
_CANCELLATIONS = frozenset({"cancel", "no", "stop", "취소", "아니", "중지"})
_LOG = logging.getLogger(__name__)


class IncidentLifecycleWorkflow:
    """Coordinate human and autonomous incident lifecycle entry points."""

    def __init__(
        self,
        *,
        registry: IncidentRegistry,
        notifier: IncidentLifecycleNotifier | None = None,
        allowed_agent_principals: Collection[str] = (),
    ) -> None:
        self._registry = registry
        self._notifier = notifier or NullIncidentLifecycleNotifier()
        self._allowed_agents = frozenset(allowed_agent_principals)

    def prepare_chat(self, *, text: str, principal: IncidentOperatorPrincipal) -> IncidentChatTurn:
        """Interpret an operator request and return a confirmation turn."""
        require_incident_operator(principal)
        return prepare_incident_chat(text, requested_by=principal.id)

    async def confirm_chat(
        self,
        *,
        proposal: IncidentCreationProposal,
        principal: IncidentOperatorPrincipal,
        confirmation: str,
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Create an incident only after the same operator confirms in time."""
        require_incident_operator(principal)
        if proposal.requested_by != principal.id:
            raise IncidentConfirmationError(
                "incident proposal can only be confirmed by its requester"
            )
        moment = now or datetime.now(tz=UTC)
        if moment > proposal.expires_at:
            raise IncidentConfirmationError("incident proposal expired; prepare a new request")
        normalized = confirmation.strip().lower()
        if normalized in _CANCELLATIONS:
            raise IncidentConfirmationError("incident creation cancelled by operator")
        if normalized not in _CONFIRMATIONS:
            raise IncidentConfirmationError("explicit incident creation confirmation is required")

        return await self.open_confirmed_operator(
            principal=principal,
            correlation_keys=proposal.correlation_keys,
            severity=proposal.severity,
            now=moment,
        )

    async def open_confirmed_operator(
        self,
        *,
        principal: IncidentOperatorPrincipal,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID] = (),
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Open a structured operator request after its caller confirmed it."""
        require_incident_operator(principal)
        keys = tuple(correlation_keys)
        members = tuple(member_event_ids) or (manual_incident_event_id(keys),)
        moment = now or datetime.now(tz=UTC)
        opened = await self._registry.open_with_status(
            correlation_keys=keys,
            severity=severity,
            member_event_ids=members,
            actor_oid=principal.id,
            opened_at=moment,
        )
        incident = opened.incident
        created = opened.created
        notification = (
            await self._notify_opened(incident=incident, actor_oid=principal.id, at=moment)
            if created
            else None
        )
        return IncidentWorkflowResult(
            incident=incident,
            response=(
                f"Incident {incident.incident_id} created in {incident.state.value} state."
                if created
                else (
                    f"Incident {incident.incident_id} already exists in "
                    f"{incident.state.value} state."
                )
            ),
            notification_result=notification,
            created=created,
        )

    async def open_from_agent(
        self,
        *,
        producer_principal: str,
        correlation_keys: Iterable[str],
        severity: IncidentSeverity,
        member_event_ids: Iterable[UUID],
        reason: str,
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Open an evidence-backed incident for an authorized pantheon agent."""
        if producer_principal not in self._allowed_agents:
            raise IncidentWorkflowForbiddenError(
                f"agent principal {producer_principal!r} is not allowed to create incidents"
            )
        members = tuple(member_event_ids)
        if not members:
            raise IncidentWorkflowError("agent-created incident requires at least one member event")
        if not reason.strip():
            raise IncidentWorkflowError("agent-created incident requires a reason")
        moment = now or datetime.now(tz=UTC)
        keys = tuple(correlation_keys)
        opened = await self._registry.open_with_status(
            correlation_keys=keys,
            severity=severity,
            member_event_ids=members,
            actor_oid=producer_principal,
            opened_at=moment,
        )
        incident = opened.incident
        created = opened.created
        notification = (
            await self._notify_opened(
                incident=incident,
                actor_oid=producer_principal,
                at=moment,
                reason=reason,
            )
            if created
            else None
        )
        return IncidentWorkflowResult(
            incident=incident,
            response=(
                f"Agent {producer_principal} created incident {incident.incident_id}."
                if created
                else f"Incident {incident.incident_id} already exists."
            ),
            notification_result=notification,
            created=created,
        )

    async def transition_as_operator(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        principal: IncidentOperatorPrincipal,
        reason: str | None = None,
        severity: IncidentSeverity | None = None,
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Apply a legal operator transition and notify subscribers."""
        require_incident_operator(principal)
        return await self._transition(
            incident_id=incident_id,
            to_state=to_state,
            actor_oid=principal.id,
            reason=reason,
            severity=severity,
            now=now,
        )

    async def transition_from_agent(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        producer_principal: str,
        reason: str,
        severity: IncidentSeverity | None = None,
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Apply a legal transition for an authorized agent and notify."""
        if producer_principal not in self._allowed_agents:
            raise IncidentWorkflowForbiddenError(
                f"agent principal {producer_principal!r} is not allowed to transition incidents"
            )
        if not reason.strip():
            raise IncidentWorkflowError("agent incident transition requires a reason")
        return await self._transition(
            incident_id=incident_id,
            to_state=to_state,
            actor_oid=producer_principal,
            reason=reason,
            severity=severity,
            now=now,
        )

    async def assign_as_operator(
        self,
        *,
        incident_id: UUID,
        assignee_oid: str | None,
        principal: IncidentOperatorPrincipal,
        now: datetime | None = None,
    ) -> IncidentWorkflowResult:
        """Assign an incident and notify the operations audience."""
        require_incident_operator(principal)
        existing = self._registry.get(incident_id)
        if existing is None:
            raise KeyError(f"unknown incident_id: {incident_id}")
        moment = now or datetime.now(tz=UTC)
        assigned = await self._registry.assign_with_status(
            incident_id=incident_id,
            assignee_oid=assignee_oid,
            actor_oid=principal.id,
            at=moment,
        )
        incident = assigned.incident
        changed = assigned.changed
        notification = (
            await self._notify_after_write(
                IncidentLifecycleNotice(
                    kind=IncidentNoticeKind.ASSIGNED,
                    actor_oid=principal.id,
                    occurred_at=moment,
                    incident=incident,
                    reason="assigned" if incident.assignee_oid else "unassigned",
                )
            )
            if changed
            else None
        )
        return IncidentWorkflowResult(
            incident=incident,
            response=(
                f"Incident {incident_id} assigned."
                if incident.assignee_oid
                else f"Incident {incident_id} unassigned."
            ),
            notification_result=notification,
            changed=changed,
        )

    def list_incidents(self, *, state: IncidentState | None = None) -> IncidentRosterResult:
        """Return a deterministic roster, optionally filtered by state."""
        incidents = tuple(
            sorted(
                (
                    incident
                    for incident in self._registry.snapshot().values()
                    if state is None or incident.state is state
                ),
                key=lambda incident: (incident.opened_at, str(incident.incident_id)),
                reverse=True,
            )
        )
        return IncidentRosterResult(incidents=incidents)

    async def notify_roster(
        self,
        *,
        actor_oid: str,
        state: IncidentState | None = None,
        now: datetime | None = None,
    ) -> IncidentRosterResult:
        """Send the current roster through the same configured channels."""
        roster = self.list_incidents(state=state).incidents
        notification = await self._notifier.notify(
            IncidentLifecycleNotice(
                kind=IncidentNoticeKind.ROSTER,
                actor_oid=actor_oid,
                occurred_at=now or datetime.now(tz=UTC),
                roster=roster,
            )
        )
        return IncidentRosterResult(incidents=roster, notification_result=notification)

    async def _transition(
        self,
        *,
        incident_id: UUID,
        to_state: IncidentState,
        actor_oid: str,
        reason: str | None,
        severity: IncidentSeverity | None,
        now: datetime | None,
    ) -> IncidentWorkflowResult:
        existing = self._registry.get(incident_id)
        if existing is None:
            raise KeyError(f"unknown incident_id: {incident_id}")
        previous_state = existing.state
        if previous_state is to_state:
            return IncidentWorkflowResult(
                incident=existing,
                response=f"Incident {incident_id} is already in {to_state.value} state.",
                notification_result=None,
            )
        moment = now or datetime.now(tz=UTC)
        transitioned = await self._registry.transition_with_status(
            incident_id=incident_id,
            to_state=to_state,
            actor_oid=actor_oid,
            reason=reason,
            severity=severity,
            at=moment,
        )
        incident = transitioned.incident
        notification = (
            await self._notify_after_write(
                IncidentLifecycleNotice(
                    kind=IncidentNoticeKind.STATE_CHANGED,
                    actor_oid=actor_oid,
                    occurred_at=moment,
                    incident=incident,
                    previous_state=previous_state,
                    reason=reason,
                )
            )
            if transitioned.changed
            else None
        )
        return IncidentWorkflowResult(
            incident=incident,
            response=(
                f"Incident {incident.incident_id} changed from "
                f"{previous_state.value} to {incident.state.value}."
            ),
            notification_result=notification,
            changed=transitioned.changed,
        )

    async def _notify_opened(
        self,
        *,
        incident: Incident,
        actor_oid: str,
        at: datetime,
        reason: str | None = None,
    ) -> object | None:
        return await self._notify_after_write(
            IncidentLifecycleNotice(
                kind=IncidentNoticeKind.OPENED,
                actor_oid=actor_oid,
                occurred_at=at,
                incident=incident,
                reason=reason,
            )
        )

    async def _notify_after_write(
        self,
        notice: IncidentLifecycleNotice,
    ) -> object | None:
        """Notify without hiding an already-committed lifecycle write."""
        try:
            return await self._notifier.notify(notice)
        except Exception as exc:  # noqa: BLE001 - durable replay owns retry
            incident_id = notice.incident.incident_id if notice.incident is not None else None
            _LOG.error(
                "incident_notification_deferred",
                extra={
                    "incident_id": str(incident_id) if incident_id is not None else None,
                    "notice_kind": notice.kind.value,
                    "error_type": type(exc).__name__,
                },
            )
            return IncidentNotificationDeferred(error_type=type(exc).__name__)

