"""Reviewed MSCP profile lifecycle tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile.profile_lifecycle import (
    IndependentProfileReview,
    MscpProfileLifecycleConflictError,
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
