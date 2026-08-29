"""Durable MSCP pending-effect ownership tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationReason,
    EffectVerificationResult,
    EffectVerificationStatus,
    ExpectedEffect,
)
from fdai.core.mscp_profile.pending_effect_store import (
    PendingEffectConflictError,
    PendingEffectOwnershipError,
    PendingEffectStaleRevisionError,
    PendingEffectStatus,
    StateStorePendingEffectStore,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 29, 2, 0, tzinfo=UTC)
_VERIFIED = EffectVerificationResult(
    EffectVerificationStatus.VERIFIED,
    EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE,
)


def _expected(
    prediction_id: str = "prediction-one",
    *,
    deadline_minutes: int = 5,
) -> ExpectedEffect:
    return ExpectedEffect(
        prediction_id=prediction_id,
        target_ref="resource/example",
        metric="availability",
        acceptable_min=0.99,
        acceptable_max=1.0,
        predicted_at=_NOW,
        observation_deadline=_NOW + timedelta(minutes=deadline_minutes),
    )


async def _register(
    store: StateStorePendingEffectStore,
    expected: ExpectedEffect | None = None,
):
    return await store.register(
        expected or _expected(),
        action_type="example.restart",
        environment="non-production",
        observer_version="observer-v1",
    )


async def test_registered_effect_survives_store_recreation_and_replays_idempotently() -> None:
    state = InMemoryStateStore()
    first_store = StateStorePendingEffectStore(state)
    registered = await _register(first_store)

    restarted_store = StateStorePendingEffectStore(state)
    loaded = await restarted_store.get(registered.expected.prediction_id)
    replay = await _register(restarted_store)

    assert loaded == replay == registered
    assert registered.status is PendingEffectStatus.PENDING
    assert len(state.audit_entries) == 1


async def test_prediction_identity_reuse_with_changed_content_is_rejected() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    await _register(store)

    with pytest.raises(PendingEffectConflictError):
        await _register(
            store,
            replace(_expected(), acceptable_min=0.5),
        )


async def test_active_owner_and_stale_revision_are_rejected() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    registered = await _register(store)
    claimed = await store.claim(
        registered.expected.prediction_id,
        owner_id="observer-one",
        expected_revision=registered.revision,
        now=_NOW,
        lease_until=_NOW + timedelta(minutes=1),
    )

    with pytest.raises(PendingEffectOwnershipError, match="active owner"):
        await store.claim(
            registered.expected.prediction_id,
            owner_id="observer-two",
            expected_revision=claimed.revision,
            now=_NOW,
            lease_until=_NOW + timedelta(minutes=1),
        )
    with pytest.raises(PendingEffectStaleRevisionError):
        await store.claim(
            registered.expected.prediction_id,
            owner_id="observer-two",
            expected_revision=registered.revision,
            now=_NOW + timedelta(minutes=2),
            lease_until=_NOW + timedelta(minutes=3),
        )


async def test_effect_cannot_be_claimed_before_prediction_time() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    expected = replace(
        _expected(),
        predicted_at=_NOW + timedelta(minutes=1),
        observation_deadline=_NOW + timedelta(minutes=5),
    )
    registered = await _register(store, expected)

    with pytest.raises(PendingEffectOwnershipError, match="not ready"):
        await store.claim(
            registered.expected.prediction_id,
            owner_id="observer-one",
            expected_revision=registered.revision,
            now=_NOW,
            lease_until=_NOW + timedelta(minutes=2),
        )


async def test_expired_claim_advances_generation_and_fences_old_owner() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    registered = await _register(store)
    first = await store.claim(
        registered.expected.prediction_id,
        owner_id="observer-one",
        expected_revision=registered.revision,
        now=_NOW,
        lease_until=_NOW + timedelta(minutes=1),
    )
    second = await store.claim(
        registered.expected.prediction_id,
        owner_id="observer-two",
        expected_revision=first.revision,
        now=_NOW + timedelta(minutes=2),
        lease_until=_NOW + timedelta(minutes=3),
    )

    assert second.owner_generation == first.owner_generation + 1
    with pytest.raises(PendingEffectStaleRevisionError):
        await store.complete(
            registered.expected.prediction_id,
            owner_id="observer-one",
            owner_generation=first.owner_generation,
            expected_revision=first.revision,
            completed_at=_NOW + timedelta(seconds=30),
            result=_VERIFIED,
        )


async def test_only_current_owner_can_complete_before_lease_expiry() -> None:
    state = InMemoryStateStore()
    store = StateStorePendingEffectStore(state)
    registered = await _register(store)
    claimed = await store.claim(
        registered.expected.prediction_id,
        owner_id="observer-one",
        expected_revision=registered.revision,
        now=_NOW,
        lease_until=_NOW + timedelta(minutes=1),
    )

    with pytest.raises(PendingEffectOwnershipError):
        await store.complete(
            registered.expected.prediction_id,
            owner_id="observer-two",
            owner_generation=claimed.owner_generation,
            expected_revision=claimed.revision,
            completed_at=_NOW + timedelta(seconds=30),
            result=_VERIFIED,
        )
    completed = await store.complete(
        registered.expected.prediction_id,
        owner_id="observer-one",
        owner_generation=claimed.owner_generation,
        expected_revision=claimed.revision,
        completed_at=_NOW + timedelta(seconds=30),
        result=_VERIFIED,
    )

    assert completed.status is PendingEffectStatus.COMPLETED
    assert completed.completed_at == _NOW + timedelta(seconds=30)
    assert completed.verification_status is EffectVerificationStatus.VERIFIED
    assert completed.verification_reason is EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE
    assert len(state.audit_entries) == 3


async def test_ready_list_is_deadline_ordered_and_includes_expired_claims() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    later = await _register(store, _expected("later", deadline_minutes=10))
    earlier = await _register(store, _expected("earlier", deadline_minutes=5))
    claimed = await store.claim(
        earlier.expected.prediction_id,
        owner_id="observer-one",
        expected_revision=earlier.revision,
        now=_NOW,
        lease_until=_NOW + timedelta(minutes=1),
    )

    before_expiry = await store.list_ready(now=_NOW + timedelta(seconds=30))
    after_expiry = await store.list_ready(now=_NOW + timedelta(minutes=2))

    assert before_expiry == (later,)
    assert tuple(record.expected.prediction_id for record in after_expiry) == (
        "earlier",
        "later",
    )
    assert after_expiry[0].owner_generation == claimed.owner_generation


async def test_malformed_durable_state_fails_closed() -> None:
    state = InMemoryStateStore()
    store = StateStorePendingEffectStore(state)
    registered = await _register(store)
    key = (
        "mscp:pending-effect:"
        + hashlib.sha256(registered.expected.prediction_id.encode()).hexdigest()
    )
    await state.write_state(key, {"schema_version": "1.0.0", "revision": 1})

    with pytest.raises(ValueError, match="unsupported schema"):
        await store.get(registered.expected.prediction_id)


async def test_pending_version_one_record_replays_without_inventing_verification() -> None:
    state = InMemoryStateStore()
    store = StateStorePendingEffectStore(state)
    registered = await _register(store)
    key = (
        "mscp:pending-effect:"
        + hashlib.sha256(registered.expected.prediction_id.encode()).hexdigest()
    )
    legacy = registered.to_mapping()
    legacy["schema_version"] = "1.0.0"
    legacy.pop("verification_status")
    legacy.pop("verification_reason")
    await state.write_state(key, legacy)

    replay = await store.get(registered.expected.prediction_id)

    assert replay.status is PendingEffectStatus.PENDING
    assert replay.verification_status is None
    assert replay.verification_reason is None
