"""LocalWorkloadIdentity - deterministic in-memory OIDC token issuer.

Used in dev + tests. The token is a synthetic HS256-style string (no
real signature) so no cryptography libs are pulled into the wheel; the
Azure OpenAI + ARG adapters that consume it via httpx.MockTransport
never validate the signature. Real prod uses the Managed-Identity
adapter - this module is NEVER active when ``runtime.env == 'prod'``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.shared.providers.workload_identity import IdentityToken


@dataclass(frozen=True, slots=True)
class LocalWorkloadIdentityConfig:
    """Knobs for the dev-mode token issuer."""

    principal_object_id: str = "00000000-0000-0000-0000-000000000001"
    """The identity the fake claims to be. Prod uses the MI's real oid."""

    tenant_id: str = "00000000-0000-0000-0000-000000000000"
    ttl_seconds: int = 3600


class LocalWorkloadIdentity:
    """Deterministic :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`.

    Tokens are stable per ``(audience, tenant_id, principal_object_id)`` so a
    test replay produces byte-identical audit entries. A cache honours
    :attr:`LocalWorkloadIdentityConfig.ttl_seconds` - beyond that a fresh
    token is minted (again deterministically).
    """

    def __init__(self, *, config: LocalWorkloadIdentityConfig | None = None) -> None:
        cfg = config or LocalWorkloadIdentityConfig()
        if cfg.ttl_seconds < 1:
            raise ValueError("ttl_seconds MUST be >= 1")
        self._config = cfg
        # Simple audience cache - Protocol contract forbids cross-audience
        # reuse, so keyed by full audience string.
        self._cache: dict[str, IdentityToken] = {}

    async def get_token(self, audience: str) -> IdentityToken:
        cached = self._cache.get(audience)
        now = datetime.now(tz=UTC)
        if cached is not None and cached.expires_at > now + timedelta(seconds=60):
            return cached
        expires_at = now + timedelta(seconds=self._config.ttl_seconds)
        token = _synthetic_token(
            audience=audience,
            principal_object_id=self._config.principal_object_id,
            tenant_id=self._config.tenant_id,
            expires_at=expires_at,
        )
        identity = IdentityToken(token=token, expires_at=expires_at, audience=audience)
        self._cache[audience] = identity
        return identity


def _synthetic_token(
    *,
    audience: str,
    principal_object_id: str,
    tenant_id: str,
    expires_at: datetime,
) -> str:
    """Hex-encoded SHA256 of the claims - deterministic, not cryptographic.

    A downstream test-mode HTTP handler can accept any bearer that starts
    with the ``fdai-local:`` prefix; production adapters MUST NOT
    accept this token - the Azure identity plane rejects it because the
    signature is not real.
    """
    claims: Mapping[str, str] = {
        "aud": audience,
        "oid": principal_object_id,
        "tid": tenant_id,
        "exp": expires_at.replace(tzinfo=UTC).isoformat(),
    }
    payload = "|".join(f"{k}={v}" for k, v in sorted(claims.items()))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"fdai-local:{digest}"


__all__ = ["LocalWorkloadIdentity", "LocalWorkloadIdentityConfig"]
