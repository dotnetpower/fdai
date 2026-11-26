"""Per-resource lock manager for the executor.

Multiple concurrent events may target the same resource - a rotate-secret
action and a right-size action on the same Container App, say. Applying
them in parallel would violate the ordering rule in
``architecture.instructions.md § Idempotency, Ordering, and Replay``:

> Events that mutate the same resource are serialized on a per-resource
> key; concurrent actions on one resource are mutually excluded.

Design
------

- One :class:`asyncio.Lock` per ``resource_id``, created lazily.
- This implementation stays in-process and is the local/single-replica
    default behind the ``ResourceLock`` seam. Scale-out composition injects
    ``PostgresAdvisoryResourceLock`` for cross-replica exclusion; the event
    bus resource partition key separately preserves per-resource ordering.
- The manager MUST be safe to reuse across concurrent tasks - the
  per-resource-id dictionary itself is guarded by an internal lock.
- Locks are held for the *duration of the action*; short critical
  sections keep the throughput acceptable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fdai_service_contracts.ontology_query import content_digest

from fdai.shared.providers.resource_lock import (
    MAX_LOCK_ASSESSMENT_TTL,
    HeldResourceLock,
    HeldResourceLockLifecycle,
    LiveLockOwnershipAssessment,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionReceipt,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)

_LOCAL_PROVIDER_ID = "fdai-in-memory-resource-lock"
_LOCAL_PROVIDER_VERSION = "1.0.0"
_LOCAL_VERIFIER_ID = "fdai-in-memory-lock-readback"
_LOCAL_TRUST_ANCHOR_ID = "fdai:local-test-only"


@dataclass
class _LockEntry:
    """A per-resource lock plus a refcount of interested callers."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refcount: int = 0
    active_acquisition_id: str | None = None


class _HeldLocalResourceLock:
    """One exact local acquisition that becomes inert on context exit."""

    def __init__(
        self,
        *,
        manager: ResourceLockManager,
        lock_key: str,
        entry: _LockEntry,
        acquisition_id: str,
        lifecycle: HeldResourceLockLifecycle,
    ) -> None:
        self._manager = manager
        self._lock_key = lock_key
        self._entry = entry
        self._acquisition_id = acquisition_id
        self._lifecycle = lifecycle
        self._release_receipt: ResourceLockReleaseReceipt | None = None

    @property
    def acquisition_request(self) -> ResourceLockAcquisitionRequest:
        return self._lifecycle.acquisition_request

    @property
    def acquisition_receipt(self) -> ResourceLockAcquisitionReceipt:
        return self._lifecycle.acquisition_receipt

    def require_active(self) -> None:
        self._lifecycle.require_active()

    @property
    def release_receipt(self) -> ResourceLockReleaseReceipt | None:
        return self._release_receipt

    def deactivate(self) -> None:
        self._lifecycle.deactivate()

    def record_release(self, released_at: datetime) -> None:
        if self._lifecycle.active:
            raise RuntimeError("local resource lock release recorded while active")
        self._release_receipt = ResourceLockReleaseReceipt.create(
            acquisition_receipt=self.acquisition_receipt,
            state=ResourceLockReleaseState.RELEASED,
            provider_attestation_digest=content_digest(
                {
                    "domain": "local-resource-lock-release",
                    "request_digest": self.acquisition_request.request_digest,
                    "owner_reference_digest": (self.acquisition_receipt.owner_token_digest),
                    "released_at": released_at.isoformat(),
                }
            ),
            observed_at=released_at,
            recorded_at=released_at,
        )

    async def assess_ownership(self) -> LiveLockOwnershipAssessment:
        evaluated_at = self._manager.clock()
        owns_acquisition = self._lifecycle.active and await self._manager._owns_acquisition(
            self._lock_key,
            self._entry,
            self._acquisition_id,
        )
        receipt = self.acquisition_receipt
        current_session_identity = receipt.session_identity if owns_acquisition else None
        rejection_reasons = () if owns_acquisition else (LockOwnershipRejectionReason.LOCK_LOST,)
        return LiveLockOwnershipAssessment.create(
            receipt,
            current_fencing_generation=None,
            current_session_identity=current_session_identity,
            verifier_id=_LOCAL_VERIFIER_ID,
            verifier_version=_LOCAL_PROVIDER_VERSION,
            trust_anchor_id=_LOCAL_TRUST_ANCHOR_ID,
            provider_attestation_digest=content_digest(
                {
                    "domain": "local-resource-lock-readback",
                    "request_digest": self.acquisition_request.request_digest,
                    "owner_reference_digest": receipt.owner_token_digest,
                    "owns_acquisition": owns_acquisition,
                    "evaluated_at": evaluated_at.isoformat(),
                }
            ),
            evaluated_at=evaluated_at,
            valid_until=evaluated_at + MAX_LOCK_ASSESSMENT_TTL,
            rejection_reasons=rejection_reasons,
        )


class ResourceLockManager:
    """Serialize actions per-resource in-process.

    Not persistent - a process restart forgets in-flight locks. That is
    acceptable because the audit log records every action; a replayed
    event acquires the lock and dedupes on ``idempotency_key`` before
    doing any work.
    """

    distributed = False
    production_eligible = False

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        acquisition_id_factory: Callable[[], str] | None = None,
    ) -> None:
        # resource_id -> (lock, refcount). The refcount tracks how many
        # callers currently hold or are waiting on the lock; the entry is
        # evicted once it drops to zero so the map cannot grow without
        # bound over a long-running process that touches many distinct
        # resource ids (a memory leak otherwise).
        self._locks: dict[str, _LockEntry] = {}
        self._registry_lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._acquisition_id_factory = acquisition_id_factory or (lambda: uuid4().hex)
        self._acquisition_sequence = 0

    def clock(self) -> datetime:
        """Return adapter-owned UTC time for acquisition and readback."""

        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("local resource lock clock MUST return an exact UTC datetime")
        return value

    async def _checkout(self, resource_id: str) -> _LockEntry:
        async with self._registry_lock:
            entry = self._locks.get(resource_id)
            if entry is None:
                entry = _LockEntry()
                self._locks[resource_id] = entry
            entry.refcount += 1
            return entry

    async def _checkin(self, resource_id: str) -> None:
        async with self._registry_lock:
            entry = self._locks.get(resource_id)
            if entry is None:
                return
            entry.refcount -= 1
            if entry.refcount <= 0:
                del self._locks[resource_id]

    async def _activate_acquisition(
        self,
        lock_key: str,
        entry: _LockEntry,
        acquisition_id: str,
    ) -> None:
        async with self._registry_lock:
            if self._locks.get(lock_key) is not entry or entry.active_acquisition_id is not None:
                raise RuntimeError("local resource lock acquisition state is inconsistent")
            entry.active_acquisition_id = acquisition_id

    async def _new_acquisition_id(self) -> str:
        raw_identity = self._acquisition_id_factory()
        if type(raw_identity) is not str or not raw_identity.strip():
            raise ValueError("local resource lock acquisition identity MUST be non-empty")
        async with self._registry_lock:
            self._acquisition_sequence += 1
            return f"{raw_identity}:{self._acquisition_sequence}"

    def _deactivate_acquisition(
        self,
        lock_key: str,
        entry: _LockEntry,
        acquisition_id: str,
    ) -> None:
        if self._locks.get(lock_key) is entry and entry.active_acquisition_id == acquisition_id:
            entry.active_acquisition_id = None

    async def _owns_acquisition(
        self,
        lock_key: str,
        entry: _LockEntry,
        acquisition_id: str,
    ) -> bool:
        async with self._registry_lock:
            return bool(
                self._locks.get(lock_key) is entry
                and entry.lock.locked()
                and entry.active_acquisition_id == acquisition_id
            )

    @asynccontextmanager
    async def acquire(self, resource_id: str) -> AsyncIterator[None]:
        """Hold the lock for ``resource_id`` until the ``async with`` exits."""
        # Reference is counted before the (possibly awaiting) acquire so a
        # concurrent release cannot evict the entry out from under a waiter.
        entry = await self._checkout(resource_id)
        try:
            async with entry.lock:
                yield
        finally:
            await self._checkin(resource_id)

    @asynccontextmanager
    async def acquire_evidenced(
        self,
        request: ResourceLockAcquisitionRequest,
    ) -> AsyncIterator[HeldResourceLock]:
        """Acquire one local test-only evidenced target lock."""

        if type(request) is not ResourceLockAcquisitionRequest:
            raise ValueError("local evidenced lock requires a canonical acquisition request")
        entry = await self._checkout(request.lock_key)
        handle: _HeldLocalResourceLock | None = None
        try:
            async with entry.lock:
                acquisition_id = await self._new_acquisition_id()
                await self._activate_acquisition(
                    request.lock_key,
                    entry,
                    acquisition_id,
                )
                lifecycle: HeldResourceLockLifecycle | None = None
                try:
                    acquired_at = self.clock()
                    owner_reference_digest = content_digest(
                        {
                            "domain": "local-resource-lock-owner",
                            "request_digest": request.request_digest,
                            "acquisition_id": acquisition_id,
                        }
                    )
                    session_identity = f"local:{owner_reference_digest}"
                    receipt = ResourceLockAcquisitionReceipt.create(
                        lock_key=request.lock_key,
                        target_digest=request.target_digest,
                        action_digest=request.action_digest,
                        attempt=request.attempt,
                        provider_id=_LOCAL_PROVIDER_ID,
                        provider_version=_LOCAL_PROVIDER_VERSION,
                        producer_id=request.producer_id,
                        producer_version=request.producer_version,
                        owner_token_digest=owner_reference_digest,
                        fencing_generation=None,
                        session_identity=session_identity,
                        provider_attestation_digest=content_digest(
                            {
                                "domain": "local-resource-lock-acquisition",
                                "request_digest": request.request_digest,
                                "owner_reference_digest": owner_reference_digest,
                                "acquired_at": acquired_at.isoformat(),
                            }
                        ),
                        trust_anchor_id=_LOCAL_TRUST_ANCHOR_ID,
                        acquired_at=acquired_at,
                        valid_until=None,
                        source_revision=request.source_revision,
                        request_digest=request.request_digest,
                    )
                    lifecycle = HeldResourceLockLifecycle(request, receipt)
                    handle = _HeldLocalResourceLock(
                        manager=self,
                        lock_key=request.lock_key,
                        entry=entry,
                        acquisition_id=acquisition_id,
                        lifecycle=lifecycle,
                    )
                    yield handle
                finally:
                    if lifecycle is not None:
                        lifecycle.deactivate()
                    self._deactivate_acquisition(
                        request.lock_key,
                        entry,
                        acquisition_id,
                    )
        finally:
            if handle is not None and handle.release_receipt is None:
                handle.record_release(self.clock())
            await self._checkin(request.lock_key)

    def snapshot(self) -> dict[str, bool]:
        """Test-only helper: which resource ids are currently locked."""
        return {rid: entry.lock.locked() for rid, entry in self._locks.items()}


__all__ = ["ResourceLockManager"]
