"""Transport-neutral readiness evidence for independently deployed adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdapterReadinessState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class AdapterReadiness(BaseModel):
    """Bounded adapter readiness that distinguishes config evidence from a live probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Annotated[str, Field(min_length=1, max_length=128)]
    state: AdapterReadinessState
    evidence: Literal["configuration", "live"]
    live_verified: bool
    reason: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def _validate_evidence(self) -> AdapterReadiness:
        if self.state is AdapterReadinessState.UNAVAILABLE and self.reason is None:
            raise ValueError("unavailable adapter readiness MUST include a reason")
        if self.evidence == "configuration" and self.live_verified:
            raise ValueError("configuration readiness cannot claim live verification")
        return self


@runtime_checkable
class AdapterReadinessProvider(Protocol):
    """Describe adapter readiness without requiring network access."""

    def readiness(self) -> AdapterReadiness: ...


@runtime_checkable
class AdapterLiveReadinessProvider(Protocol):
    """Perform one bounded adapter check without exposing connection material."""

    async def probe_readiness(self) -> AdapterReadiness: ...


def configured_readiness(adapter: str) -> AdapterReadiness:
    """Return readiness proven only by validated config and injected dependencies."""
    return AdapterReadiness(
        adapter=adapter,
        state=AdapterReadinessState.READY,
        evidence="configuration",
        live_verified=False,
    )


def unavailable_readiness(adapter: str, reason: str) -> AdapterReadiness:
    """Return explicit fail-closed unavailability evidence."""
    return AdapterReadiness(
        adapter=adapter,
        state=AdapterReadinessState.UNAVAILABLE,
        evidence="configuration",
        live_verified=False,
        reason=reason,
    )


def live_readiness(adapter: str) -> AdapterReadiness:
    """Return successful evidence from a bounded live adapter operation."""
    return AdapterReadiness(
        adapter=adapter,
        state=AdapterReadinessState.READY,
        evidence="live",
        live_verified=True,
    )


def live_unavailable_readiness(adapter: str, reason: str) -> AdapterReadiness:
    """Return sanitized failure evidence from a bounded live adapter operation."""
    return AdapterReadiness(
        adapter=adapter,
        state=AdapterReadinessState.UNAVAILABLE,
        evidence="live",
        live_verified=False,
        reason=reason,
    )
