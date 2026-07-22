from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.read_investigation import (
    InvestigationExecutionPolicy,
    PlanLatencyEstimate,
    ReadInvestigationBudget,
    ReadInvestigationExecutionMode,
    ReadInvestigationPlan,
    ReadInvestigationRequest,
    ReadLatencyProfile,
    estimate_parallel_p95,
    estimate_plan_latency,
    estimate_sequential_p95,
    latency_profile,
    plan_read_investigation,
)
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadLatencySample,
    ReadToolId,
    ResourceSelector,
)

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _plan(
    intent: ReadInvestigationIntent = ReadInvestigationIntent.RESOURCE_STATE,
    *,
    explicit_deep: bool = False,
) -> ReadInvestigationPlan:
    return plan_read_investigation(
        ReadInvestigationRequest(
            requester_ref="principal:one",
            conversation_ref="conversation:one",
            correlation_ref="correlation:one",
            intent=intent,
            selector=ResourceSelector(name="vm-01", scope_ref="scope:allowed"),
            lookback_seconds=3_600,
            requested_evidence=(),
            budget=ReadInvestigationBudget(),
            idempotency_key="request:one",
            created_at=NOW,
            explicit_deep=explicit_deep,
        )
    )


def test_latency_profile_includes_failures_and_nearest_rank_percentiles() -> None:
    samples = tuple(
        ReadLatencySample(
            tool_id=ReadToolId.GET_RESOURCE_STATE,
            transport="rest",
            operation_class="resource_state",
            succeeded=index != 4,
            queue_duration_ms=10,
            execution_duration_ms=value,
            recorded_at=NOW,
        )
        for index, value in enumerate((90, 190, 290, 390, 490))
    )
    profile = latency_profile(samples)
    assert profile.sample_count == 5
    assert profile.failure_rate == 0.2
    assert profile.p50_ms == 200
    assert profile.p95_ms == 400


def test_plan_estimate_uses_broad_cold_range_until_minimum_samples() -> None:
    plan = _plan()
    estimate = estimate_plan_latency(
        plan,
        {ReadToolId.RESOLVE_RESOURCE: ReadLatencyProfile(2, 0.0, 10, 20)},
        minimum_samples=3,
    )
    assert estimate.measured is False
    assert (estimate.lower_ms, estimate.upper_ms) == (1_000, 8_000)


def test_plan_estimate_uses_sum_for_sequence_and_max_for_fanout() -> None:
    profiles = [
        ReadLatencyProfile(20, 0.0, 100, 200),
        ReadLatencyProfile(20, 0.0, 300, 500),
    ]
    assert estimate_sequential_p95(profiles) == 700
    assert estimate_parallel_p95(profiles) == 500


def test_multi_source_plan_estimate_matches_sequential_execution() -> None:
    plan = _plan(ReadInvestigationIntent.CHANGE_ATTRIBUTION)
    profiles = {
        ReadToolId.RESOLVE_RESOURCE: ReadLatencyProfile(20, 0.0, 100, 200),
        ReadToolId.QUERY_RESOURCE_ACTIVITY: ReadLatencyProfile(20, 0.0, 300, 500),
        ReadToolId.QUERY_GUEST_SHUTDOWN_EVENTS: ReadLatencyProfile(20, 0.0, 500, 1_000),
        ReadToolId.QUERY_RESOURCE_HEALTH: ReadLatencyProfile(20, 0.0, 400, 700),
    }

    estimate = estimate_plan_latency(plan, profiles, minimum_samples=20)

    assert estimate.measured is True
    assert estimate.multi_source is True
    assert estimate.lower_ms == 1_300
    assert estimate.upper_ms == 2_400


def test_execution_policy_boundaries_and_forced_detach() -> None:
    policy = InvestigationExecutionPolicy(detach_on_multi_source=False)
    plan = _plan()
    assert policy.select(plan, PlanLatencyEstimate(100, 4_000, True, 40, False)) is (
        ReadInvestigationExecutionMode.DIRECT
    )
    assert policy.select(plan, PlanLatencyEstimate(100, 4_001, True, 40, False)) is (
        ReadInvestigationExecutionMode.STREAMED
    )
    assert policy.select(plan, PlanLatencyEstimate(100, 15_001, True, 40, False)) is (
        ReadInvestigationExecutionMode.DETACHED
    )
    multi_source = _plan(ReadInvestigationIntent.CHANGE_ATTRIBUTION)
    assert (
        InvestigationExecutionPolicy().select(
            multi_source,
            PlanLatencyEstimate(100, 1_000, True, 80, True),
        )
        is ReadInvestigationExecutionMode.DETACHED
    )
    assert (
        policy.select(
            _plan(explicit_deep=True),
            PlanLatencyEstimate(100, 1_000, True, 80, False),
        )
        is ReadInvestigationExecutionMode.DETACHED
    )
