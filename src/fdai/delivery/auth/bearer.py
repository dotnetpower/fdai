"""Framework-neutral bearer authentication and human-role gating.

The module parses an Authorization header, delegates token verification to an
injected callable, resolves verified claims through core RBAC, and applies
route-supplied role requirements. It owns no HTTP paths, response envelopes,
CORS policy, executor identity, business exceptions, or mutable state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.core.rbac.enforcer import RoleEnforcer
from fdai.core.rbac.resolver import (
    MalformedTokenError,
    Principal,
    RoleResolver,
    decode_jwt_payload,
)
from fdai.core.rbac.roles import Role

_BEARER_PREFIX = "Bearer "

ClaimsVerifier = Callable[[str], Mapping[str, Any]]
"""Callable that verifies a JWT and returns its claims.

Implementations validate signature, audience, issuer, expiry, and any supplied
not-before claim. Any failure raises :class:`AuthenticationError`; role
authorization happens after claims verification.
"""


class AuthenticationError(Exception):
    """A bearer token is missing, malformed, or fails claims verification."""


@dataclass(frozen=True, slots=True)
class Authenticator:
    """Resolve a verified human bearer token into a core RBAC principal."""

    verifier: ClaimsVerifier
    resolver: RoleResolver
    enforcer: RoleEnforcer

    def authenticate(
        self,
        authorization_header: str | None,
        *,
        correlation_id: str | None = None,
    ) -> Principal:
        """Return a principal or raise :class:`AuthenticationError`."""
        token = _extract_bearer(authorization_header)
        try:
            claims = self.verifier(token)
        except AuthenticationError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize verifier failures
            raise AuthenticationError(f"token verification failed: {type(exc).__name__}") from exc
        try:
            return self.resolver.resolve_from_claims(
                claims,
                correlation_id=correlation_id,
            )
        except ValueError as exc:
            raise AuthenticationError(f"invalid claims: {exc}") from exc

    def require_roles(
        self,
        authorization_header: str | None,
        *,
        required: tuple[Role, ...],
        correlation_id: str | None = None,
    ) -> Principal:
        """Authenticate and require one of the supplied human roles."""
        principal = self.authenticate(
            authorization_header,
            correlation_id=correlation_id,
        )
        self.enforcer.authorize(principal, required)
        return principal


def build_authenticator(*, verifier: ClaimsVerifier, resolver: RoleResolver) -> Authenticator:
    """Build an authenticator with the default clock-based role enforcer."""
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
    """Test-only claims extraction that performs no signature verification."""

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
