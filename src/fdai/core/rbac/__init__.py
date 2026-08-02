"""Human-identity RBAC - the authority for who may do what via the Operator API.

Governs *human* users only: console sign-in, ChatOps approvers, catalog PR
authors. Non-human identities (executor Managed Identity, GitHub App,
Teams bot) stay under
[`docs/roadmap/architecture/security-and-identity.md`](../../../../docs/roadmap/architecture/security-and-identity.md);
they never share a principal with a human role in this module.

Design authority:
[`docs/roadmap/interfaces/user-rbac-and-identity.md`](../../../../docs/roadmap/interfaces/user-rbac-and-identity.md).

Four sub-modules, each with one responsibility (SRP):

- :mod:`.access_request` - governed role-change request persistence + audit.
- :mod:`.roles` - the 5-role enum + capability matrix (data only, no I/O).
- :mod:`.resolver` - Entra ID token claims → :class:`~.resolver.Principal`.
- :mod:`.enforcer` - gate a route/handler by role or capability, and reject
  self-approval on a governance action.

Every module is CSP-neutral: no Azure SDK import, no HTTP client, no
framework dependency. A caller that already has a *verified* claims dict
(the API layer is responsible for JWKS signature + audience + issuer
validation) hands it to :class:`~.resolver.RoleResolver` and gets back a
frozen :class:`~.resolver.Principal`.
"""

from __future__ import annotations

from fdai.core.rbac.access_request import (
    AccessOperation,
    AccessRequest,
    AccessRequestConflictError,
    AccessRequestError,
    AccessRequestPermissionError,
    AccessRequestService,
    AccessRequestStatus,
    AccessReviewDecision,
)
from fdai.core.rbac.enforcer import (
    AuthorizationError,
    BreakGlassExpiredError,
    RoleEnforcer,
    RoleRequiredError,
    SelfApprovalError,
    require_capability,
    require_roles,
)
from fdai.core.rbac.resolver import (
    BreakGlassActivation,
    BreakGlassActivationError,
    GroupMapping,
    MalformedTokenError,
    Principal,
    RoleResolver,
    decode_jwt_payload,
)
from fdai.core.rbac.roles import (
    ROLE_CAPABILITIES,
    Capability,
    Role,
    capabilities_for,
    has_capability,
)

__all__ = [
    "ROLE_CAPABILITIES",
    "AccessOperation",
    "AccessRequest",
    "AccessRequestConflictError",
    "AccessRequestError",
    "AccessRequestPermissionError",
    "AccessRequestService",
    "AccessRequestStatus",
    "AccessReviewDecision",
    "AuthorizationError",
    "BreakGlassActivation",
    "BreakGlassActivationError",
    "BreakGlassExpiredError",
    "Capability",
    "GroupMapping",
    "MalformedTokenError",
    "Principal",
    "Role",
    "RoleEnforcer",
    "RoleRequiredError",
    "RoleResolver",
    "SelfApprovalError",
    "capabilities_for",
    "decode_jwt_payload",
    "has_capability",
    "require_capability",
    "require_roles",
]
