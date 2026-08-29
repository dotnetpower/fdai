"""MSCP deadline observation worker tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai.core.mscp_profile.effect_verification import (
    EffectVerificationReason,
    EffectVerificationStatus,
    ExpectedEffect,
    ObservedEffect,
)
from fdai.core.mscp_profile.observation_worker import PendingEffectObservationWorker
from fdai.core.mscp_profile.pending_effect_store import StateStorePendingEffectStore
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)


def _expected(prediction_id: str) -> ExpectedEffect:
    return ExpectedEffect(
        prediction_id=prediction_id,
        target_ref=f"resource/{prediction_id}",
        metric="availability",
        acceptable_min=0.9,
        acceptable_max=1.0,
        predicted_at=_NOW,
        observation_deadline=_NOW + timedelta(minutes=5),
    )


async def _register(store: StateStorePendingEffectStore, prediction_id: str) -> None:
    await store.register(
        _expected(prediction_id),
        action_type="example.restart",
        environment="non-production",
        observer_version="observer-v1",
    )


async def test_worker_records_verified_mismatch_missing_and_provider_failure() -> None:
    store = StateStorePendingEffectStore(InMemoryStateStore())
    for prediction_id in ("verified", "mismatch", "missing", "failed"):
        await _register(store, prediction_id)
    clock_values = iter(
        (
            _NOW,
            _NOW + timedelta(seconds=1),
            _NOW + timedelta(seconds=2),
            _NOW + timedelta(seconds=3),
            _NOW + timedelta(seconds=4),
        )
    )

    async def observe(record):
        prediction_id = record.expected.prediction_id
        if prediction_id == "failed":
            raise RuntimeError("provider unavailable")
        if prediction_id == "missing":
            return None
        return ObservedEffect(
            prediction_id=prediction_id,
            target_ref=record.expected.target_ref,
            metric=record.expected.metric,
            value=0.95 if prediction_id == "verified" else 0.5,
            observed_at=_NOW + timedelta(seconds=1),
        )

    report = await PendingEffectObservationWorker(
        store=store,
        observer=observe,
        owner_id="observer-worker",
        clock=lambda: next(clock_values),
    ).run_once()

    assert report.considered == 4
    assert report.verified == 1
    assert report.mismatched == 1
    assert report.held == 2
    assert report.provider_failures == 1
    assert report.ownership_conflicts == 0
    assert report.execution_authority is False
    assert (await store.get("verified")).verification_status is EffectVerificationStatus.VERIFIED
    assert (await store.get("mismatch")).verification_status is EffectVerificationStatus.MISMATCH
    assert (await store.get("missing")).verification_reason is (
        EffectVerificationReason.OBSERVATION_UNAVAILABLE
    )
    assert (await store.get("failed")).verification_reason is (
        EffectVerificationReason.OBSERVATION_PROVIDER_FAILED
    )


async def test_completed_effects_do_not_run_again() -> None:
    state = InMemoryStateStore()
    store = StateStorePendingEffectStore(state)
    await _register(store, "verified")
    calls = 0

    async def observe(record):
        nonlocal calls
        calls += 1
        return ObservedEffect(
            prediction_id=record.expected.prediction_id,
            target_ref=record.expected.target_ref,
            metric=record.expected.metric,
            value=1.0,
            observed_at=_NOW,
        )

    worker = PendingEffectObservationWorker(
        store=store,
        observer=observe,
        owner_id="observer-worker",
        clock=lambda: _NOW,
    )
    first = await worker.run_once()
    replay = await worker.run_once()

    assert first.verified == 1
    assert replay.considered == 0
    assert calls == 1
