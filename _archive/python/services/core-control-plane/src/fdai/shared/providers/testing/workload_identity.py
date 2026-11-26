"""Static :class:`WorkloadIdentity` for unit tests + debugger sessions.

Issues a fixed token for one whitelisted audience. Cross-audience requests
raise, matching the contract rule ("cross-audience reuse is denied").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.shared.providers.workload_identity import (
    IdentityToken,
    WorkloadIdentity,
)


class StaticWorkloadIdentity(WorkloadIdentity):
    """A test-only :class:`WorkloadIdentity` that hands out one token."""

    def __init__(
        self,
        *,
        audience: str,
        token: str = "test-token",  # noqa: S107 - deterministic test literal
        ttl: timedelta = timedelta(hours=1),
    ) -> None:
        self._audience = audience
        self._token = token
        self._ttl = ttl

    async def get_token(self, audience: str) -> IdentityToken:
        if audience != self._audience:
            raise ValueError(
                f"no token available for audience {audience!r}; "
                f"this fake is configured for {self._audience!r}"
            )
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + self._ttl,
            audience=audience,
        )


__all__ = ["StaticWorkloadIdentity"]
