"""Reviewed MSCP profile lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile.profile_lifecycle import (
    IndependentProfileReview,
    MscpProfileLifecycleConflictError,
    MscpProfileLifecycleRecord,
    MscpProfileMode,
    StateStoreMscpProfileLifecycle,
    readiness_digest,
)
from fdai.core.mscp_profile.readiness import (
    MscpCandidateKey,
    MscpReadinessPolicy,
    ReviewedEffectOutcome,
    evaluate_mscp_readiness,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 29, 4, 0, tzinfo=UTC)
_CANDIDATE = MscpCandidateKey(
    action_type="example.restart",
    effect_metric="availability",
    environment="non-production",
    observer_version="observer-v1",
)


def _readiness():
    outcomes = tuple(
        ReviewedEffectOutcome(
            candidate=_CANDIDATE,
            observed_at=_NOW - timedelta(days=index % 14, seconds=index),
            reviewed=True,
            prediction_accurate=True,
            false_positive=False,
            false_negative=False,
            policy_escape=False,
            correlation_error=False,
            verified_then_rollback_or_incident=False,
            observer_available=True,
            stale=False,
            provider_failed=False,
            observation_latency_ms=100,
            rollback=False,
            human_touchpoint=False,
        )
        for index in range(200)
    )
    return evaluate_mscp_readiness(
        outcomes,
        policy=MscpReadinessPolicy(
            min_accuracy=0.95,
            demotion_drill_passed=True,
        ),
    )


def _review(readiness, **changes: object) -> IndependentProfileReview:
    values: dict[str, object] = {
        "review_id": "review-one",
        "reviewer_id": "independent-reviewer",
        "candidate": _CANDIDATE,
        "readiness_digest": readiness_digest(readiness),
        "reviewed_at": _NOW,
        "approved": True,
    }
    values.update(changes)
    return IndependentProfileReview(**values)  # type: ignore[arg-type]


async def test_profile_defaults_to_shadow_and_survives_restart() -> None:
    state = InMemoryStateStore()
    first = StateStoreMscpProfileLifecycle(state)
    registered = await first.register(_CANDIDATE, at=_NOW)
    replay = await StateStoreMscpProfileLifecycle(state).register(
        _CANDIDATE,
        at=_NOW + timedelta(minutes=1),
    )

    assert registered == replay
    assert registered.mode is MscpProfileMode.SHADOW
    assert registered.activation_authority is False
    assert len(state.audit_entries) == 1
    assert await state.verify_chain() is True


async def test_promotion_requires_matching_ready_report_and_independent_review() -> None:
    state = InMemoryStateStore()
    lifecycle = StateStoreMscpProfileLifecycle(state)
    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    readiness = _readiness()

    with pytest.raises(MscpProfileLifecycleConflictError, match="does not match"):
        await lifecycle.promote(
            _CANDIDATE,
            expected_revision=registered.revision,
            readiness=readiness,
            review=_review(readiness, readiness_digest="sha256:" + "0" * 64),
            at=_NOW + timedelta(minutes=1),
        )
    promoted = await lifecycle.promote(
        _CANDIDATE,
        expected_revision=registered.revision,
        readiness=readiness,
        review=_review(readiness),
        at=_NOW + timedelta(minutes=1),
    )

    assert promoted.mode is MscpProfileMode.GATING
    assert promoted.readiness_digest == readiness_digest(readiness)
    assert promoted.review_id == "review-one"
    assert promoted.activation_authority is False
    assert await state.verify_chain() is True


async def test_statistically_incomplete_readiness_cannot_promote() -> None:
    state = InMemoryStateStore()
    lifecycle = StateStoreMscpProfileLifecycle(state)
    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    incomplete = replace(_readiness(), gaps=("sample_count",), ready_for_review=False)

    with pytest.raises(MscpProfileLifecycleConflictError, match="not eligible"):
        await lifecycle.promote(
            _CANDIDATE,
            expected_revision=registered.revision,
            readiness=incomplete,
            review=_review(incomplete),
            at=_NOW + timedelta(minutes=1),
        )


async def test_immediate_demotion_is_audited_and_stale_revision_is_rejected() -> None:
    state = InMemoryStateStore()
    lifecycle = StateStoreMscpProfileLifecycle(state)
    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    readiness = _readiness()
    promoted = await lifecycle.promote(
        _CANDIDATE,
        expected_revision=registered.revision,
        readiness=readiness,
        review=_review(readiness),
        at=_NOW + timedelta(minutes=1),
    )
    demoted = await lifecycle.demote(
        _CANDIDATE,
        expected_revision=promoted.revision,
        reason="observer_slo_regressed",
        at=_NOW + timedelta(minutes=2),
    )

    assert demoted.mode is MscpProfileMode.SHADOW
    assert demoted.transition_reason == "observer_slo_regressed"
    assert len(state.audit_entries) == 3
    with pytest.raises(MscpProfileLifecycleConflictError, match="stale"):
        await lifecycle.demote(
            _CANDIDATE,
            expected_revision=promoted.revision,
            reason="duplicate",
            at=_NOW + timedelta(minutes=3),
        )


async def test_concurrent_transition_allows_only_one_revision_winner() -> None:
    lifecycle = StateStoreMscpProfileLifecycle(InMemoryStateStore())
    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    readiness = _readiness()
    first, second = await asyncio.gather(
        lifecycle.promote(
            _CANDIDATE,
            expected_revision=registered.revision,
            readiness=readiness,
            review=_review(readiness),
            at=_NOW + timedelta(minutes=1),
        ),
        lifecycle.promote(
            _CANDIDATE,
            expected_revision=registered.revision,
            readiness=readiness,
            review=_review(readiness, review_id="review-two"),
            at=_NOW + timedelta(minutes=1),
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in (first, second)) == 1
    assert sum(isinstance(item, MscpProfileLifecycleConflictError) for item in (first, second)) == 1


async def test_profile_lifecycle_validation_and_idempotent_promote() -> None:
    readiness = _readiness()
    with pytest.raises(ValueError, match="bounded text"):
        _review(readiness, review_id=" ")
    with pytest.raises(ValueError, match="SHA-256"):
        _review(readiness, readiness_digest="bad")
    with pytest.raises(ValueError, match="boolean"):
        _review(readiness, approved="yes")
    with pytest.raises(ValueError, match="timezone-aware"):
        _review(readiness, reviewed_at=datetime(2026, 8, 29))

    with pytest.raises(ValueError, match="revision MUST be positive"):
        MscpProfileLifecycleRecord(
            candidate=_CANDIDATE,
            mode=MscpProfileMode.SHADOW,
            revision=0,
            updated_at=_NOW,
        )
    with pytest.raises(ValueError, match="transition_reason"):
        MscpProfileLifecycleRecord(
            candidate=_CANDIDATE,
            mode=MscpProfileMode.SHADOW,
            revision=1,
            updated_at=_NOW,
            transition_reason=" ",
        )
    with pytest.raises(ValueError, match="activation authority"):
        MscpProfileLifecycleRecord(
            candidate=_CANDIDATE,
            mode=MscpProfileMode.SHADOW,
            revision=1,
            updated_at=_NOW,
            activation_authority=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="requires exact readiness and review"):
        MscpProfileLifecycleRecord(
            candidate=_CANDIDATE,
            mode=MscpProfileMode.GATING,
            revision=1,
            updated_at=_NOW,
        )
    with pytest.raises(ValueError, match="SHA-256 or null"):
        MscpProfileLifecycleRecord(
            candidate=_CANDIDATE,
            mode=MscpProfileMode.SHADOW,
            revision=1,
            updated_at=_NOW,
            readiness_digest="bad",
        )

    rec = MscpProfileLifecycleRecord(
        candidate=_CANDIDATE, mode=MscpProfileMode.SHADOW, revision=1, updated_at=_NOW
    )
    raw = rec.to_mapping()
    with pytest.raises(ValueError, match="unsupported schema"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "schema_version": "2.0.0"})
    with pytest.raises(ValueError, match="candidate MUST be an object"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "candidate": "bad"})
    with pytest.raises(ValueError, match="activation_authority MUST be false"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "activation_authority": True})
    with pytest.raises(ValueError, match="non-empty text"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "transition_reason": ""})
    with pytest.raises(ValueError, match="text or null"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "review_id": 123})
    with pytest.raises(ValueError, match="MUST be an integer"):
        MscpProfileLifecycleRecord.from_mapping({**raw, "revision": True})

    state = InMemoryStateStore()
    lifecycle = StateStoreMscpProfileLifecycle(state)
    with pytest.raises(KeyError):
        await lifecycle.get(_CANDIDATE)

    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    promoted = await lifecycle.promote(
        _CANDIDATE,
        expected_revision=registered.revision,
        readiness=readiness,
        review=_review(readiness),
        at=_NOW + timedelta(minutes=1),
    )
    idempotent = await lifecycle.promote(
        _CANDIDATE,
        expected_revision=promoted.revision,
        readiness=readiness,
        review=_review(readiness),
        at=_NOW + timedelta(minutes=2),
    )
    assert idempotent == promoted

    with pytest.raises(ValueError, match="demotion reason"):
        await lifecycle.demote(
            _CANDIDATE,
            expected_revision=promoted.revision,
            reason=" ",
            at=_NOW + timedelta(minutes=3),
        )

    key = next(iter(state._state))
    other_cand = replace(_CANDIDATE, environment="staging")
    other_rec = MscpProfileLifecycleRecord(
        candidate=other_cand, mode=MscpProfileMode.SHADOW, revision=1, updated_at=_NOW
    )
    state._state[key] = other_rec.to_mapping()
    with pytest.raises(ValueError, match="candidate identity mismatched"):
        await lifecycle.get(_CANDIDATE)
