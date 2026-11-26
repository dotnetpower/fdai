"""Provider-neutral atomic persistence boundaries for A3-E lifecycle state and leases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.standing_authority.lease import (
        EffectStatus,
        LeaseAcquisitionRequest,
        LeaseAcquisitionResult,
        LeaseCheckpoint,
        ProviderCommitFenceRequest,
        ProviderCommitFenceResult,
        TerminalLeaseRecord,
    )
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


@runtime_checkable
class StandingAuthorizationLeaseStore(Protocol):
    """Provider-neutral persistence boundary for effect-spanning A3-E leases.

    Every method must fail closed: any uncertainty about current lease state or
    provider effect status must produce a fail-closed outcome, never a permissive
    default.

    This store is **inert**: nothing in the shipped runtime wires it. It remains
    unused until governed shadow evidence and an independent promotion review exist.
    """

    async def acquire(
        self,
        request: LeaseAcquisitionRequest,
    ) -> LeaseAcquisitionResult:
        """Atomically acquire a lease if the fence is still current.

        The implementation MUST:
        - Read the current lifecycle fence from the authoritative store.
        - Compare it exactly against ``request.fence``.
        - Assign a monotonically increasing ``lease_generation`` for the slot.
        - Fail closed with ``STALE_GENERATION`` when the fence generation advanced.
        - Fail closed with ``LEASE_LOSS`` when another holder owns the slot.
        - Fail closed with ``PERSISTENCE_FAILURE`` on any store error.
        """

        ...

    async def check_commit_fence(
        self,
        request: ProviderCommitFenceRequest,
    ) -> ProviderCommitFenceResult:
        """Validate current lease and fence atomically at provider-commit time.

        This is the core of the effect-spanning guarantee. The provider calls this
        method inside the same transaction (or two-phase commit) that records the
        provider operation. An ineligible capability that cannot enforce this
        boundary MUST return ``INELIGIBLE_CAPABILITY`` and never proceed.
        """

        ...

    async def write_checkpoint(
        self,
        checkpoint: LeaseCheckpoint,
    ) -> bool:
        """Write a liveness checkpoint for the active lease.

        Returns ``True`` on success. Returning ``False`` or raising
        ``StandingAuthorizationStoreError`` blocks the provider commit.
        """

        ...

    async def terminal_release(
        self,
        record: TerminalLeaseRecord,
    ) -> bool:
        """Persist the terminal release record.

        Must be called after provider commit (whether the effect succeeded or not).
        A crash before this call is reconciled via ``reconcile_provider_status``.
        Returns ``True`` on success.
        """

        ...

    async def reconcile_provider_status(
        self,
        lease_id: str,
    ) -> EffectStatus:
        """Query the authoritative provider operation status for reconciliation.

        Called when a crash occurred between provider commit and terminal release
        persistence. The result MUST come from an authoritative, independent source
        (not from local state). Returns ``EffectStatus.UNKNOWN`` when the status
        cannot be determined; callers MUST treat ``UNKNOWN`` as ``COMMITTED``.
        """

        ...


__all__ = [
    "StandingAuthorizationLeaseStore",
    "StandingAuthorizationLifecycleStore",
    "StandingAuthorizationStoreError",
]
