"""A bounded challenger is evidence only; the actual T1 decision stays legacy."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.tiers.t1_lightweight import (
    CurrentReuseVerification,
    CurrentReuseVerifier,
    LearnedAction,
    OperationalCaseContext,
    SimilarityMatch,
    T1Config,
    T1Decision,
    T1Outcome,
    T1Tier,
)
from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel
from fdai.shared.contracts.models import Event

from .test_contextual_reuse import _action, _event, _Verifier

_NOW = datetime(2026, 8, 1, 0, 0, 3, tzinfo=UTC)


class _Library:
    def __init__(self, matches: tuple[SimilarityMatch, ...]) -> None:
        self.matches = matches
        self.calls: list[int] = []

    async def search(
        self, query_vector: Sequence[float], *, k: int = 5
    ) -> tuple[SimilarityMatch, ...]:
        self.calls.append(k)
        return self.matches


class _Cases:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def current_revision_available(self, *, case_ref: str, **values: object) -> bool:
        self.calls.append(case_ref)
        return True


class _Verifications:
    def __init__(self, **changes: dict[str, object]) -> None:
        self.changes = changes
        self.calls: list[str] = []
        self.hook: Callable[[], Awaitable[None]] | None = None

    async def verify(
        self, *, event: Event, action: LearnedAction, context: OperationalCaseContext
    ) -> CurrentReuseVerification:
        self.calls.append(action.signature)
        if self.hook is not None:
            await self.hook()
        verifier: CurrentReuseVerifier = _Verifier(**self.changes.get(action.signature, {}))
        return await verifier.verify(event=event, action=action, context=context)


def _matches(*, top_rate: float = 0.99) -> tuple[SimilarityMatch, ...]:
    return (
        SimilarityMatch(
            action=replace(_action(), signature="top", success_rate=top_rate), score=0.99
        ),
        SimilarityMatch(action=replace(_action(), signature="next"), score=0.98),
    )


def _tier(
    *,
    matches: tuple[SimilarityMatch, ...] | None = None,
    verifier: _Verifications | None = None,
    config: T1Config | None = None,
    cases: _Cases | None = None,
) -> tuple[T1Tier, _Library, _Verifications]:
    library = _Library(_matches() if matches is None else matches)
    verifier = verifier or _Verifications()
    return (
        T1Tier(
            embedding_model=DeterministicEmbeddingModel(),
            pattern_library=library,
            current_reuse_verifier=verifier,
            config=config or T1Config(compare_eligibility=True),
            clock=lambda: _NOW,
            case_history=cases or _Cases(),  # type: ignore[arg-type]
        ),
        library,
        verifier,
    )


def _actual(decision: T1Decision) -> T1Decision:
    return replace(decision, eligibility_comparison=None)


@pytest.mark.parametrize("rate", [0.5, 0.99])
async def test_default_and_explicit_off_keep_exact_baseline_and_provider_calls(rate: float) -> None:
    matches = _matches(top_rate=rate)
    default, default_library, default_verifier = _tier(matches=matches, config=T1Config())
    disabled, disabled_library, disabled_verifier = _tier(
        matches=matches, config=T1Config(compare_eligibility=False)
    )
    enabled, _, enabled_verifier = _tier(matches=matches)
    expected = await default.evaluate(event=_event())
    off = await disabled.evaluate(event=_event())
    on = await enabled.evaluate(event=_event())
    assert expected == off == _actual(on)
    assert expected.eligibility_comparison is None
    assert default_library.calls == disabled_library.calls == [5]
    assert default_verifier.calls == disabled_verifier.calls == (["top"] if rate > 0.9 else [])
    assert enabled_verifier.calls == (["top"] if rate > 0.9 else ["next"])

    enabled._config = T1Config(compare_eligibility=False)
    assert await enabled.evaluate(event=_event()) == expected


async def test_ineligible_top_does_not_hide_challenger_or_change_actual_selection() -> None:
    verifier = _Verifications(top={"preconditions_passed": False})
    cases = _Cases()
    tier, library, _ = _tier(verifier=verifier, cases=cases)
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert result.outcome is comparison.baseline_outcome is T1Outcome.ABSTAIN
    assert result.best_match is comparison.baseline_match is library.matches[0]
    assert result.reason == "current_precondition_failed"
    assert comparison.challenger_match is library.matches[1]
    assert [check.eligible for check in comparison.candidates] == [False, True]
    assert comparison.candidates[1].current_reuse_verification is not None
    assert result.current_reuse_verification is None
    assert result.requires_reverification
    assert comparison.stop_reason is None
    assert verifier.calls == ["top", "next"]
    assert len(cases.calls) == 3
    assert [match.action.reuse_count for match in library.matches] == [0, 0]
    assert [match.action.success_rate for match in library.matches] == [0.99, 0.99]


async def test_all_candidates_ineligible_is_not_a_success() -> None:
    verifier = _Verifications(
        top={"preconditions_passed": False}, next={"rollback_resolved": False}
    )
    tier, _, _ = _tier(verifier=verifier)
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert result.outcome is T1Outcome.ABSTAIN
    assert comparison.challenger_match is None
    assert all(not check.eligible for check in comparison.candidates)
    assert comparison.candidates[1].reasons == ("historical_rollback_unresolved",)
    assert comparison.stop_reason is None


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_type": "kubernetes.deployment"},
        {"failure_fingerprint": "7" * 64},
        {"topology_role": "depends-on"},
        {"graph_digest": "9" * 64},
        {"owner_digest": "8" * 64},
        {"preconditions_passed": False},
        {"blast_radius_within_limit": False},
        {"dry_run_passed": False},
        {"idempotency_available": False},
        {"rollback_resolved": False},
    ],
)
async def test_candidate_local_incompatibility_can_reveal_a_challenger(
    changes: dict[str, object],
) -> None:
    tier, library, verifier = _tier(verifier=_Verifications(top=changes))
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert result.outcome is T1Outcome.ABSTAIN
    assert comparison.challenger_match is library.matches[1]
    assert comparison.stop_reason is None
    assert verifier.calls == ["top", "next"]


async def test_score_order_is_stable_and_only_retrieved_candidates_are_checked() -> None:
    first, second = _matches()
    third = replace(second, action=replace(second.action, signature="third"))
    tier, library, verifier = _tier(
        matches=(second, third, first),
        verifier=_Verifications(top={"preconditions_passed": False}),
    )
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.challenger_match is second
    assert result.best_match is first
    assert verifier.calls == ["top", "next"]
    assert library.calls == [5]


async def test_equal_top_scores_keep_legacy_first_returned_tie_break() -> None:
    first, second = _matches()
    first = replace(first, score=second.score)
    tier, _, verifier = _tier(
        matches=(first, second), verifier=_Verifications(top={"preconditions_passed": False})
    )
    result = await tier.evaluate(event=_event())
    assert result.best_match is first
    assert result.eligibility_comparison is not None
    assert result.eligibility_comparison.challenger_match is second
    assert verifier.calls == ["top", "next"]


async def test_screening_is_bounded_to_five_candidates() -> None:
    matches = tuple(
        SimilarityMatch(
            action=replace(_action(), signature=f"candidate-{index}", success_rate=0.5),
            score=0.99 - index / 100,
        )
        for index in range(5)
    )
    tier, library, verifier = _tier(matches=matches)
    result = await tier.evaluate(event=_event())
    assert result.eligibility_comparison is not None
    assert len(result.eligibility_comparison.candidates) == 5
    assert result.eligibility_comparison.challenger_match is None
    assert library.calls == [5]
    assert verifier.calls == []


async def test_below_threshold_candidates_never_collect_current_evidence() -> None:
    matches = tuple(
        replace(match, score=0.7 - index / 100) for index, match in enumerate(_matches())
    )
    tier, _, verifier = _tier(matches=matches)
    result = await tier.evaluate(event=_event())
    assert result.eligibility_comparison is not None
    assert len(result.eligibility_comparison.candidates) == 2
    assert result.eligibility_comparison.challenger_match is None
    assert verifier.calls == []


async def test_empty_library_records_no_invented_challenger() -> None:
    tier, _, verifier = _tier(matches=())
    result = await tier.evaluate(event=_event())
    assert result.reason == "no_neighbour_found"
    assert result.eligibility_comparison is not None
    assert result.eligibility_comparison.candidates == ()
    assert result.eligibility_comparison.challenger_match is None
    assert verifier.calls == []


@pytest.mark.parametrize(
    "rate",
    [
        True,
        "0.99",
        float("nan"),
        float("inf"),
        -0.1,
        1.1,
        pytest.param(1 << 4096, id="oversized-integer"),
    ],
)
@pytest.mark.parametrize("compare", [False, True])
async def test_invalid_historical_success_is_never_skipped_for_a_valid_candidate(
    rate: Any, compare: bool
) -> None:
    tier, _, verifier = _tier(
        matches=_matches(top_rate=rate),
        config=T1Config(compare_eligibility=compare),
    )
    result = await tier.evaluate(event=_event())
    assert result.outcome is T1Outcome.ABSTAIN
    assert verifier.calls == []
    if compare:
        assert result.eligibility_comparison is not None
        assert result.eligibility_comparison.challenger_match is None
        assert result.eligibility_comparison.stop_reason == result.reason


@pytest.mark.parametrize(
    ("score", "reason"),
    [
        (float("nan"), "non_finite_similarity_score"),
        (float("inf"), "non_finite_similarity_score"),
        (-float("inf"), "non_finite_similarity_score"),
        (1.001, "similarity_score_out_of_range"),
        (-1.001, "similarity_score_out_of_range"),
        pytest.param(1 << 4096, "similarity_score_out_of_range", id="oversized-integer"),
        (True, "invalid_similarity_score"),
        ("0.98", "invalid_similarity_score"),
    ],
)
@pytest.mark.parametrize("compare", [False, True])
async def test_one_poisoned_similarity_invalidates_the_whole_result(
    score: Any, reason: str, compare: bool
) -> None:
    top, other = _matches()
    tier, _, verifier = _tier(
        matches=(top, replace(other, score=score)),
        config=T1Config(compare_eligibility=compare),
    )
    result = await tier.evaluate(event=_event())
    assert result.reason == reason
    assert result.best_match is None
    assert result.outcome is T1Outcome.ABSTAIN
    assert verifier.calls == []
    if compare:
        assert result.eligibility_comparison is not None
        assert result.eligibility_comparison.stop_reason == reason
        assert result.eligibility_comparison.challenger_match is None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"policy_allowed": False}, "current_policy_denied"),
        ({"target_identity_verified": False}, "current_target_identity_unverified"),
        (
            {"preconditions_passed": False, "policy_allowed": False},
            "current_policy_denied",
        ),
    ],
)
async def test_request_wide_denial_cannot_be_bypassed_by_another_candidate(
    changes: dict[str, object], reason: str
) -> None:
    tier, _, verifier = _tier(verifier=_Verifications(top=changes))
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert result.outcome is T1Outcome.ABSTAIN
    assert comparison.stop_reason == reason
    assert comparison.challenger_match is None
    assert len(comparison.candidates) == 1
    assert verifier.calls == ["top"]


@pytest.mark.parametrize("mutation", ["target", "scope", "params", "rule", "signature"])
async def test_stale_exact_scope_admission_stops_comparison(mutation: str) -> None:
    original = _event()
    top, other = _matches()
    current_verifier: CurrentReuseVerifier = _Verifier()
    assert top.action.operational_case is not None
    verification = await current_verifier.verify(
        event=original, action=top.action, context=top.action.operational_case
    )
    event = original
    if mutation == "target":
        event = original.model_copy(
            update={"payload": {"resource": {"type": "kubernetes.service", "id": "other"}}}
        )
    elif mutation == "scope":
        event = original.model_copy(
            update={"payload": {**original.payload, "access_scope_digest": "9" * 64}}
        )
    elif mutation == "params":
        top = replace(top, action=replace(top.action, params={"replicas": 20}))
    elif mutation == "rule":
        top = replace(top, action=replace(top.action, rule_id="learned.operational.other"))
    else:
        top = replace(top, action=replace(top.action, signature="other"))
    assert verification.decision_evidence is not None
    changed_evidence: dict[str, object] = {"decision_evidence": verification.decision_evidence}
    verifier = _Verifications(**{top.action.signature: changed_evidence})
    tier, _, _ = _tier(matches=(top, other), verifier=verifier)
    result = await tier.evaluate(event=event)
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.stop_reason == "decision_evidence_scope_mismatch"
    assert comparison.challenger_match is None
    assert verifier.calls == [top.action.signature]


async def test_corrected_source_during_candidate_verification_cannot_be_selected() -> None:
    class _ChangingCases(_Cases):
        async def current_revision_available(self, *, case_ref: str, **values: object) -> bool:
            self.calls.append(case_ref)
            return len(self.calls) != 2

    tier, _, verifier = _tier(
        matches=_matches(top_rate=0.5),
        cases=_ChangingCases(),
    )
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.challenger_match is None
    assert comparison.candidates[-1].reasons == ("current_case_revision_changed",)
    assert comparison.stop_reason == "current_case_revision_changed"
    assert verifier.calls == ["next"]


@pytest.mark.parametrize("raises", [False, True])
async def test_unavailable_or_unauthorized_source_stops_comparison(raises: bool) -> None:
    class _UnavailableCases(_Cases):
        async def current_revision_available(self, **values: object) -> bool:
            if raises:
                raise PermissionError("source denied")
            return False

    tier, _, verifier = _tier(cases=_UnavailableCases())
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.stop_reason == "current_case_revision_unavailable"
    assert comparison.challenger_match is None
    assert verifier.calls == []


async def test_final_source_denial_cannot_be_bypassed_by_another_candidate() -> None:
    class _DeniedCases(_Cases):
        async def current_revision_available(self, **values: object) -> bool:
            self.calls.append("read")
            if len(self.calls) == 2:
                raise PermissionError("source denied")
            return True

    tier, _, verifier = _tier(cases=_DeniedCases())
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.stop_reason == "current_case_revision_changed"
    assert comparison.challenger_match is None
    assert verifier.calls == ["top"]


async def test_expiry_during_final_read_keeps_challenger_ineligible() -> None:
    instant = _NOW

    class _ExpiringCases(_Cases):
        async def current_revision_available(self, **values: object) -> bool:
            nonlocal instant
            self.calls.append("read")
            if len(self.calls) == 2:
                instant += timedelta(days=1)
            return True

    tier, _, _ = _tier(matches=_matches(top_rate=0.5), cases=_ExpiringCases())
    tier._clock = lambda: instant
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.challenger_match is None
    assert "current_evidence_expired" in comparison.candidates[-1].reasons


async def test_malformed_verifier_is_not_a_skippable_candidate_failure() -> None:
    class _Malformed(_Verifications):
        async def verify(self, **values: Any) -> CurrentReuseVerification:
            self.calls.append("malformed")
            return None  # type: ignore[return-value]

    tier, _, verifier = _tier(verifier=_Malformed())
    result = await tier.evaluate(event=_event())
    comparison = result.eligibility_comparison
    assert comparison is not None
    assert comparison.stop_reason == "t1_candidate_error:AttributeError"
    assert comparison.challenger_match is None
    assert verifier.calls == ["malformed"]


@pytest.mark.parametrize("malformed", [None, [None], (None,), (*_matches(),) * 3])
async def test_malformed_or_over_limit_provider_output_is_rejected(malformed: Any) -> None:
    tier, library, verifier = _tier()
    library.matches = malformed
    result = await tier.evaluate(event=_event())
    assert result.outcome is T1Outcome.ABSTAIN
    assert result.reason == "invalid_pattern_library_matches"
    assert result.best_match is None
    assert verifier.calls == []


async def test_comparison_deadline_does_not_overwrite_completed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, closed = asyncio.Event(), asyncio.Event()
    timeout_calls: list[float | None] = []
    original_timeout = asyncio.timeout

    def timeout(delay: float | None) -> asyncio.Timeout:
        timeout_calls.append(delay)
        return original_timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", timeout)

    async def blocked() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    verifier = _Verifications()
    verifier.hook = blocked
    tier, _, _ = _tier(
        matches=_matches(top_rate=0.5),
        verifier=verifier,
        config=T1Config(compare_eligibility=True, timeout_seconds=0.01),
    )
    result = await tier.evaluate(event=_event())
    assert entered.is_set() and closed.is_set()
    assert result.reason == "success_rate=0.5000<floor=0.9000"
    assert result.outcome is T1Outcome.ABSTAIN
    assert result.eligibility_comparison is not None
    assert result.eligibility_comparison.stop_reason == "t1_deadline_exceeded"
    assert result.eligibility_comparison.challenger_match is None
    assert timeout_calls == [0.01]


async def test_external_cancellation_during_comparison_is_not_a_decision() -> None:
    entered, closed = asyncio.Event(), asyncio.Event()

    async def blocked() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    verifier = _Verifications()
    verifier.hook = blocked
    tier, _, _ = _tier(matches=_matches(top_rate=0.5), verifier=verifier)
    task = asyncio.create_task(tier.evaluate(event=_event()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()


@pytest.mark.parametrize("flag", [None, 1, "true"])
def test_comparison_flag_requires_explicit_boolean(flag: Any) -> None:
    with pytest.raises(ValueError, match="compare_eligibility MUST be boolean"):
        _tier(config=T1Config(compare_eligibility=flag))
