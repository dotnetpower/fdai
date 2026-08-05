"""Entra ID JWT verification for shared human-facing API delivery.

Responsibility: verify signature, audience, issuer, expiry, and supplied not-before
claims for a configured Entra application. Authority: cryptographic claims
verification only; role resolution and HTTP envelopes belong to their existing
owners. State: PyJWKClient's bounded process-local key cache. Dependencies:
PyJWT and deployment-supplied tenant metadata. Deployment role: reusable by
independently hosted API processes without sharing route or business policy.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

from fdai.delivery.auth.bearer import AuthenticationError

_DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)
_DEFAULT_LEEWAY_SECONDS = 60
_DEFAULT_JWKS_TIMEOUT_SECONDS = 10
_DEFAULT_JWKS_LIFESPAN_SECONDS = 3600

_TENANT_ENV = "FDAI_ENTRA_TENANT_ID"
_AUDIENCE_ENV = "FDAI_API_AUDIENCE"
_ISSUER_ENV = "FDAI_ENTRA_ISSUER"
_JWKS_URI_ENV = "FDAI_ENTRA_JWKS_URI"


class EntraVerifierConfigError(ValueError):
    """Required Entra verifier deployment configuration is missing."""


@dataclass(frozen=True, slots=True)
class EntraJwtVerifier:
    """Verify an Entra access token and return its claims."""

    jwks_client: PyJWKClient
    audience: str
    issuer: str
    algorithms: tuple[str, ...] = field(default=_DEFAULT_ALGORITHMS)
    leeway_seconds: int = _DEFAULT_LEEWAY_SECONDS

    def __call__(self, token: str) -> Mapping[str, Any]:
        """Return verified claims or raise :class:`AuthenticationError`."""
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(
                f"Entra token verification failed: {type(exc).__name__}"
            ) from exc
        return claims

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EntraJwtVerifier:
        """Build a lazily cached verifier from deployment environment values."""
        env = environ if environ is not None else os.environ
        tenant_id = _require(env, _TENANT_ENV)
        audience = _require(env, _AUDIENCE_ENV)
        issuer = env.get(_ISSUER_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        jwks_uri = env.get(_JWKS_URI_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        return cls(
            jwks_client=PyJWKClient(
                jwks_uri,
                cache_keys=True,
                lifespan=_DEFAULT_JWKS_LIFESPAN_SECONDS,
                timeout=_DEFAULT_JWKS_TIMEOUT_SECONDS,
            ),
            audience=audience,
            issuer=issuer,
        )


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise EntraVerifierConfigError(
            f"{key} is required to build the Entra JWT verifier; set it in "
            "the deployment environment or secret store."
        )
    return value


__all__ = ["EntraJwtVerifier", "EntraVerifierConfigError"]
