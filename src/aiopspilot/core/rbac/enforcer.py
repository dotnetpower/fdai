"""Route/handler-level RBAC gate + separation-of-duties check.

Framework-neutral by design — no FastAPI/Starlette import. The three public
surfaces are:

- :class:`RoleEnforcer` — the pure decision object: given a
  :class:`~aiopspilot.core.rbac.resolver.Principal` and a required role or
  capability, either return ``None`` or raise an
  :class:`AuthorizationError` subclass. The read-API layer wraps this in
  its own FastAPI dependency (see
  :mod:`aiopspilot.delivery.read_api.auth`).
- :func:`require_roles` / :func:`require_capability` — factory helpers
  that return a *callable dependency* of shape ``(principal) -> principal``.
  The shape is FastAPI-compatible via ``Depends(...)`` but does not require
  FastAPI to be importable at core-layer parse time.
- :meth:`RoleEnforcer.no_self_approval` — the audited author-vs-approver
  separation check pulled from
  [`user-rbac-and-identity.md § 5.2 Author-is-not-approver`]
  (../../../../docs/roadmap/user-rbac-and-identity.md#52-ci-checks-upstream-provided-fork-configured)
  and [`security-and-identity.md § HIL Approval Integrity`]
  (../../../../docs/roadmap/security-and-identity.md#hil-approval-integrity).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from aiopspilot.core.rbac.resolver import Principal
from aiopspilot.core.rbac.roles import (
    Capability,
    Role,
    has_capability,
)


class AuthorizationError(Exception):
    """Base class for RBAC-layer authorization failures.

    Callers (or a FastAPI exception handler) translate this into an HTTP
    ``403`` response. Never surfaces token contents in ``str(exc)`` — the
    message is safe to log per :ref:`coding-conventions § Logging`.
    """


class RoleRequiredError(AuthorizationError):
    """The principal lacks the roles required by the guarded route."""


class SelfApprovalError(AuthorizationError):
    """The principal attempted to approve their own submitted change.

    Enforcement lives at BOTH the CI layer (governance PRs) and here (runtime
    HIL approvals), so a fork's audit adapter records the same
    ``correlation_id`` on both surfaces.
    """


class BreakGlassExpiredError(AuthorizationError):
    """Principal carries :attr:`Role.BREAK_GLASS` but the timebox has elapsed.

    Break-glass is time-bounded on purpose (see
    :class:`~aiopspilot.core.rbac.resolver.BreakGlassActivation`); once the
    ``expires_at`` mark passes, the elevated role stops counting toward
    :meth:`RoleEnforcer.authorize` even if the principal object still
    physically carries it.
    """


class RoleEnforcer:
    """Immutable authorizer.

    Instances are cheap — the read-API layer builds one per process and
    reuses it for every request. No state is mutated per call, so
    concurrent access is safe.
    """

    __slots__ = ("_clock",)

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        # Injectable clock keeps break-glass expiry testable without freezing
        # wall-clock time process-wide.
        self._clock = clock or _utcnow

    def authorize(self, principal: Principal, required_roles: Iterable[Role]) -> None:
        """Raise :class:`RoleRequiredError` unless the principal carries any required role.

        An empty ``required_roles`` iterable is a programmer error — this
        method raises :class:`ValueError` for it rather than silently
        allowing all callers.
        """
        required = frozenset(required_roles)
        if not required:
            raise ValueError(
                "authorize() requires at least one required role; "
                "pass Role.READER for a view-only surface"
            )
        effective = self._effective_roles(principal)
        if effective.isdisjoint(required):
            raise RoleRequiredError(
                f"principal lacks required role: any of {_role_set_str(required)} "
                f"(has {_role_set_str(effective)})"
            )

    def require_capability(self, principal: Principal, capability: Capability) -> None:
        """Raise :class:`RoleRequiredError` unless a held role covers ``capability``."""
        effective = self._effective_roles(principal)
        if not has_capability(effective, capability):
            raise RoleRequiredError(
                f"principal lacks capability {capability.value!r} "
                f"(has roles {_role_set_str(effective)})"
            )

    def no_self_approval(self, approver: Principal, *, submitter_oid: str) -> None:
        """Raise :class:`SelfApprovalError` when the approver authored the change.

        Comparison uses Entra ``oid`` — never ``upn`` or ``email`` — because
        UPNs can be renamed and emails aliased. Auditors follow the same
        rule (see [`user-rbac-and-identity.md § 10.2`]
        (../../../../docs/roadmap/user-rbac-and-identity.md#102-api-token-validation)).

        A ``submitter_oid`` that is empty or None is a programmer bug — the
        caller MUST record submitter identity on the pending item before
        it enters an approval queue.
        """
        if not submitter_oid:
            raise ValueError(
                "no_self_approval() requires a non-empty submitter_oid — "
                "the pending item must record its author's Entra oid"
            )
        if approver.oid == submitter_oid:
            raise SelfApprovalError(
                "approver.oid == submitter_oid; no-self-approval invariant would be violated"
            )

    def _effective_roles(self, principal: Principal) -> frozenset[Role]:
        """Drop :attr:`Role.BREAK_GLASS` when its timebox has elapsed.

        If the principal carries the role but no activation stamp, treat it
        as expired — the resolver only attaches the role via
        :meth:`~aiopspilot.core.rbac.resolver.RoleResolver.activate_break_glass`,
        which always stamps the activation, so an unstamped principal is a
        bug we fail closed on.
        """
        if Role.BREAK_GLASS not in principal.roles:
            return principal.roles
        activation = principal.break_glass
        now = self._clock()
        if activation is None or not activation.is_active_at(now):
            raise BreakGlassExpiredError(
                "BreakGlass role present but activation is missing or expired"
            )
        return principal.roles


# ---------------------------------------------------------------------------
# Framework-neutral dependency factories
# ---------------------------------------------------------------------------


def require_roles(
    *roles: Role, enforcer: RoleEnforcer | None = None
) -> Callable[[Principal], Principal]:
    """Return a dependency that gates a handler on any of ``roles``.

    Usage in an ASGI framework::

        require_approver = require_roles(Role.APPROVER, Role.OWNER)

        @router.post('/approvals')
        async def post_approval(principal: Principal = Depends(require_approver)):
            ...

    The returned callable takes an already-resolved
    :class:`Principal` and returns it unchanged when authorized, so the
    surrounding framework's DI can inject the resolved principal into the
    handler. Raises :class:`RoleRequiredError` on failure — the read-API
    layer maps that to HTTP 403.
    """
    if not roles:
        raise ValueError("require_roles() requires at least one Role")
    active = enforcer if enforcer is not None else RoleEnforcer()
    required = frozenset(roles)

    def _dependency(principal: Principal) -> Principal:
        active.authorize(principal, required)
        return principal

    return _dependency


def require_capability(
    capability: Capability, *, enforcer: RoleEnforcer | None = None
) -> Callable[[Principal], Principal]:
    """Return a dependency that gates a handler on ``capability``."""
    active = enforcer if enforcer is not None else RoleEnforcer()

    def _dependency(principal: Principal) -> Principal:
        active.require_capability(principal, capability)
        return principal

    return _dependency


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _role_set_str(roles: frozenset[Role]) -> str:
    """Return a stable, sorted textual representation of a role set."""
    if not roles:
        return "{}"
    return "{" + ", ".join(sorted(role.value for role in roles)) + "}"


__all__ = [
    "AuthorizationError",
    "BreakGlassExpiredError",
    "RoleEnforcer",
    "RoleRequiredError",
    "SelfApprovalError",
    "require_capability",
    "require_roles",
]
