"""Caller authentication for the deployed operational evidence verifier.

The deployed verifier accepts issuance requests only from the registered producer
workload identity. The bearer token is validated behind this provider seam and is
never retained, logged, echoed, or written into proof records.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

import jwt
from aiohttp import web

_API_UUID_AUDIENCE = re.compile(r"api://([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_JWK_PUBLIC_FIELDS = frozenset({"kty", "use", "kid", "n", "e", "alg", "crv", "x", "y"})


def _accepted_audiences(expected: str) -> tuple[str, ...]:
    match = _API_UUID_AUDIENCE.fullmatch(expected)
    if match is not None:
        return (expected, match.group(1))
    return (expected,)


def _load_jwks(raw: str) -> jwt.PyJWKSet:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("keys"), list):
        raise ValueError("JWKS document is invalid")
    keys = [
        {k: v for k, v in item.items() if k in _JWK_PUBLIC_FIELDS}
        for item in parsed["keys"]
        if isinstance(item, dict)
    ]
    return jwt.PyJWKSet.from_dict({"keys": keys})


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
        accepted_audiences = _accepted_audiences(self.audience)
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            jwks = _load_jwks(self.jwks_json)
            candidates = [key for key in jwks.keys if kid is None or key.key_id == kid]
            if len(candidates) != 1:
                raise CallerAuthenticationError("caller token key is ambiguous")
            claims = jwt.decode(
                token,
                candidates[0].key,
                algorithms=list(self.algorithms),
                audience=list(accepted_audiences),
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
            if not any(candidate in aud for candidate in accepted_audiences):
                raise CallerAuthenticationError("caller token audience is invalid")
            audience = self.audience
        elif isinstance(aud, str) and aud in accepted_audiences:
            audience = self.audience
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
