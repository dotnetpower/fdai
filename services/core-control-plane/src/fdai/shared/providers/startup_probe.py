"""Injected provider seam for bounded startup probes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable

StartupProbeResultT = TypeVar("StartupProbeResultT", covariant=True)


@dataclass(frozen=True, slots=True)
class StartupProbeRequest:
    """Per-attempt limits passed to every provider implementation."""

    deadline: datetime
    cost_limit_usd: float
    model_sample_count: int
    synthetic_scope: bool
    evidence_ttl_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.evidence_ttl_seconds <= 0:
            raise ValueError("startup evidence TTL MUST be positive")


@runtime_checkable
class StartupProbe(Protocol[StartupProbeResultT]):
    """Run one read-only or explicitly synthetic startup check."""

    @property
    def probe_id(self) -> str: ...

    async def run(self, request: StartupProbeRequest) -> StartupProbeResultT: ...


__all__ = ["StartupProbe", "StartupProbeRequest", "StartupProbeResultT"]
