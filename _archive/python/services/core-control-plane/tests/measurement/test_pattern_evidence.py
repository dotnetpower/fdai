"""Pure pattern evidence: holdout envelopes, measured statistics, and signature identity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.measurement.pattern_evidence import (
    HoldoutPolicy,
    ScoredOutcome,
    StatisticsPolicy,
    holdout_envelopes,
    measured_statistics,
    pattern_signature,
)
from fdai.core.measurement.pattern_growth import (
    OutcomeRecord,
    TemporalHoldoutConfig,
    TemporalHoldoutValidator,
)
from fdai.delivery.measurement.holdout import (
    HoldoutVerifiedPatternBuilder,
    StateStoreTemporalHoldoutEvidenceSource,
)
from fdai.delivery.measurement.pattern_evidence import scored_outcome
from fdai.delivery.measurement.postgres_growth import PostgresVerifiedPatternBuilder
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_BASE = datetime(2026, 10, 1, tzinfo=UTC)


def _outcomes(
    count: int,
    *,
    step: timedelta = timedelta(hours=2),
    verified: bool = True,
    rolled_back: bool = False,
    scorable: bool = True,
    signature: str = "sig-a",
) -> list[ScoredOutcome]:
    return [
        ScoredOutcome(
            signature=signature,
            observed_at=_BASE + step * index,
            scorable=scorable,
            verified=verified,
            rolled_back=rolled_back,
        )
        for index in range(count)
    ]


def test_envelope_is_complete_only_with_enough_later_samples_over_the_window() -> None:
    policy = HoldoutPolicy(min_samples=20, min_window=timedelta(days=1))
    enough = holdout_envelopes(_outcomes(21), policy=policy)["sig-a"]
    assert enough["complete"] is True

    too_few = holdout_envelopes(_outcomes(20), policy=policy)["sig-a"]
    assert too_few["complete"] is False  # 19 samples after the first

    burst = holdout_envelopes(_outcomes(30, step=timedelta(seconds=1)), policy=policy)["sig-a"]
    assert burst["complete"] is False  # no window elapsed


def test_unscorable_outcomes_never_become_samples() -> None:
    assert holdout_envelopes(_outcomes(30, scorable=False)) == {}


def test_a_failed_or_rolled_back_outcome_is_an_incorrect_sample() -> None:
    items = _outcomes(2) + [
        ScoredOutcome("sig-a", _BASE + timedelta(days=3), True, False, False),
        ScoredOutcome("sig-a", _BASE + timedelta(days=4), True, True, True),
    ]
    samples = holdout_envelopes(items)["sig-a"]["samples"]
    assert [sample["was_correct"] for sample in samples] == [True, True, False, False]


def test_duplicate_timestamps_keep_one_sample() -> None:
    twin = ScoredOutcome("sig-a", _BASE, True, True, False)
    samples = holdout_envelopes([twin, twin])["sig-a"]["samples"]
    assert len(samples) == 1


def test_statistics_need_the_minimum_and_exclude_rollbacks_and_unscorable() -> None:
    policy = StatisticsPolicy(min_outcomes=5)
    assert measured_statistics(_outcomes(4), policy=policy) == {}
    stats = measured_statistics(_outcomes(5), policy=policy)["sig-a"]
    assert (stats.success_rate, stats.reuse_count) == (1.0, 5)

    mixed = _outcomes(8) + _outcomes(2, verified=False)
    mixed += _outcomes(3, rolled_back=True) + _outcomes(3, scorable=False)
    measured = measured_statistics(mixed, policy=policy)["sig-a"]
    assert measured.reuse_count == 10
    assert measured.success_rate == pytest.approx(0.8)


def test_a_new_failure_lowers_the_measured_rate_below_the_t1_floor() -> None:
    policy = StatisticsPolicy(min_outcomes=5)
    before = measured_statistics(_outcomes(10), policy=policy)["sig-a"]
    after = measured_statistics(_outcomes(10) + _outcomes(2, verified=False), policy=policy)[
        "sig-a"
    ]
    assert before.success_rate == 1.0
    assert after.success_rate < 0.9


def test_signature_is_stable_and_sensitive_to_every_identity_field() -> None:
    base = {"action_type_id": "a", "params": {"x": 1}, "rule_id": "r", "operational_case": None}
    assert pattern_signature(**base) == pattern_signature(**base)
    for change in ({"action_type_id": "b"}, {"params": {"x": 2}}, {"rule_id": "s"}):
        assert pattern_signature(**{**base, **change}) != pattern_signature(**base)
    assert pattern_signature(**{**base, "params": {"x": float("nan")}}) is None


def test_scored_outcome_requires_enforce_mode_context_and_boolean_evidence() -> None:
    outcome = {
        "action_type_id": "remediate.tag-add",
        "execution_mode": "enforce",
        "observed_at": _BASE.isoformat(),
        "verification_passed": True,
        "rollback_succeeded": False,
        "scorable": True,
    }
    context = {"rule_id": "r", "params": {"tag": "owner"}}
    recorded = _BASE + timedelta(minutes=1)
    scored = scored_outcome(outcome, context, recorded_at=recorded)
    assert scored is not None and scored.verified and not scored.rolled_back
    assert (
        scored_outcome({**outcome, "execution_mode": "shadow"}, context, recorded_at=recorded)
        is None
    )
    assert scored_outcome(outcome, {}, recorded_at=recorded) is None
    unknown_success = {**outcome, "rollback_succeeded": None}
    assert scored_outcome(unknown_success, context, recorded_at=recorded) is None
    unknown_failure = {**unknown_success, "verification_passed": False}
    failed = scored_outcome(unknown_failure, context, recorded_at=recorded)
    assert failed is not None and not failed.verified and not failed.rolled_back
    future = _BASE + timedelta(days=30)
    assert (
        scored_outcome(
            {**outcome, "observed_at": future.isoformat()}, context, recorded_at=recorded
        )
        is None
    )


class _Embedding:
    dim = 384

    async def embed(self, text: str) -> tuple[float, ...]:
        return (0.1,) * 384


@pytest.mark.asyncio
async def test_the_builder_and_the_evidence_use_the_same_signature() -> None:
    entry = {
        "action_id": "action-1",
        "action_type_id": "remediate.tag-add",
        "observed_at": _BASE.isoformat(),
        "execution_mode": "enforce",
        "decision": "auto",
        "verification_passed": True,
        "rollback_succeeded": False,
        "scorable": True,
        "rule_id": "example.rule",
        "params": {"tag": "owner", "value": "team"},
        "incident_id": "incident-1",
        "embedding_projection": "projection",
    }

    class Builder(PostgresVerifiedPatternBuilder):
        async def _entry(self, action_id: str):  # type: ignore[no-untyped-def]
            return {**entry, "recorded_at": _BASE + timedelta(minutes=1)}

    built = await Builder(dsn="unused", embedding_model=_Embedding()).build(
        OutcomeRecord("action-1", "remediate.tag-add", _BASE, True, True, False)
    )
    assert built is not None
    scored = scored_outcome(entry, entry, recorded_at=_BASE + timedelta(minutes=1))
    assert scored is not None and built[1].signature == scored.signature


@pytest.mark.asyncio
async def test_a_complete_envelope_releases_the_pattern_and_an_incomplete_one_defers_it() -> None:
    store = InMemoryStateStore()
    entry = {
        "action_id": "action-1",
        "action_type_id": "remediate.tag-add",
        "observed_at": _BASE.isoformat(),
        "execution_mode": "enforce",
        "decision": "auto",
        "verification_passed": True,
        "rollback_succeeded": False,
        "scorable": True,
        "rule_id": "example.rule",
        "params": {"tag": "owner"},
        "incident_id": "incident-1",
        "embedding_projection": "projection",
    }

    class Builder(PostgresVerifiedPatternBuilder):
        async def _entry(self, action_id: str):  # type: ignore[no-untyped-def]
            return {**entry, "recorded_at": _BASE + timedelta(minutes=1)}

    gated = HoldoutVerifiedPatternBuilder(
        delegate=Builder(dsn="unused", embedding_model=_Embedding()),
        evidence_source=StateStoreTemporalHoldoutEvidenceSource(store),
        validator=TemporalHoldoutValidator(config=TemporalHoldoutConfig(min_samples=20)),
        audit_store=store,
        clock=lambda: _BASE + timedelta(days=30),
    )
    record = OutcomeRecord("action-1", "remediate.tag-add", _BASE, True, True, False)
    signature = pattern_signature(
        action_type_id="remediate.tag-add",
        params={"tag": "owner"},
        rule_id="example.rule",
        operational_case=None,
    )
    assert signature is not None
    for count, released in ((10, False), (30, True)):
        envelope = holdout_envelopes(_outcomes(count, signature=signature))[signature]
        await store.write_state(f"measurement:pattern_holdout:{signature}", envelope)
        result = await gated.build(record)
        assert (not hasattr(result, "reason")) is released
