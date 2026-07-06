"""Bearer-token authentication + role gate for the console API.

Wire-up between the framework-neutral RBAC primitives in
:mod:`aiopspilot.core.rbac` and the concrete HTTP surface (Session I, the
console read API). Framework-neutral by design: neither FastAPI nor
Starlette is imported at module load. The read-API composition binds this
into an ASGI app; unit tests exercise it with plain callables.

Boundary contract
-----------------

The read API is responsible for **JWT signature + audience + issuer + expiry
validation** before this module ever sees the claims (see
[`user-rbac-and-identity.md § 10.2`]
(../../../../../docs/roadmap/user-rbac-and-identity.md#102-api-token-validation)).
The verifier is injected — :func:`build_authenticator` accepts a
:class:`ClaimsVerifier` callable of shape ``(token) -> claims``. Upstream
does not ship a real JWKS-fetching verifier; that concrete implementation
lives in the fork's composition root, alongside its ``httpx`` client and
Entra tenant endpoint.

A test / dev-mode fake verifier is
:class:`UnsafeClaimsExtractor`, which uses
:func:`aiopspilot.core.rbac.resolver.decode_jwt_payload` and MUST NOT be
wired in production.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from aiopspilot.core.rbac.enforcer import RoleEnforcer
from aiopspilot.core.rbac.resolver import (
    MalformedTokenError,
    Principal,
    RoleResolver,
    decode_jwt_payload,
)
from aiopspilot.core.rbac.roles import Role

_BEARER_PREFIX = "Bearer "

ClaimsVerifier = Callable[[str], Mapping[str, Any]]
"""Callable that verifies a JWT and returns its claims.

Implementations MUST:

- validate signature against the tenant JWKS;
- check ``aud`` matches ``api://<aiopspilot-api-guid>``;
- check ``iss`` matches the fork's Entra tenant issuer;
- check ``exp`` and ``nbf`` are current.

On any failure, raise :class:`AuthenticationError` — the read-API layer
translates that into HTTP ``401``. Do NOT raise :class:`AuthorizationError`
here; role checks happen later.
"""


class AuthenticationError(Exception):
    """Bearer token is missing, malformed, or fails signature/claims validation.

    Read-API layer maps this to HTTP ``401 Unauthorized``. Never leaks the
    token contents in ``str(exc)`` — the message is safe to log.
    """


@dataclass(frozen=True, slots=True)
class Authenticator:
    """One-per-process request authenticator.

    Given the raw ``Authorization`` header value, produces a
    :class:`~aiopspilot.core.rbac.resolver.Principal` or raises
    :class:`AuthenticationError`. Combines the injected
    :class:`ClaimsVerifier` (crypto) with :class:`RoleResolver` (RBAC).
    """

    verifier: ClaimsVerifier
    resolver: RoleResolver
    enforcer: RoleEnforcer

    def authenticate(
        self,
        authorization_header: str | None,
        *,
        correlation_id: str | None = None,
    ) -> Principal:
        """Return a :class:`Principal` for the given header value.

        - Missing header → :class:`AuthenticationError` (401 later).
        - Token verification failure → :class:`AuthenticationError`.
        - Successful verification with an *empty* ``roles`` (no App Role
          assigned) → returns a Principal with :attr:`Principal.roles`
          == ``frozenset()``. The route-level enforcer is responsible for
          the 403 that comes next (see
          [`user-rbac-and-identity.md § 10.3`]
          (../../../../../docs/roadmap/user-rbac-and-identity.md#103-first-sign-in-unassigned-users));
          this method never conflates "not authenticated" with "not authorized".
        """
        token = _extract_bearer(authorization_header)
        try:
            claims = self.verifier(token)
        except AuthenticationError:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap arbitrary verifier failures
            raise AuthenticationError(f"token verification failed: {type(exc).__name__}") from exc
        try:
            return self.resolver.resolve_from_claims(claims, correlation_id=correlation_id)
        except ValueError as exc:
            raise AuthenticationError(f"invalid claims: {exc}") from exc

    def require_roles(
        self,
        authorization_header: str | None,
        *,
        required: tuple[Role, ...],
        correlation_id: str | None = None,
    ) -> Principal:
        """Authenticate + gate on the given roles in one call.

        Convenience for handlers that do not need to distinguish 401 from 403
        in their own code — the surrounding exception handler still keeps
        them apart because :class:`AuthenticationError` and
        :class:`AuthorizationError` are distinct types.
        """
        principal = self.authenticate(authorization_header, correlation_id=correlation_id)
        self.enforcer.authorize(principal, required)
        return principal


def build_authenticator(*, verifier: ClaimsVerifier, resolver: RoleResolver) -> Authenticator:
    """Build an :class:`Authenticator` with the default clock-based enforcer.

    Convenience factory the read-API composition root calls once at
    startup. A test that needs a frozen clock builds an
    :class:`Authenticator` directly with its own :class:`RoleEnforcer`.
    """
    return Authenticator(
        verifier=verifier,
        resolver=resolver,
        enforcer=RoleEnforcer(),
    )


def _extract_bearer(header: str | None) -> str:
    if not header:
        raise AuthenticationError("Authorization header missing")
    if not header.startswith(_BEARER_PREFIX):
        raise AuthenticationError("Authorization header MUST use the Bearer scheme")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise AuthenticationError("Bearer token is empty")
    return token


class UnsafeClaimsExtractor:
    """Development-only :class:`ClaimsVerifier` that skips signature verification.

    Uses :func:`aiopspilot.core.rbac.resolver.decode_jwt_payload` to pull
    claims out of a JWT without any cryptographic check. **MUST NOT** be
    wired into a production composition root — the fork's real verifier
    (JWKS + audience + issuer + expiry) replaces this.

    Kept in-tree so unit tests can exercise the read-API surface without
    a live Entra tenant, and so the local dev harness in
    [`dev-and-deploy-parity.md`]
    (../../../../../docs/roadmap/dev-and-deploy-parity.md) works
    end-to-end without customer values.
    """

    def __call__(self, token: str) -> Mapping[str, Any]:
        try:
            return decode_jwt_payload(token)
        except MalformedTokenError as exc:
            raise AuthenticationError(str(exc)) from exc


__all__ = [
    "AuthenticationError",
    "Authenticator",
    "ClaimsVerifier",
    "UnsafeClaimsExtractor",
    "build_authenticator",
]
