"""Provider-neutral atomic persistence boundary for A3-E lifecycle state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.standing_authority.lifecycle import (
        AuthorizationLifecycleCommand,
        AuthorizationLifecycleWriteResult,
        AuthorizationRevision,
        AuthorizationSnapshot,
        AuthorizationTransition,
        LifecycleFence,
    )


class StandingAuthorizationStoreError(RuntimeError):
    """Bounded persistence failure that a dispatch fence must treat as stale."""


@runtime_checkable
class StandingAuthorizationLifecycleStore(Protocol):
    """Persist one complete lifecycle mutation or none of it."""

    async def apply(
        self,
        command: AuthorizationLifecycleCommand,
    ) -> AuthorizationLifecycleWriteResult:
        """Atomically commit revision, transition, snapshot, fence, and audit."""

        ...

    async def read_revision(self, revision_id: str) -> AuthorizationRevision | None: ...

    async def read_transitions(
        self,
        family_id: str,
    ) -> tuple[AuthorizationTransition, ...]: ...

    async def read_snapshot(self, family_id: str) -> AuthorizationSnapshot | None:
        """Read the primary projection or fail if history exists without it."""

        ...

    async def rebuild_snapshot(self, family_id: str) -> AuthorizationSnapshot | None:
        """Validate complete history and replace only the derived projection."""

        ...

    async def check_fence(self, fence: LifecycleFence) -> bool:
        """Compare an exact fence against the authoritative primary store."""

        ...


__all__ = [
    "StandingAuthorizationLifecycleStore",
    "StandingAuthorizationStoreError",
]
