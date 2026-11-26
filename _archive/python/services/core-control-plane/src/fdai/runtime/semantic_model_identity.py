"""Bounded model-identity readiness for semantic conversation turns."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.readiness import ProbeStatus, StartupProbeResult
from fdai.shared.providers.startup_probe import StartupProbeRequest
from fdai.shared.providers.workload_identity import WorkloadIdentity

_LOGGER = logging.getLogger("fdai.startup")
_DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class SemanticModelIdentityReadiness:
    """Check every semantic-model audience without retaining credential material."""

    identity: WorkloadIdentity
    audiences: tuple[str, ...]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    probe_id: str = "semantic.model-identity"

    def __post_init__(self) -> None:
        if not self.audiences or any(not audience.strip() for audience in self.audiences):
            raise ValueError("semantic model identity audiences MUST be non-empty")
        if len(set(self.audiences)) != len(self.audiences):
            raise ValueError("semantic model identity audiences MUST be unique")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("semantic model identity timeout MUST be in (0, 30]")

    async def unavailable_reason(self) -> str | None:
        """Return a stable reason when a model-scoped token cannot be acquired."""

        try:
            async with asyncio.timeout(self.timeout_seconds):
                for audience in self.audiences:
                    token = await self.identity.get_token(audience)
                    if token.audience != audience or token.expires_at <= datetime.now(UTC):
                        raise RuntimeError("semantic model identity token is invalid")
        except Exception as exc:  # noqa: BLE001 - identity details stay inside this boundary
            _LOGGER.warning(
                "semantic_model_identity_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return "semantic_model_identity_unavailable"
        return None

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        """Project model identity into sanitized startup readiness evidence."""

        observed_at = datetime.now(UTC)
        reason = await self.unavailable_reason()
        return StartupProbeResult(
            probe_id=self.probe_id,
            status=ProbeStatus.PASSED if reason is None else ProbeStatus.FAILED,
            observed_at=observed_at,
            expires_at=observed_at + timedelta(seconds=request.evidence_ttl_seconds),
            latency_ms=0,
            failure_class=reason,
            evidence={"audience_count": len(self.audiences)},
        )


__all__ = ["SemanticModelIdentityReadiness"]
