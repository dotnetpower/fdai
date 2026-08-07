"""Bearer authentication and role resolution owned by the ingestion API."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import jwt
from jwt import PyJWKClient


class Role(StrEnum):
    READER = "Reader"
    CONTRIBUTOR = "Contributor"
    APPROVER = "Approver"
    OWNER = "Owner"
    BREAK_GLASS = "BreakGlass"


class AuthenticationError(Exception):
    """A bearer token is missing, malformed, or fails verification."""


class RoleRequiredError(Exception):
    """The verified principal lacks every required role."""


@dataclass(frozen=True, slots=True)
class Principal:
    oid: str
    roles: frozenset[Role] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class GroupMapping:
    reader_group_id: str
    contributor_group_id: str
    approver_group_id: str
    owner_group_id: str
    break_glass_group_id: str

    def __post_init__(self) -> None:
        concrete = tuple(
            value
            for value in (
                self.reader_group_id,
                self.contributor_group_id,
                self.approver_group_id,
                self.owner_group_id,
                self.break_glass_group_id,
            )
            if value != "00000000-0000-0000-0000-000000000000"
        )
        if len(concrete) != len(set(concrete)):
            raise ValueError("RBAC group objectIds MUST be unique")

    def roles_by_group(self) -> Mapping[str, Role]:
        return {
            self.reader_group_id: Role.READER,
            self.contributor_group_id: Role.CONTRIBUTOR,
            self.approver_group_id: Role.APPROVER,
            self.owner_group_id: Role.OWNER,
            self.break_glass_group_id: Role.BREAK_GLASS,
        }


ClaimsVerifier = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class Authenticator:
    verifier: ClaimsVerifier
    mapping: GroupMapping

    def require_roles(
        self,
        authorization_header: str | None,
        *,
        required: tuple[Role, ...],
    ) -> Principal:
        if not authorization_header or not authorization_header.startswith("Bearer "):
            raise AuthenticationError("Authorization header MUST use the Bearer scheme")
        token = authorization_header.removeprefix("Bearer ").strip()
        if not token:
            raise AuthenticationError("Bearer token is empty")
        try:
            claims = self.verifier(token)
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(f"token verification failed: {type(exc).__name__}") from exc
        oid = claims.get("oid")
        if not isinstance(oid, str) or not oid:
            raise AuthenticationError("verified claims MUST carry a non-empty oid")
        groups = _claim_strings(claims.get("groups"))
        claimed_roles = {
            role
            for value in _claim_strings(claims.get("roles"))
            if (role := _role(value)) is not None and role is not Role.BREAK_GLASS
        }
        if not claimed_roles:
            by_group = self.mapping.roles_by_group()
            claimed_roles = {
                role
                for group in groups
                if (role := by_group.get(group)) is not None and role is not Role.BREAK_GLASS
            }
        principal = Principal(
            oid=oid,
            roles=frozenset(claimed_roles),
            groups=frozenset(groups),
        )
        if principal.roles.isdisjoint(required):
            raise RoleRequiredError("principal lacks a required ingestion role")
        return principal


@dataclass(frozen=True, slots=True)
class EntraJwtVerifier:
    jwks_client: PyJWKClient
    audience: str
    issuer: str

    def __call__(self, token: str) -> Mapping[str, Any]:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
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

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EntraJwtVerifier:
        env = environ if environ is not None else os.environ
        tenant_id = _required(env, "FDAI_ENTRA_TENANT_ID")
        audience = _required(env, "FDAI_API_AUDIENCE")
        issuer = env.get("FDAI_ENTRA_ISSUER", "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        jwks_uri = env.get("FDAI_ENTRA_JWKS_URI", "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        return cls(
            PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600, timeout=10), audience, issuer
        )


def _role(value: str) -> Role | None:
    try:
        return Role(value)
    except ValueError:
        return None


def _claim_strings(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value
