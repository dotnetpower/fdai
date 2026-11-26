"""ResourceLockManager - per-resource serialization invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fdai.core.executor.lock import ResourceLockManager
from fdai.shared.providers.resource_lock import (
    MAX_LOCK_ASSESSMENT_TTL,
    LockOwnershipRejectionReason,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
)

_NOW = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
_SOURCE_REVISION = "commit:" + "a" * 40


def _request() -> ResourceLockAcquisitionRequest:
    return ResourceLockAcquisitionRequest.create(
        target_ref="resource/example",
        action_digest="sha256:" + "1" * 64,
        attempt=1,
        producer_id="fdai.core.executor",
        producer_version="1.0.0",
        source_revision=_SOURCE_REVISION,
    )


@pytest.mark.asyncio
async def test_locks_are_created_lazily_per_resource() -> None:
    lock = ResourceLockManager()
    assert lock.snapshot() == {}

    async with lock.acquire("rid-a"):
        assert lock.snapshot() == {"rid-a": True}
    # Refcount hits zero on exit, so the entry is evicted (no unbounded
    # growth over many distinct resource ids).
    assert lock.snapshot() == {}


@pytest.mark.asyncio
async def test_concurrent_actions_on_one_resource_are_serialized() -> None:
    """Two tasks racing on the same resource_id MUST NOT interleave."""
    lock = ResourceLockManager()
    order: list[str] = []

    async def worker(name: str, delay: float) -> None:
        async with lock.acquire("shared"):
            order.append(f"{name}-in")
            await asyncio.sleep(delay)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a", 0.02), worker("b", 0.0))
    # Whichever grabbed the lock first MUST fully exit before the other enters.
    assert order in (
        ["a-in", "a-out", "b-in", "b-out"],
        ["b-in", "b-out", "a-in", "a-out"],
    )


@pytest.mark.asyncio
async def test_different_resources_run_in_parallel() -> None:
    lock = ResourceLockManager()
    order: list[str] = []

    async def worker(name: str, resource: str) -> None:
        async with lock.acquire(resource):
            order.append(f"{name}-in")
            await asyncio.sleep(0.02)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a", "res-a"), worker("b", "res-b"))
    # Interleaving allowed on distinct resources.
    assert order[0].endswith("-in")
    assert order[1].endswith("-in")


@pytest.mark.asyncio
async def test_snapshot_reflects_current_locked_state() -> None:
    lock = ResourceLockManager()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        async with lock.acquire("held"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold())
    await entered.wait()
    assert lock.snapshot() == {"held": True}
    release.set()
    await task
    # Evicted once the holder releases (refcount zero).
    assert lock.snapshot() == {}


@pytest.mark.asyncio
async def test_local_evidenced_lock_emits_current_no_authority_assessment() -> None:
    lock = ResourceLockManager(
        clock=lambda: _NOW,
        acquisition_id_factory=lambda: "private-owner-token",
    )
    request = _request()

    async with lock.acquire_evidenced(request) as held:
        assessment = await held.assess_ownership()

        assert held.acquisition_request is request
        assert held.acquisition_receipt.request_digest == request.request_digest
        assert held.acquisition_receipt.trust_anchor_id == "fdai:local-test-only"
        assert "private-owner-token" not in repr(held.acquisition_receipt)
        assert assessment.eligible is True
        assert assessment.execution_authority is False
        assert assessment.valid_until - assessment.evaluated_at == MAX_LOCK_ASSESSMENT_TTL

    with pytest.raises(RuntimeError, match="no longer active"):
        held.require_active()
    assert held.release_receipt is not None
    assert held.release_receipt.state is ResourceLockReleaseState.RELEASED
    assert held.release_receipt.execution_authority is False
    assert held.release_receipt.effect_verified is False
    inactive = await held.assess_ownership()
    assert inactive.eligible is False
    assert set(inactive.rejection_reasons) == {
        LockOwnershipRejectionReason.LOCK_LOST,
        LockOwnershipRejectionReason.SESSION_MISMATCH,
    }


@pytest.mark.asyncio
async def test_old_local_handle_stays_ineligible_during_reacquisition() -> None:
    lock = ResourceLockManager(
        clock=lambda: _NOW,
        acquisition_id_factory=lambda: "deterministic-owner",
    )
    request = _request()

    async with lock.acquire_evidenced(request) as first:
        first_receipt_digest = first.acquisition_receipt.receipt_digest

    async with lock.acquire_evidenced(request) as second:
        old_assessment = await first.assess_ownership()
        current_assessment = await second.assess_ownership()

        assert old_assessment.eligible is False
        assert current_assessment.eligible is True
        assert second.acquisition_receipt.receipt_digest != first_receipt_digest
        assert (
            second.acquisition_receipt.session_identity
            != first.acquisition_receipt.session_identity
        )


@pytest.mark.asyncio
async def test_local_evidenced_lock_deactivates_on_cancellation() -> None:
    lock = ResourceLockManager(
        clock=lambda: _NOW,
        acquisition_id_factory=lambda: "cancelled-owner",
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    captured = []

    async def hold() -> None:
        async with lock.acquire_evidenced(_request()) as held:
            captured.append(held)
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(captured) == 1
    with pytest.raises(RuntimeError, match="no longer active"):
        captured[0].require_active()
    assert (await captured[0].assess_ownership()).eligible is False
    assert lock.snapshot() == {}


@pytest.mark.asyncio
async def test_local_evidenced_lock_clears_activation_after_receipt_failure() -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("clock unavailable")
        return _NOW

    lock = ResourceLockManager(
        clock=clock,
        acquisition_id_factory=lambda: "recoverable-owner",
    )
    request = _request()

    with pytest.raises(RuntimeError, match="clock unavailable"):
        async with lock.acquire_evidenced(request):
            pytest.fail("receipt creation must fail before yielding")

    async with lock.acquire_evidenced(request) as held:
        assert (await held.assess_ownership()).eligible is True


@pytest.mark.asyncio
async def test_cancelled_holder_does_not_poison_queued_acquisition() -> None:
    lock = ResourceLockManager(
        clock=lambda: _NOW,
        acquisition_id_factory=lambda: "queued-owner",
    )
    request = _request()
    holder_entered = asyncio.Event()
    waiter_entered = asyncio.Event()
    hold = asyncio.Event()

    async def holder() -> None:
        async with lock.acquire_evidenced(request):
            holder_entered.set()
            await hold.wait()

    async def waiter() -> None:
        async with lock.acquire_evidenced(request) as held:
            assert (await held.assess_ownership()).eligible is True
            waiter_entered.set()

    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    holder_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder_task
    await waiter_task

    assert waiter_entered.is_set()
    assert lock.snapshot() == {}
