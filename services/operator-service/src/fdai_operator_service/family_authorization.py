"""Verified principal adapters shared by all Operator route families."""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.requests import Request

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.conversation.contracts import PrincipalScope
from fdai_operator_service.families.conversation.manifest import CONVERSATION_ROUTE_MANIFEST
from fdai_operator_service.families.iam.contracts import IamPrincipal

_READ_ROLES = frozenset(
    {
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.OWNER,
    }
)
_WRITE_ROLES = frozenset({OperatorRole.CONTRIBUTOR, OperatorRole.APPROVER, OperatorRole.OWNER})
_CONVERSATION_WRITE_OPERATIONS = frozenset(
    spec.operation
    for spec in CONVERSATION_ROUTE_MANIFEST
    if spec.mode == "proposal" or (spec.mode == "stream" and spec.method == "POST")
)


@dataclass(frozen=True, slots=True)
class OperatorFamilyAuthorizer:
    """Adapt one verified authenticator to family-specific principal contracts."""

    authenticator: OperatorAuthenticator

    async def authorize(self, request: Request, *, operation: str) -> PrincipalScope:
        """Authenticate conversation reads and require contributor roles for proposals."""
        required = _WRITE_ROLES if operation in _CONVERSATION_WRITE_OPERATIONS else _READ_ROLES
        principal = self.authenticator.require_any(
            request.headers.get("authorization"),
            required,
        )
        return PrincipalScope(
            subject_id=principal.subject_id,
            roles=frozenset(role.value for role in principal.roles),
        )

    async def iam(self, request: Request) -> IamPrincipal:
        """Authenticate IAM callers while leaving capability checks to owned routes."""
        principal = self.authenticator.authenticate(request.headers.get("authorization"))
        return IamPrincipal(oid=principal.subject_id, roles=principal.roles)

    async def workflow(
        self,
        request: Request,
        required_roles: frozenset[OperatorRole],
    ) -> OperatorPrincipal:
        """Enforce the workflow manifest's exact server-owned role set."""
        return self.authenticator.require_any(
            request.headers.get("authorization"),
            required_roles,
        )


__all__ = ["OperatorFamilyAuthorizer"]
