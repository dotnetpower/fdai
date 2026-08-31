"""Entra bearer verification and human-role resolution owned by Operator Service."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import jwt
from fdai_service_contracts import (
    OperatorPrincipal,
    OperatorPrincipalKind,
    OperatorRole,
    OperatorTokenVerifier,
)
from jwt import PyJWKClient

from fdai_operator_service.environment import OperatorEnvironment

_BEARER_PREFIX = "Bearer "


class AuthenticationError(Exception):
    """A human bearer token is missing, malformed, or unverified."""


class AuthorizationError(Exception):
    """A verified human principal lacks every required role."""


@dataclass(frozen=True, slots=True)
class EntraJwtVerifier:
    """Verify Entra JWT signature and required audience, issuer, and time claims."""

    jwks_client: PyJWKClient
    audience: str
    issuer: str

    def __call__(self, token: str) -> Mapping[str, object]:
        """Return verified claims while redacting provider failure details."""
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=60,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(
                f"Entra token verification failed: {type(exc).__name__}"
            ) from exc
        return cast(Mapping[str, object], claims)

    @classmethod
    def from_environment(cls, environment: OperatorEnvironment) -> EntraJwtVerifier:
        """Build a verifier with process-local bounded JWKS caching."""
        return cls(
            jwks_client=PyJWKClient(
                environment.jwks_uri,
                cache_keys=True,
                lifespan=3600,
                timeout=10,
            ),
            audience=environment.audience,
            issuer=environment.issuer,
        )


@dataclass(frozen=True, slots=True)
class VerifiedOperatorIdentity:
    """Retain one verified principal and its token's authorized client."""

    principal: OperatorPrincipal
    authorized_party: str | None


@dataclass(frozen=True, slots=True)
class OperatorAuthenticator:
    """Authenticate verified claims and enforce server-owned role gates."""

    verifier: OperatorTokenVerifier
    group_ids: Mapping[OperatorRole, str]

    def authenticate(self, authorization_header: str | None) -> OperatorPrincipal:
        """Return a verified principal or raise a stable authentication error."""
        return self.authenticate_identity(authorization_header).principal

    def authenticate_identity(
        self,
        authorization_header: str | None,
    ) -> VerifiedOperatorIdentity:
        """Return server-derived authority plus the verified client binding."""
        token = _extract_bearer(authorization_header)
        try:
            claims = self.verifier(token)
        except AuthenticationError:
            raise
        except Exception as exc:  # noqa: BLE001 - verifiers share one boundary.
            raise AuthenticationError(f"token verification failed: {type(exc).__name__}") from exc
        subject_id = claims.get("oid")
        if not isinstance(subject_id, str) or not subject_id:
            raise AuthenticationError("invalid claims: missing non-empty oid")

        claimed_roles = _parse_roles(claims.get("roles"))
        principal_kind = _principal_kind(claims)
        if principal_kind is OperatorPrincipalKind.WORKLOAD:
            if claimed_roles != frozenset({OperatorRole.READER}):
                raise AuthenticationError(
                    "invalid claims: workload principals require the Reader App Role"
                )
            return VerifiedOperatorIdentity(
                principal=OperatorPrincipal(
                    subject_id=_principal_digest(subject_id),
                    roles=claimed_roles,
                    principal_kind=principal_kind,
                ),
                authorized_party=_authorized_party(claims),
            )
        if not claimed_roles and _has_group_overage(claims):
            raise AuthenticationError("invalid claims: group overage tokens require FDAI App Roles")
        if not claimed_roles:
            groups = frozenset(_string_items(claims.get("groups")))
            claimed_roles = frozenset(
                role for role, group_id in self.group_ids.items() if group_id in groups
            )
        return VerifiedOperatorIdentity(
            principal=OperatorPrincipal(
                subject_id=subject_id,
                roles=claimed_roles,
                principal_kind=principal_kind,
            ),
            authorized_party=_authorized_party(claims),
        )

    def require_any(
        self,
        authorization_header: str | None,
        required: frozenset[OperatorRole],
    ) -> OperatorPrincipal:
        """Authenticate and require at least one role without implicit elevation."""
        principal = self.authenticate(authorization_header)
        if principal.roles.isdisjoint(required):
            expected = ", ".join(sorted(role.value for role in required))
            actual = ", ".join(sorted(role.value for role in principal.roles))
            raise AuthorizationError(
                f"principal lacks required role: any of {{{expected}}} (has {{{actual}}})"
            )
        return principal


def _extract_bearer(header: str | None) -> str:
    if not header:
        raise AuthenticationError("Authorization header missing")
    if not header.startswith(_BEARER_PREFIX):
        raise AuthenticationError("Authorization header MUST use the Bearer scheme")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise AuthenticationError("Bearer token is empty")
    return token


def _parse_roles(raw: object) -> frozenset[OperatorRole]:
    roles: set[OperatorRole] = set()
    for value in _string_items(raw):
        try:
            roles.add(OperatorRole(value))
        except ValueError:
            continue
    return frozenset(roles)


def _string_items(raw: object) -> Iterable[str]:
    if isinstance(raw, str):
        yield from raw.split()
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        for value in raw:
            if isinstance(value, str) and value:
                yield value


def _has_group_overage(claims: Mapping[str, object]) -> bool:
    if claims.get("hasgroups") is True:
        return True
    claim_names = claims.get("_claim_names")
    return isinstance(claim_names, Mapping) and "groups" in claim_names


def _principal_kind(claims: Mapping[str, object]) -> OperatorPrincipalKind:
    identity_type = claims.get("idtyp")
    if identity_type is None or identity_type == "user":
        return OperatorPrincipalKind.HUMAN
    if identity_type == "app":
        return OperatorPrincipalKind.WORKLOAD
    raise AuthenticationError("invalid claims: unsupported principal type")


def _principal_digest(subject_id: str) -> str:
    digest = hashlib.sha256(subject_id.casefold().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _authorized_party(claims: Mapping[str, object]) -> str | None:
    value = claims.get("azp", claims.get("appid"))
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise AuthenticationError("invalid claims: authorized party is malformed")
    return value.strip()


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "EntraJwtVerifier",
    "OperatorAuthenticator",
    "VerifiedOperatorIdentity",
]
