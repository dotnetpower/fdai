"""Generic Entra ID JWT verifier for the console read API.

Concrete :data:`fdai.delivery.read_api.auth.ClaimsVerifier` implementation
that upstream now ships (previously left to the fork's composition root).
It performs the **cryptographic half** of the boundary contract in
[`user-rbac-and-identity.md § 10.2`]
(../../../../../docs/roadmap/user-rbac-and-identity.md#102-api-token-validation):
JWKS signature, ``aud``, ``iss``, ``exp``/``nbf``. The **RBAC half**
(``roles`` claim -> :class:`~fdai.core.rbac.resolver.Principal`) stays in
:class:`fdai.core.rbac.resolver.RoleResolver`; this module never resolves
roles and never re-hits the network per request beyond the cached JWKS.

Customer-agnostic
-----------------

Nothing is baked in. The tenant id, API audience, and (optionally) the
issuer / JWKS URI arrive via environment variables:

- ``FDAI_ENTRA_TENANT_ID`` (required) - the fork's single tenant.
- ``FDAI_API_AUDIENCE`` (required) - the ``fdai-api`` App ID URI, e.g.
  ``api://<fdai-api-guid>``. The access token's ``aud`` MUST equal this.
- ``FDAI_ENTRA_ISSUER`` (optional) - defaults to the v2 issuer
  ``https://login.microsoftonline.com/<tenant>/v2.0``. A fork whose
  ``fdai-api`` app still issues v1 access tokens sets this to
  ``https://sts.windows.net/<tenant>/``.
- ``FDAI_ENTRA_JWKS_URI`` (optional) - defaults to the tenant's public
  key set; override only for sovereign / air-gapped clouds.

``core/`` never imports this module - validating a **human** bearer token
is a delivery-layer concern (the executor's non-human identity is governed
separately by ``security-and-identity.md``).

Sync by design
--------------

:data:`ClaimsVerifier` is a **sync** callable and PyJWT's
:class:`~jwt.PyJWKClient` caches the tenant JWKS in-process, so per-request
verification is local RSA crypto (sub-millisecond). Only the first request
after a signing-key rotation performs a blocking JWKS fetch (bounded by
``timeout``); that is acceptable for a read-only console API and keeps the
sync boundary contract intact - no async ripple into
:class:`~fdai.delivery.read_api.auth.Authenticator`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

from fdai.delivery.read_api.auth import AuthenticationError

_DEFAULT_ALGORITHMS: tuple[str, ...] = ("RS256",)
_DEFAULT_LEEWAY_SECONDS: int = 60
_DEFAULT_JWKS_TIMEOUT_SECONDS: int = 10
_DEFAULT_JWKS_LIFESPAN_SECONDS: int = 3600

_TENANT_ENV = "FDAI_ENTRA_TENANT_ID"
_AUDIENCE_ENV = "FDAI_API_AUDIENCE"
_ISSUER_ENV = "FDAI_ENTRA_ISSUER"
_JWKS_URI_ENV = "FDAI_ENTRA_JWKS_URI"


class EntraVerifierConfigError(ValueError):
    """Raised at startup when required Entra verifier env/config is missing.

    Fail-fast, deny-by-default: a fork that forgets to supply the tenant id
    or audience gets a clear startup error rather than an API that silently
    trusts unverifiable tokens.
    """


@dataclass(frozen=True, slots=True)
class EntraJwtVerifier:
    """Verify an Entra access token and return its claims.

    Satisfies the :data:`~fdai.delivery.read_api.auth.ClaimsVerifier`
    structural type (``(token) -> claims``) by duck typing - it does not
    import the alias, only raises :class:`AuthenticationError` on failure,
    which :meth:`~fdai.delivery.read_api.auth.Authenticator.authenticate`
    maps to HTTP ``401``.
    """

    jwks_client: PyJWKClient
    audience: str
    issuer: str
    algorithms: tuple[str, ...] = field(default=_DEFAULT_ALGORITHMS)
    leeway_seconds: int = _DEFAULT_LEEWAY_SECONDS

    def __call__(self, token: str) -> Mapping[str, Any]:
        """Return verified claims or raise :class:`AuthenticationError`.

        Validates, in one :func:`jwt.decode` call: RS256 signature against
        the tenant JWKS (key selected by the token's ``kid``), ``aud`` ==
        :attr:`audience`, ``iss`` == :attr:`issuer`, and ``exp``/``nbf``
        within :attr:`leeway_seconds`. ``exp``, ``iss``, and ``aud`` are
        required claims - a token missing any of them is rejected.
        """
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
            # Never leak token contents in the message; the exception *type*
            # (ExpiredSignatureError / InvalidAudienceError / InvalidIssuerError
            # / InvalidSignatureError / ...) is enough to triage and is
            # audit-safe to log.
            raise AuthenticationError(
                f"Entra token verification failed: {type(exc).__name__}"
            ) from exc
        return claims

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EntraJwtVerifier:
        """Build a verifier from the fork's environment.

        Reads ``FDAI_ENTRA_TENANT_ID`` and ``FDAI_API_AUDIENCE`` (both
        required); derives the issuer and JWKS URI from the tenant unless
        ``FDAI_ENTRA_ISSUER`` / ``FDAI_ENTRA_JWKS_URI`` override them. The
        JWKS is fetched lazily on first use and cached in-process.
        """
        env = environ if environ is not None else os.environ
        tenant_id = _require(env, _TENANT_ENV)
        audience = _require(env, _AUDIENCE_ENV)
        issuer = env.get(_ISSUER_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        )
        jwks_uri = env.get(_JWKS_URI_ENV, "").strip() or (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        jwks_client = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            lifespan=_DEFAULT_JWKS_LIFESPAN_SECONDS,
            timeout=_DEFAULT_JWKS_TIMEOUT_SECONDS,
        )
        return cls(jwks_client=jwks_client, audience=audience, issuer=issuer)


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise EntraVerifierConfigError(
            f"{key} is required to build the Entra JWT verifier; set it in "
            "the fork's environment or secret store."
        )
    return value


__all__ = [
    "EntraJwtVerifier",
    "EntraVerifierConfigError",
]
