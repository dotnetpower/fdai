"""Fail-closed pre-dispatch check for an A3-E lifecycle fence.

The guard is intentionally not wired into Thor or any executor. It proves the
read-time contract only; enforcement additionally needs a lease spanning the
side effect and independent promotion evidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from fdai.core.standing_authority.lifecycle import (
    AuthorizationLifecycleError,
    LifecycleFence,
)
from fdai.shared.providers.standing_authority import (
    StandingAuthorizationLifecycleStore,
    StandingAuthorizationStoreError,
)


class LifecycleFenceReason(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    STORE_UNAVAILABLE = "store_unavailable"


@dataclass(frozen=True, slots=True)
class LifecycleFenceResult:
    """Read-time fence result with no authority of its own."""

    current: bool
    reason: LifecycleFenceReason
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.current != (self.reason is LifecycleFenceReason.CURRENT):
            raise ValueError("lifecycle fence result mismatched its reason")


class StandingAuthorizationFenceGuard:
    """Compare an exact fence with the primary lifecycle snapshot."""

    def __init__(
        self,
        *,
        store: StandingAuthorizationLifecycleStore,
        timeout_seconds: float = 2.0,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise ValueError("standing authorization fence timeout MUST be in (0, 10]")
        self._store = store
        self._timeout_seconds = timeout_seconds

    async def evaluate(self, fence: LifecycleFence) -> LifecycleFenceResult:
        """Return current only after an exact primary-store comparison."""

        try:
            async with asyncio.timeout(self._timeout_seconds):
                current = await self._store.check_fence(fence)
        except (
            TimeoutError,
            AuthorizationLifecycleError,
            StandingAuthorizationStoreError,
        ):
            return LifecycleFenceResult(
                current=False,
                reason=LifecycleFenceReason.STORE_UNAVAILABLE,
            )
        return LifecycleFenceResult(
            current=current,
            reason=(LifecycleFenceReason.CURRENT if current else LifecycleFenceReason.STALE),
        )


__all__ = [
    "LifecycleFenceReason",
    "LifecycleFenceResult",
    "StandingAuthorizationFenceGuard",
]
