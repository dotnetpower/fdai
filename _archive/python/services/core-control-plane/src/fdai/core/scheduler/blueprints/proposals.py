"""Apply durable Operator review proposals to inert automation blueprints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.conversation.session import Principal, Role
from fdai.core.scheduler.blueprints.models import AutomationBlueprintCandidate
from fdai.core.scheduler.blueprints.review import AutomationBlueprintReviewService

_BLUEPRINT_OPERATIONS = frozenset(
    {
        "automation_blueprint.accept",
        "automation_blueprint.reject",
        "automation_blueprint.materialize",
    }
)
_ROLE_MAP = {
    "Reader": Role.READER,
    "Contributor": Role.CONTRIBUTOR,
    "Approver": Role.APPROVER,
    "Owner": Role.OWNER,
    "reader": Role.READER,
    "contributor": Role.CONTRIBUTOR,
    "approver": Role.APPROVER,
    "owner": Role.OWNER,
}
_ROLE_ORDER = (Role.READER, Role.CONTRIBUTOR, Role.APPROVER, Role.OWNER)


@dataclass(frozen=True, slots=True)
class AutomationBlueprintReviewProposal:
    """One durable Operator proposal that carries no executor authority."""

    operation: str
    principal_id: str
    idempotency_key: str
    payload: Mapping[str, object]
    principal_roles: tuple[str, ...] = ()
    proposal_id: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in _BLUEPRINT_OPERATIONS:
            raise ValueError("unsupported automation blueprint proposal operation")
        for label, value in (
            ("principal_id", self.principal_id),
            ("idempotency_key", self.idempotency_key),
        ):
            if not value.strip():
                raise ValueError(f"automation blueprint proposal {label} MUST be non-empty")
        candidate_id = self.payload.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("automation blueprint proposal candidate_id MUST be non-empty")
        if self.operation != "automation_blueprint.materialize":
            reason = self.payload.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("automation blueprint review reason MUST be non-empty")


class AutomationBlueprintPrincipalResolver(Protocol):
    """Resolve a queued proposal's reviewer without granting route authority."""

    async def principal_for(self, proposal: AutomationBlueprintReviewProposal) -> Principal: ...


class ProposalRolePrincipalResolver:
    """Bind server-recorded ordinary roles from the durable proposal."""

    async def principal_for(self, proposal: AutomationBlueprintReviewProposal) -> Principal:
        roles = frozenset(_ROLE_MAP[role] for role in proposal.principal_roles if role in _ROLE_MAP)
        ordinary = [role for role in _ROLE_ORDER if role in roles]
        if not ordinary:
            raise PermissionError("automation blueprint proposal has no ordinary reviewer role")
        return Principal(id=proposal.principal_id, role=ordinary[-1])


class FailClosedAutomationBlueprintPrincipalResolver:
    """Default resolver for unbound production composition."""

    async def principal_for(self, proposal: AutomationBlueprintReviewProposal) -> Principal:
        del proposal
        raise PermissionError("automation blueprint proposal principal resolver is not configured")


class AutomationBlueprintProposalProcessor:
    """Dispatch queued accept, reject, and materialize proposals to Core review logic."""

    def __init__(
        self,
        *,
        review: AutomationBlueprintReviewService,
        principal_resolver: AutomationBlueprintPrincipalResolver,
    ) -> None:
        self._review = review
        self._principal_resolver = principal_resolver

    async def apply(
        self,
        proposal: AutomationBlueprintReviewProposal,
        *,
        at: datetime,
    ) -> AutomationBlueprintCandidate:
        principal = await self._principal_resolver.principal_for(proposal)
        candidate_id = str(proposal.payload["candidate_id"])
        if proposal.operation == "automation_blueprint.materialize":
            return await self._review.materialize(candidate_id, principal=principal, at=at)
        reason = str(proposal.payload["reason"])
        return await self._review.review(
            candidate_id,
            principal=principal,
            approve=proposal.operation == "automation_blueprint.accept",
            reason=reason,
            at=at,
        )


__all__ = [
    "AutomationBlueprintPrincipalResolver",
    "AutomationBlueprintProposalProcessor",
    "AutomationBlueprintReviewProposal",
    "FailClosedAutomationBlueprintPrincipalResolver",
    "ProposalRolePrincipalResolver",
]
