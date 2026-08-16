"""The integrated operator SRE problem-response command path.

One explicit operator problem-response request (`operator-initiated-sre-and-arb.md`
"Operator-initiated SRE flow") must do four things at once: open or reuse exactly
one Incident, publish exactly one idempotent typed ActionProposal, keep one
correlation across every stage, and return the authoritative Incident, Trace,
Process, and Approval links. This module is the bounded coordinator that binds
those steps together; the individual primitives stay where they already live.

Design invariants
-----------------

- **Deterministic identity**: the operator session, target resource, and
  investigation kind derive the Incident correlation keys, the correlation ID,
  and the proposal idempotency key. A retry reuses all three, so it reopens no
  second Incident and publishes no second proposal.
- **Separate writes**: Incident creation and proposal dispatch are separate.
  A dispatch failure keeps the Incident and reports the failure so the operator
  can retry with the same idempotency key; it never fabricates a decision.
- **No executor identity**: the coordinator holds the requesting operator
  principal only. It never dispatches an action itself and never attaches an
  executor credential to the proposal.
- **Read-only classification stays out**: a read-only discovery question never
  reaches this path, so the coordinator never opens an Incident for one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fdai.shared.contracts.models import Incident, IncidentSeverity
from fdai.shared.providers.operator_request import (
    OperatorProposalDispatch,
    OperatorProposalDispatcher,
)

from .lifecycle import IncidentOperatorPrincipal
from .workflow import IncidentLifecycleWorkflow
from .workflow_support import canonical_incident_correlation_keys

_HIL_DECISION = "hil"


class OperatorSreRequestError(ValueError):
    """Raised when an operator SRE request cannot be scoped before any write."""


def _require(value: str, name: str) -> str:
    text = value.strip()
    if not text:
        raise OperatorSreRequestError(f"operator SRE request {name} MUST be non-empty")
    return text


@dataclass(frozen=True, slots=True)
class OperatorSreRequest:
    """One confirmed operator problem-response request with a bounded target."""

    principal: IncidentOperatorPrincipal
    session_id: str
    action_type: str
    resource_id: str
    investigation_kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    resource_type: str | None = None
    severity: IncidentSeverity = IncidentSeverity.SEV3

    def __post_init__(self) -> None:
        _require(self.session_id, "session_id")
        _require(self.action_type, "action_type")
        _require(self.resource_id, "resource_id")
        _require(self.investigation_kind, "investigation_kind")
        if not str(getattr(self.principal, "id", "")).strip():
            raise OperatorSreRequestError("operator SRE request principal id MUST be non-empty")


@dataclass(frozen=True, slots=True)
class ProgressLinkTemplates:
    """Authoritative Operator API projections the progress contract points at.

    Templates are injectable so a fork can mount the same projections behind its
    own prefix. The defaults are the routes this repository actually serves.
    """

    incident: str = "/incidents?status=all&correlation_id={correlation_id}"
    trace: str = "/audit/{correlation_id}/trace"
    process: str = "/views/process/{process_id}"
    approval: str = "/hil-queue?search={approval_id}"


@dataclass(frozen=True, slots=True)
class ProgressLinks:
    """The links one command response returns for durable progress rebuild."""

    incident: str
    trace: str
    process: str | None = None
    approval: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorSreRequestResult:
    """Truthful result of one operator problem-response command."""

    incident: Incident
    incident_created: bool
    correlation_id: str
    idempotency_key: str
    proposal: Mapping[str, Any]
    links: ProgressLinks
    dispatch: OperatorProposalDispatch | None = None
    dispatch_error: str | None = None

    @property
    def dispatched(self) -> bool:
        return self.dispatch is not None


def sre_correlation_keys(
    *,
    session_id: str,
    resource_id: str,
    investigation_kind: str,
) -> tuple[str, ...]:
    """Derive the bounded Incident correlation keys for one SRE request."""
    return canonical_incident_correlation_keys(
        (
            f"session:{_require(session_id, 'session_id')}",
            f"resource:{_require(resource_id, 'resource_id')}",
            f"investigation:{_require(investigation_kind, 'investigation_kind')}",
        )
    )


def sre_correlation_id(correlation_keys: tuple[str, ...]) -> str:
    """Derive the one correlation ID every stage of this request shares."""
    canonical = "|".join(canonical_incident_correlation_keys(correlation_keys))
    return str(uuid5(NAMESPACE_URL, "fdai.operator-sre.correlation://" + canonical))


def sre_idempotency_key(*, correlation_id: str, action_type: str) -> str:
    """Derive the stable proposal identity so a retry publishes no duplicate."""
    correlation = _require(correlation_id, "correlation_id")
    action = _require(action_type, "action_type")
    return f"operator-sre:{correlation}::{action}"


class OperatorSreRequestCoordinator:
    """Turn one confirmed operator request into a governed, linked response."""

    __slots__ = ("_dispatcher", "_templates", "_workflow")

    def __init__(
        self,
        *,
        workflow: IncidentLifecycleWorkflow,
        dispatcher: OperatorProposalDispatcher,
        link_templates: ProgressLinkTemplates | None = None,
    ) -> None:
        self._workflow = workflow
        self._dispatcher = dispatcher
        self._templates = link_templates or ProgressLinkTemplates()

    async def submit(
        self,
        request: OperatorSreRequest,
        *,
        now: datetime | None = None,
    ) -> OperatorSreRequestResult:
        """Open or reuse the Incident, publish one proposal, and return links."""
        keys = sre_correlation_keys(
            session_id=request.session_id,
            resource_id=request.resource_id,
            investigation_kind=request.investigation_kind,
        )
        correlation_id = sre_correlation_id(keys)
        idempotency_key = sre_idempotency_key(
            correlation_id=correlation_id,
            action_type=request.action_type,
        )

        opened = await self._workflow.open_confirmed_operator(
            principal=request.principal,
            correlation_keys=keys,
            severity=request.severity,
            now=now,
        )
        incident = opened.incident
        proposal = self._build_proposal(
            request,
            incident_id=incident.incident_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

        dispatch: OperatorProposalDispatch | None = None
        dispatch_error: str | None = None
        try:
            dispatch = await self._dispatcher.dispatch(proposal)
        except Exception as exc:  # noqa: BLE001 - the Incident write already committed
            dispatch_error = type(exc).__name__

        return OperatorSreRequestResult(
            incident=incident,
            incident_created=opened.created,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            proposal=proposal,
            links=self._build_links(correlation_id=correlation_id, dispatch=dispatch),
            dispatch=dispatch,
            dispatch_error=dispatch_error,
        )

    def _build_proposal(
        self,
        request: OperatorSreRequest,
        *,
        incident_id: UUID,
        correlation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        proposal: dict[str, Any] = {
            "event_type": "operator_request",
            "operator_initiated": True,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "initiator_principal": str(request.principal.id),
            "action_type": request.action_type.strip(),
            "resource_id": request.resource_id.strip(),
            "incident_id": str(incident_id),
            "params": dict(request.params),
        }
        if request.resource_type is not None and request.resource_type.strip():
            proposal["resource_type"] = request.resource_type.strip()
        return proposal

    def _build_links(
        self,
        *,
        correlation_id: str,
        dispatch: OperatorProposalDispatch | None,
    ) -> ProgressLinks:
        approval_ref = dispatch.approval_ref if dispatch is not None else None
        process_ref = dispatch.process_ref if dispatch is not None else None
        # An approval link is meaningful only when the gate actually parked.
        if dispatch is not None and dispatch.decision.strip().lower() != _HIL_DECISION:
            approval_ref = None
        return ProgressLinks(
            incident=self._templates.incident.format(correlation_id=correlation_id),
            trace=self._templates.trace.format(correlation_id=correlation_id),
            process=(
                self._templates.process.format(process_id=process_ref)
                if process_ref is not None and process_ref.strip()
                else None
            ),
            approval=(
                self._templates.approval.format(approval_id=approval_ref)
                if approval_ref is not None and approval_ref.strip()
                else None
            ),
        )


__all__ = [
    "OperatorSreRequest",
    "OperatorSreRequestCoordinator",
    "OperatorSreRequestError",
    "OperatorSreRequestResult",
    "ProgressLinkTemplates",
    "ProgressLinks",
    "sre_correlation_id",
    "sre_correlation_keys",
    "sre_idempotency_key",
]
