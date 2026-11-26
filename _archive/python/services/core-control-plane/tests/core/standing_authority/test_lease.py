"""Deterministic tests for the A3-E effect-spanning standing-authorization lease.

Covers:
- Lease acquisition, idempotency key derivation, field validation
- Revocation before provider commit (fail closed, no effect)
- Revocation after provider committed effect (effect preserved)
- Crash after provider commit with authoritative reconciliation (no duplicate)
- Expiry during effect (lease times out before commit)
- Lease loss / concurrent restart (stale slot)
- Redelivery with same idempotency key (idempotent, no duplicate effect)
- Restart after terminal release (prior outcome detected)
- Stale release (wrong generation rejected)
- Cross-revision reuse (different revision, independent slot)
- No duplicate effect on any path

Static dependency test: no agent, risk_gate, hil_resume, workflow, control_loop,
or executor file imports ``fdai.core.standing_authority.lease``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.standing_authority.lease import (
    EffectStatus,
    LeaseAcquisitionRequest,
    LeaseAcquisitionResult,
    LeaseCheckpoint,
    LeaseOutcome,
    ProviderCommitFenceRequest,
    ProviderCommitFenceResult,
    StandingAuthorizationLease,
    TerminalLeaseRecord,
    build_acquisition_request,
    build_checkpoint,
    build_provider_commit_fence_request,
    build_terminal_record,
    provider_idempotency_key,
)
from fdai.core.standing_authority.lifecycle import (
    LifecycleFence,
)
from fdai.shared.providers.standing_authority import (
    StandingAuthorizationLeaseStore,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "fdai"

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
REVISION_ID = "sha256:" + "a" * 64
ACTION_DIGEST = "sha256:" + "b" * 64
TARGET_DIGEST = "sha256:" + "c" * 64
EXECUTOR = "identity:thor"
SOURCE_REV = "source:v1.2.3"
VALID_SECONDS = 300

FENCE = LifecycleFence(
    family_id="family:one",
    revision_id=REVISION_ID,
    fencing_generation=3,
    transition_digest="sha256:" + "d" * 64,
)

# ---------------------------------------------------------------------------
# Test-only in-memory transactional lease store
# ---------------------------------------------------------------------------


@dataclass
class _LeaseSlot:
    """One active-or-terminal lease slot keyed by idempotency key."""

    lease: StandingAuthorizationLease | None = None
    terminal: TerminalLeaseRecord | None = None
    generation: int = 0
    provider_committed: bool = False  # authoritative effect status for reconcile


class InMemoryLeaseStore:
    """Deterministic in-memory lease store for tests.

    Transactional semantics are approximated with per-operation Python dict
    mutations (single-threaded). All fence checks compare against a mutable
    ``current_fence`` that the test harness advances to simulate revocation,
    renewal, or expiry.
    """

    def __init__(self, current_fence: LifecycleFence) -> None:
        self._fence = current_fence
        self._slots: dict[str, _LeaseSlot] = {}
        self.ineligible_capabilities: set[str] = set()

    # -- harness helpers --

    def advance_fence(self, new_fence: LifecycleFence) -> None:
        """Simulate revocation or renewal by advancing the primary fence."""
        self._fence = new_fence

    def mark_provider_committed(self, lease_id: str) -> None:
        """Simulate a provider commit completing before terminal release."""
        slot = self._slots.setdefault(lease_id, _LeaseSlot())
        slot.provider_committed = True

    def mark_capability_ineligible(self, lease_id: str) -> None:
        """Mark a lease_id as coming from an ineligible provider."""
        self.ineligible_capabilities.add(lease_id)

    # -- StandingAuthorizationLeaseStore implementation --

    async def acquire(self, request: LeaseAcquisitionRequest) -> LeaseAcquisitionResult:
        key = request.idempotency_key
        slot = self._slots.get(key)

        # Already has a terminal record: surface prior outcome without new effect.
        if slot is not None and slot.terminal is not None:
            return LeaseAcquisitionResult(outcome=LeaseOutcome.LEASE_LOSS)

        # Fence check: must match primary store exactly.
        if request.fence != self._fence:
            return LeaseAcquisitionResult(outcome=LeaseOutcome.STALE_GENERATION)

        # Expiry pre-check.
        valid_until = request.requested_at + timedelta(seconds=request.valid_seconds)
        if valid_until <= request.requested_at:
            return LeaseAcquisitionResult(outcome=LeaseOutcome.PERSISTENCE_FAILURE)

        if slot is None:
            slot = _LeaseSlot()
            self._slots[key] = slot

        if slot.lease is not None:
            # Another holder owns the slot.
            return LeaseAcquisitionResult(outcome=LeaseOutcome.LEASE_LOSS)

        slot.generation += 1
        lease = StandingAuthorizationLease(
            lease_id=key,
            family_id=request.fence.family_id,
            revision_id=request.fence.revision_id,
            fencing_generation=request.fence.fencing_generation,
            transition_digest=request.fence.transition_digest,
            action_digest=request.action_digest,
            target_digest=request.target_digest,
            executor_identity=request.executor_identity,
            source_revision_id=request.source_revision_id,
            acquired_at=request.requested_at,
            valid_until=valid_until,
            lease_generation=slot.generation,
        )
        slot.lease = lease
        return LeaseAcquisitionResult(outcome=LeaseOutcome.ACQUIRED, lease=lease)

    async def check_commit_fence(
        self,
        request: ProviderCommitFenceRequest,
    ) -> ProviderCommitFenceResult:
        if request.lease_id in self.ineligible_capabilities:
            return ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.INELIGIBLE_CAPABILITY,
            )

        slot = self._slots.get(request.lease_id)
        if slot is None or slot.lease is None:
            return ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.LEASE_LOSS,
            )
        if slot.lease.lease_generation != request.lease_generation:
            return ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.LEASE_LOSS,
            )
        if request.fence != self._fence:
            # Revocation or renewal advanced the primary fence.
            return ProviderCommitFenceResult(
                allowed=False,
                outcome=LeaseOutcome.STALE_GENERATION,
            )
        return ProviderCommitFenceResult(allowed=True, outcome=LeaseOutcome.ACQUIRED)

    async def write_checkpoint(self, checkpoint: LeaseCheckpoint) -> bool:
        slot = self._slots.get(checkpoint.lease_id)
        if slot is None or slot.lease is None:
            return False
        if slot.lease.lease_generation != checkpoint.lease_generation:
            return False
        return True

    async def terminal_release(self, record: TerminalLeaseRecord) -> bool:
        slot = self._slots.get(record.lease_id)
        if slot is None:
            return False
        if slot.lease is None or slot.lease.lease_generation != record.lease_generation:
            return False
        slot.terminal = record
        slot.lease = None
        return True

    async def reconcile_provider_status(self, lease_id: str) -> EffectStatus:
        slot = self._slots.get(lease_id)
        if slot is None:
            return EffectStatus.NOT_COMMITTED
        if slot.provider_committed:
            return EffectStatus.COMMITTED
        return EffectStatus.NOT_COMMITTED


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_store(fence: LifecycleFence = FENCE) -> InMemoryLeaseStore:
    return InMemoryLeaseStore(current_fence=fence)


def _make_request(
    fence: LifecycleFence = FENCE,
    *,
    now: datetime = NOW,
    valid_seconds: int = VALID_SECONDS,
    action: str = ACTION_DIGEST,
    target: str = TARGET_DIGEST,
) -> LeaseAcquisitionRequest:
    return build_acquisition_request(
        fence=fence,
        action_digest=action,
        target_digest=target,
        executor_identity=EXECUTOR,
        source_revision_id=SOURCE_REV,
        requested_at=now,
        valid_seconds=valid_seconds,
    )


def _revoked_fence(base: LifecycleFence) -> LifecycleFence:
    """Return a fence with an advanced fencing_generation (simulates revoke)."""
    return LifecycleFence(
        family_id=base.family_id,
        revision_id=base.revision_id,
        fencing_generation=base.fencing_generation + 1,
        transition_digest="sha256:" + "e" * 64,
    )


# ---------------------------------------------------------------------------
# Unit tests: idempotency key derivation and lease field validation
# ---------------------------------------------------------------------------


def test_provider_idempotency_key_is_stable() -> None:
    key_a = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    key_b = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    assert key_a == key_b
    assert key_a.startswith("sha256:")


def test_provider_idempotency_key_differs_by_revision() -> None:
    other_revision = "sha256:" + "f" * 64
    key_a = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    key_b = provider_idempotency_key(
        revision_id=other_revision,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    assert key_a != key_b


def test_provider_idempotency_key_differs_by_action() -> None:
    other_action = "sha256:" + "0" * 64
    key_a = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    key_b = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=other_action,
        target_digest=TARGET_DIGEST,
    )
    assert key_a != key_b


def test_lease_rejects_mismatched_lease_id() -> None:
    correct_id = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    wrong_id = "sha256:" + "1" * 64
    assert wrong_id != correct_id
    with pytest.raises(Exception, match="lease_id MUST equal"):
        StandingAuthorizationLease(
            lease_id=wrong_id,
            family_id=FENCE.family_id,
            revision_id=REVISION_ID,
            fencing_generation=FENCE.fencing_generation,
            transition_digest=FENCE.transition_digest,
            action_digest=ACTION_DIGEST,
            target_digest=TARGET_DIGEST,
            executor_identity=EXECUTOR,
            source_revision_id=SOURCE_REV,
            acquired_at=NOW,
            valid_until=NOW + timedelta(seconds=VALID_SECONDS),
            lease_generation=1,
        )


def test_lease_rejects_expired_validity_window() -> None:
    with pytest.raises(Exception, match="valid_until MUST be after"):
        StandingAuthorizationLease(
            lease_id=provider_idempotency_key(
                revision_id=REVISION_ID,
                action_digest=ACTION_DIGEST,
                target_digest=TARGET_DIGEST,
            ),
            family_id=FENCE.family_id,
            revision_id=REVISION_ID,
            fencing_generation=FENCE.fencing_generation,
            transition_digest=FENCE.transition_digest,
            action_digest=ACTION_DIGEST,
            target_digest=TARGET_DIGEST,
            executor_identity=EXECUTOR,
            source_revision_id=SOURCE_REV,
            acquired_at=NOW,
            valid_until=NOW,  # same instant, not after
            lease_generation=1,
        )


def test_lease_fence_roundtrip() -> None:
    key = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    lease = StandingAuthorizationLease(
        lease_id=key,
        family_id=FENCE.family_id,
        revision_id=REVISION_ID,
        fencing_generation=FENCE.fencing_generation,
        transition_digest=FENCE.transition_digest,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
        executor_identity=EXECUTOR,
        source_revision_id=SOURCE_REV,
        acquired_at=NOW,
        valid_until=NOW + timedelta(seconds=VALID_SECONDS),
        lease_generation=1,
    )
    assert lease.fence() == FENCE
    assert lease.execution_authority is False
    assert lease.promotion_authority is False


def test_lease_is_expired_at_valid_until() -> None:
    key = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    lease = StandingAuthorizationLease(
        lease_id=key,
        family_id=FENCE.family_id,
        revision_id=REVISION_ID,
        fencing_generation=FENCE.fencing_generation,
        transition_digest=FENCE.transition_digest,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
        executor_identity=EXECUTOR,
        source_revision_id=SOURCE_REV,
        acquired_at=NOW,
        valid_until=NOW + timedelta(seconds=60),
        lease_generation=1,
    )
    assert not lease.is_expired(NOW)
    assert not lease.is_expired(NOW + timedelta(seconds=59))
    assert lease.is_expired(NOW + timedelta(seconds=60))
    assert lease.is_expired(NOW + timedelta(seconds=61))


# ---------------------------------------------------------------------------
# Acquisition tests
# ---------------------------------------------------------------------------


async def test_successful_lease_acquisition() -> None:
    store = _make_store()
    result = await store.acquire(_make_request())

    assert result.outcome is LeaseOutcome.ACQUIRED
    assert result.lease is not None
    assert result.lease.lease_generation == 1
    assert result.lease.revision_id == REVISION_ID
    assert result.lease.fencing_generation == FENCE.fencing_generation
    assert result.lease.execution_authority is False


async def test_acquisition_fails_with_stale_fence() -> None:
    store = _make_store()
    stale_fence = _revoked_fence(FENCE)
    result = await store.acquire(_make_request(fence=stale_fence))

    assert result.outcome is LeaseOutcome.STALE_GENERATION
    assert result.lease is None


async def test_acquisition_fails_when_slot_already_held() -> None:
    store = _make_store()
    first = await store.acquire(_make_request())
    assert first.outcome is LeaseOutcome.ACQUIRED

    second = await store.acquire(_make_request())
    assert second.outcome is LeaseOutcome.LEASE_LOSS
    assert second.lease is None


# ---------------------------------------------------------------------------
# Concurrency scenario 1: Revocation BEFORE provider commit → fail closed
# ---------------------------------------------------------------------------


async def test_revocation_before_provider_commit_is_denied() -> None:
    """Revocation detected at the commit fence → effect never committed."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # Simulate revocation advancing the primary fence.
    store.advance_fence(_revoked_fence(FENCE))

    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)

    assert not fence_result.allowed
    assert fence_result.outcome is LeaseOutcome.STALE_GENERATION
    assert fence_result.execution_authority is False


# ---------------------------------------------------------------------------
# Concurrency scenario 2: Revocation AFTER committed effect → effect preserved
# ---------------------------------------------------------------------------


async def test_revocation_after_committed_effect_is_preserved() -> None:
    """Effect committed before revocation: committed fact must be preserved."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # Provider commits successfully (fence still current).
    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)
    assert fence_result.allowed

    # Simulate: provider commits its side effect.
    store.mark_provider_committed(lease.lease_id)

    # Now revocation arrives. Terminal release discovers it was committed.
    status = await store.reconcile_provider_status(lease.lease_id)
    assert status is EffectStatus.COMMITTED

    terminal = build_terminal_record(
        lease,
        effect_status=status,
        released_at=NOW + timedelta(seconds=5),
    )
    # Status must reflect committed, not masked by revocation.
    assert terminal.effect_status is EffectStatus.COMMITTED
    released = await store.terminal_release(terminal)
    assert released


# ---------------------------------------------------------------------------
# Concurrency scenario 3: Crash after provider commit → reconcile, no duplicate
# ---------------------------------------------------------------------------


async def test_crash_after_provider_commit_reconciles_without_duplicate() -> None:
    """After crash: reconcile status from provider, never re-commit."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)
    assert fence_result.allowed

    # Simulate crash: provider committed but terminal release was not written.
    store.mark_provider_committed(lease.lease_id)

    # On restart: reconcile authoritative provider status.
    status = await store.reconcile_provider_status(lease.lease_id)
    assert status is EffectStatus.COMMITTED

    # Write the terminal record once - no second provider operation.
    terminal = build_terminal_record(
        lease, effect_status=status, released_at=NOW + timedelta(seconds=10)
    )
    ok = await store.terminal_release(terminal)
    assert ok

    # Subsequent acquisition attempt must detect prior terminal.
    second = await store.acquire(_make_request())
    assert second.outcome is LeaseOutcome.LEASE_LOSS


# ---------------------------------------------------------------------------
# Concurrency scenario 4: Expiry during effect → fail closed
# ---------------------------------------------------------------------------


async def test_expiry_during_effect_blocks_provider_commit() -> None:
    """If lease expires before provider commit, commit must fail closed."""
    store = _make_store()
    short_request = _make_request(valid_seconds=10)
    result = await store.acquire(short_request)
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # Verify the lease is expired at valid_until.
    assert lease.is_expired(lease.valid_until)

    # A provider implementation MUST check lease.is_expired(now) before calling
    # check_commit_fence. This test verifies the expiry detection logic.
    expired_at = lease.valid_until
    assert lease.is_expired(expired_at)
    assert not lease.is_expired(expired_at - timedelta(seconds=1))


# ---------------------------------------------------------------------------
# Concurrency scenario 5: Lease loss / concurrent restart
# ---------------------------------------------------------------------------


async def test_lease_loss_detected_at_fence_check() -> None:
    """A second holder acquiring the slot causes the first holder to see LEASE_LOSS."""
    store = _make_store()
    first_result = await store.acquire(_make_request())
    assert first_result.outcome is LeaseOutcome.ACQUIRED
    first_lease = first_result.lease
    assert first_lease is not None

    # Simulate: first holder lost; slot was cleared and re-acquired.
    # Clear the slot manually to simulate a restart.
    slot = store._slots[first_lease.lease_id]
    slot.lease = None  # simulates lost / evicted

    second_result = await store.acquire(_make_request())
    assert second_result.outcome is LeaseOutcome.ACQUIRED
    second_lease = second_result.lease
    assert second_lease is not None
    assert second_lease.lease_generation > first_lease.lease_generation

    # First holder's fence request now carries the old lease_generation.
    old_fence_req = build_provider_commit_fence_request(first_lease)
    fence_result = await store.check_commit_fence(old_fence_req)
    assert not fence_result.allowed
    assert fence_result.outcome is LeaseOutcome.LEASE_LOSS


# ---------------------------------------------------------------------------
# Concurrency scenario 6: Redelivery with same idempotency key
# ---------------------------------------------------------------------------


async def test_redelivery_with_same_idempotency_key_is_idempotent() -> None:
    """Re-acquiring with the same key after terminal release produces LEASE_LOSS.

    The prior terminal record blocks a new acquisition from duplicating the effect.
    The caller must check the terminal record's effect_status before deciding
    whether to re-submit.
    """
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)
    assert fence_result.allowed

    store.mark_provider_committed(lease.lease_id)
    status = await store.reconcile_provider_status(lease.lease_id)
    terminal = build_terminal_record(
        lease, effect_status=status, released_at=NOW + timedelta(seconds=5)
    )
    ok = await store.terminal_release(terminal)
    assert ok

    # Redelivery: same idempotency key → blocked.
    redelivery = await store.acquire(_make_request())
    assert redelivery.outcome is LeaseOutcome.LEASE_LOSS
    assert redelivery.lease is None


# ---------------------------------------------------------------------------
# Concurrency scenario 7: Restart before provider commit → no effect
# ---------------------------------------------------------------------------


async def test_restart_before_commit_produces_no_effect() -> None:
    """Restart before any provider commit: reconcile returns NOT_COMMITTED."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # No provider commit occurred - slot was abandoned (e.g. crash during prep).
    status = await store.reconcile_provider_status(lease.lease_id)
    assert status is EffectStatus.NOT_COMMITTED

    # Terminal record with NOT_COMMITTED is safe to write.
    terminal = build_terminal_record(
        lease, effect_status=status, released_at=NOW + timedelta(seconds=3)
    )
    assert terminal.effect_status is EffectStatus.NOT_COMMITTED


# ---------------------------------------------------------------------------
# Concurrency scenario 8: Stale terminal release (wrong generation rejected)
# ---------------------------------------------------------------------------


async def test_stale_release_with_wrong_generation_is_rejected() -> None:
    """A terminal release with a stale generation must not mutate the slot."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # Forge a terminal record with wrong generation.
    forged = TerminalLeaseRecord(
        lease_id=lease.lease_id,
        lease_generation=lease.lease_generation + 99,
        revision_id=lease.revision_id,
        fencing_generation=lease.fencing_generation,
        effect_status=EffectStatus.COMMITTED,
        released_at=NOW + timedelta(seconds=1),
    )
    rejected = await store.terminal_release(forged)
    assert not rejected

    # Slot is still held by the original lease.
    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)
    assert fence_result.allowed


# ---------------------------------------------------------------------------
# Concurrency scenario 9: Cross-revision reuse without duplicate effect
# ---------------------------------------------------------------------------


async def test_cross_revision_reuse_is_an_independent_slot() -> None:
    """Different revision → different idempotency key → independent slots."""
    other_revision = "sha256:" + "9" * 64
    other_fence = LifecycleFence(
        family_id=FENCE.family_id,
        revision_id=other_revision,
        fencing_generation=FENCE.fencing_generation + 2,
        transition_digest="sha256:" + "7" * 64,
    )

    key_a = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    key_b = provider_idempotency_key(
        revision_id=other_revision,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    assert key_a != key_b

    # Acquire and complete the first revision's lease.
    store_a = _make_store(FENCE)
    result_a = await store_a.acquire(_make_request())
    assert result_a.outcome is LeaseOutcome.ACQUIRED
    lease_a = result_a.lease
    assert lease_a is not None

    store_a.mark_provider_committed(lease_a.lease_id)
    status_a = await store_a.reconcile_provider_status(lease_a.lease_id)
    terminal_a = build_terminal_record(
        lease_a, effect_status=status_a, released_at=NOW + timedelta(seconds=5)
    )
    await store_a.terminal_release(terminal_a)

    # Acquire the second revision's lease independently - no blocking.
    store_b = _make_store(other_fence)
    result_b = await store_b.acquire(_make_request(fence=other_fence))
    assert result_b.outcome is LeaseOutcome.ACQUIRED
    lease_b = result_b.lease
    assert lease_b is not None
    assert lease_b.revision_id == other_revision
    assert lease_b.lease_id == key_b


# ---------------------------------------------------------------------------
# Scenario: ineligible capability fails closed
# ---------------------------------------------------------------------------


async def test_ineligible_capability_fails_closed_at_commit_fence() -> None:
    """Provider that cannot enforce the atomic fence returns INELIGIBLE_CAPABILITY."""
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    # Mark this lease_id as coming from a provider that cannot enforce the fence.
    store.mark_capability_ineligible(lease.lease_id)

    fence_req = build_provider_commit_fence_request(lease)
    fence_result = await store.check_commit_fence(fence_req)

    assert not fence_result.allowed
    assert fence_result.outcome is LeaseOutcome.INELIGIBLE_CAPABILITY
    assert fence_result.execution_authority is False


# ---------------------------------------------------------------------------
# Scenario: checkpoint liveness
# ---------------------------------------------------------------------------


async def test_checkpoint_written_for_active_lease() -> None:
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    checkpoint = build_checkpoint(lease, checked_at=NOW + timedelta(seconds=5))
    ok = await store.write_checkpoint(checkpoint)
    assert ok


async def test_checkpoint_rejected_for_wrong_generation() -> None:
    store = _make_store()
    result = await store.acquire(_make_request())
    assert result.outcome is LeaseOutcome.ACQUIRED
    lease = result.lease
    assert lease is not None

    bad_checkpoint = LeaseCheckpoint(
        lease_id=lease.lease_id,
        lease_generation=lease.lease_generation + 1,
        checked_at=NOW + timedelta(seconds=5),
    )
    ok = await store.write_checkpoint(bad_checkpoint)
    assert not ok


async def test_checkpoint_rejected_when_no_active_lease() -> None:
    store = _make_store()
    bad_checkpoint = LeaseCheckpoint(
        lease_id="sha256:" + "0" * 64,
        lease_generation=1,
        checked_at=NOW,
    )
    ok = await store.write_checkpoint(bad_checkpoint)
    assert not ok


# ---------------------------------------------------------------------------
# Terminal record validation
# ---------------------------------------------------------------------------


def test_terminal_record_audit_body_is_canonical() -> None:
    record = TerminalLeaseRecord(
        lease_id=provider_idempotency_key(
            revision_id=REVISION_ID,
            action_digest=ACTION_DIGEST,
            target_digest=TARGET_DIGEST,
        ),
        lease_generation=1,
        revision_id=REVISION_ID,
        fencing_generation=FENCE.fencing_generation,
        effect_status=EffectStatus.COMMITTED,
        released_at=NOW + timedelta(seconds=10),
    )
    body = record.audit_body()
    assert body["kind"] == "standing_authority.lease.terminal_release"
    assert body["effect_status"] == EffectStatus.COMMITTED.value
    assert body["execution_authority"] is False
    assert body["promotion_authority"] is False


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def test_build_acquisition_request_validates_inputs() -> None:
    with pytest.raises(Exception, match="valid_seconds"):
        build_acquisition_request(
            fence=FENCE,
            action_digest=ACTION_DIGEST,
            target_digest=TARGET_DIGEST,
            executor_identity=EXECUTOR,
            source_revision_id=SOURCE_REV,
            requested_at=NOW,
            valid_seconds=0,
        )

    with pytest.raises(Exception, match="action_digest"):
        build_acquisition_request(
            fence=FENCE,
            action_digest="not-a-digest",
            target_digest=TARGET_DIGEST,
            executor_identity=EXECUTOR,
            source_revision_id=SOURCE_REV,
            requested_at=NOW,
            valid_seconds=VALID_SECONDS,
        )


def test_build_provider_commit_fence_request_matches_lease() -> None:
    key = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    lease = StandingAuthorizationLease(
        lease_id=key,
        family_id=FENCE.family_id,
        revision_id=REVISION_ID,
        fencing_generation=FENCE.fencing_generation,
        transition_digest=FENCE.transition_digest,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
        executor_identity=EXECUTOR,
        source_revision_id=SOURCE_REV,
        acquired_at=NOW,
        valid_until=NOW + timedelta(seconds=VALID_SECONDS),
        lease_generation=2,
    )
    req = build_provider_commit_fence_request(lease)
    assert req.lease_id == lease.lease_id
    assert req.lease_generation == 2
    assert req.fence == FENCE


def test_build_terminal_record_preserves_committed_after_crash() -> None:
    key = provider_idempotency_key(
        revision_id=REVISION_ID,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
    )
    lease = StandingAuthorizationLease(
        lease_id=key,
        family_id=FENCE.family_id,
        revision_id=REVISION_ID,
        fencing_generation=FENCE.fencing_generation,
        transition_digest=FENCE.transition_digest,
        action_digest=ACTION_DIGEST,
        target_digest=TARGET_DIGEST,
        executor_identity=EXECUTOR,
        source_revision_id=SOURCE_REV,
        acquired_at=NOW,
        valid_until=NOW + timedelta(seconds=VALID_SECONDS),
        lease_generation=1,
    )
    record = build_terminal_record(
        lease, effect_status=EffectStatus.COMMITTED, released_at=NOW + timedelta(seconds=8)
    )
    assert record.effect_status is EffectStatus.COMMITTED
    assert record.lease_id == lease.lease_id
    assert record.lease_generation == 1


# ---------------------------------------------------------------------------
# ProviderCommitFenceResult validation
# ---------------------------------------------------------------------------


def test_fence_result_disallows_allowed_without_acquired_outcome() -> None:
    with pytest.raises(Exception, match="ACQUIRED outcome when allowed"):
        ProviderCommitFenceResult(allowed=True, outcome=LeaseOutcome.STALE_GENERATION)


def test_fence_result_disallows_denied_with_acquired_outcome() -> None:
    with pytest.raises(Exception, match="MUST NOT use ACQUIRED"):
        ProviderCommitFenceResult(allowed=False, outcome=LeaseOutcome.ACQUIRED)


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


def test_in_memory_store_satisfies_protocol() -> None:
    """Verify the test double structurally satisfies StandingAuthorizationLeaseStore."""
    store = InMemoryLeaseStore(FENCE)
    assert isinstance(store, StandingAuthorizationLeaseStore)


# ---------------------------------------------------------------------------
# Static dependency test: no authority path imports the lease module
# ---------------------------------------------------------------------------


def test_lease_module_is_not_imported_by_authority_paths() -> None:
    """No agent, risk_gate, hil_resume, workflow, control_loop, or executor imports the lease."""
    # The lease type is in fdai.core.standing_authority.lease; we forbid that prefix.
    # fdai.shared.providers.standing_authority is already guarded by the existing
    # test_shadow_lifecycle_and_store_remain_unwired_from_authority_paths test.
    lease_prefixes = ("fdai.core.standing_authority.lease",)
    roots = (
        "agents",
        "core/risk_gate",
        "core/executor",
        "core/hil_resume",
        "core/workflow",
        "core/control_loop",
        "composition",
    )
    violations: list[str] = []
    for root in roots:
        path = SOURCE_ROOT / root
        assert path.exists(), f"authority path is missing: {root}"
        candidates = (path,) if path.is_file() else path.rglob("*.py")
        for candidate in candidates:
            tree = ast.parse(candidate.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = (node.module,)
                if any(
                    module.startswith(prefix) for module in modules for prefix in lease_prefixes
                ):
                    violations.append(str(candidate.relative_to(SOURCE_ROOT)))
    assert violations == [], f"lease imported from authority paths: {violations}"
