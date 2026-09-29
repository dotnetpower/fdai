"""Caller authentication for the deployed operational evidence verifier.

The deployed verifier accepts issuance requests only from the registered producer
workload identity. The bearer token is validated behind this provider seam and is
never retained, logged, echoed, or written into proof records.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import jwt
from aiohttp import web


class CallerAuthenticationError(ValueError):
    """A bearer token did not prove the configured producer workload identity."""


@dataclass(frozen=True, slots=True)
class ValidatedCallerToken:
    """Content-free identity claims extracted from a validated bearer token."""

    issuer: str
    audience: str
    oid: str
    expires_at: int


class BearerTokenValidator(Protocol):
    """Validate one short-lived bearer token without retaining it."""

    def validate(self, token: str) -> ValidatedCallerToken: ...


@dataclass(frozen=True, slots=True)
class StaticJwksBearerTokenValidator:
    """Validate an Entra-compatible JWT using a deployment-supplied JWKS document."""

    issuer: str
    audience: str
    jwks_json: str
    algorithms: tuple[str, ...] = ("RS256",)

    def validate(self, token: str) -> ValidatedCallerToken:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            jwks = jwt.PyJWKSet.from_json(self.jwks_json)
            candidates = [key for key in jwks.keys if kid is None or key.key_id == kid]
            if len(candidates) != 1:
                raise CallerAuthenticationError("caller token key is ambiguous")
            claims = jwt.decode(
                token,
                candidates[0].key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "oid"]},
            )
        except (jwt.PyJWTError, ValueError) as exc:
            raise CallerAuthenticationError("caller token is invalid") from exc
        oid = claims.get("oid")
        exp = claims.get("exp")
        aud = claims.get("aud")
        if not isinstance(oid, str) or not oid.strip() or not isinstance(exp, int):
            raise CallerAuthenticationError("caller token is missing required identity claims")
        if isinstance(aud, list):
            if self.audience not in aud:
                raise CallerAuthenticationError("caller token audience is invalid")
            audience = self.audience
        elif isinstance(aud, str):
            audience = aud
        else:
            raise CallerAuthenticationError("caller token audience is invalid")
        return ValidatedCallerToken(
            issuer=str(claims["iss"]),
            audience=audience,
            oid=oid,
            expires_at=exp,
        )


@dataclass(frozen=True, slots=True)
class WorkloadCallerAuthenticator:
    """Authenticate a verifier HTTP request as the registered producer principal."""

    expected_issuer: str
    expected_audience: str
    registered_producer_principal: str
    validator: BearerTokenValidator

    def authenticate(self, request: web.Request) -> str | None:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or authorization.count(" ") != 1:
            return None
        token = authorization.removeprefix("Bearer ")
        if not token:
            return None
        try:
            claims = self.validator.validate(token)
        except CallerAuthenticationError:
            return None
        if (
            claims.issuer != self.expected_issuer
            or claims.audience != self.expected_audience
            or claims.oid != self.registered_producer_principal
            or claims.expires_at <= int(time.time())
        ):
            return None
        return claims.oid


__all__ = [
    "BearerTokenValidator",
    "CallerAuthenticationError",
    "StaticJwksBearerTokenValidator",
    "ValidatedCallerToken",
    "WorkloadCallerAuthenticator",
]
