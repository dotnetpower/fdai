"""Validation + helper edge cases for the investigation module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.investigation import Priority, priority_for
from fdai.core.investigation.analyzer import (
    Aggregation,
    Comparison,
    Threshold,
    ThresholdAnalyzer,
    reduce_values,
)
from fdai.core.investigation.contract import AnalyzerFinding
from fdai.core.investigation.recommendations import (
    build_recommendations,
    summarize_priorities,
)
from fdai.shared.contracts.models import Severity
from fdai.shared.providers.metric import StaticMetricProvider

_T = datetime(2026, 7, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("how", "expected"),
    [
        (Aggregation.MAX, 9.0),
        (Aggregation.MIN, 1.0),
        (Aggregation.SUM, 12.0),
        (Aggregation.AVG, 4.0),
        (Aggregation.LAST, 2.0),
        (Aggregation.P95, 9.0),
    ],
)
def test_reduce_values_all_aggregations(how: Aggregation, expected: float) -> None:
    assert reduce_values([9.0, 1.0, 2.0], how) == expected


def test_reduce_values_empty_is_none() -> None:
    assert reduce_values([], Aggregation.MAX) is None


def test_threshold_analyzer_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="resource_kind"):
        ThresholdAnalyzer(
            resource_kind="",
            provider=StaticMetricProvider(()),
            thresholds=(),
        )


def test_analyzer_finding_rejects_empty_resource_ref() -> None:
    with pytest.raises(ValueError, match="resource_ref"):
        AnalyzerFinding(
            resource_ref="",
            resource_kind="k",
            signal="s",
            observation="o",
            severity=Severity.LOW,
            occurred_at=_T,
        )


def test_analyzer_finding_rejects_empty_signal() -> None:
    with pytest.raises(ValueError, match="signal"):
        AnalyzerFinding(
            resource_ref="r",
            resource_kind="k",
            signal="",
            observation="o",
            severity=Severity.LOW,
            occurred_at=_T,
        )


def test_priority_for_mapping() -> None:
    assert priority_for(Severity.CRITICAL) is Priority.P1
    assert priority_for(Severity.HIGH) is Priority.P2
    assert priority_for(Severity.MEDIUM) is Priority.P3
    assert priority_for(Severity.LOW) is Priority.P3


def _finding(signal: str, severity: Severity) -> AnalyzerFinding:
    return AnalyzerFinding(
        resource_ref="r",
        resource_kind="k",
        signal=signal,
        observation=f"{signal} {severity.value}",
        severity=severity,
        occurred_at=_T,
    )


def test_recommendations_dedup_keeps_most_severe() -> None:
    # Same (resource, signal); the more severe finding wins.
    recs = build_recommendations(
        [_finding("cpu", Severity.MEDIUM), _finding("cpu", Severity.CRITICAL)]
    )
    assert len(recs) == 1
    assert recs[0].priority is Priority.P1


def test_recommendations_dedup_ignores_less_severe_duplicate() -> None:
    # Reverse order: the first (critical) stays, the second (low) is ignored.
    recs = build_recommendations(
        [_finding("cpu", Severity.CRITICAL), _finding("cpu", Severity.LOW)]
    )
    assert len(recs) == 1
    assert recs[0].priority is Priority.P1


def test_summarize_priorities_counts() -> None:
    recs = build_recommendations([_finding("a", Severity.CRITICAL), _finding("b", Severity.MEDIUM)])
    counts = summarize_priorities(recs)
    assert counts[Priority.P1] == 1
    assert counts[Priority.P3] == 1


def test_threshold_gte_default_aggregation_is_max() -> None:
    t = Threshold(
        metric="m",
        compare=Comparison.GTE,
        bound=1.0,
        severity=Severity.LOW,
        signal="s",
        observation="o",
    )
    assert t.aggregation is Aggregation.MAX


def test_recommendations_merge_citations_and_prefer_latest_on_tie() -> None:
    earlier = AnalyzerFinding(
        resource_ref="r1",
        resource_kind="k",
        signal="cpu",
        observation="earlier",
        severity=Severity.HIGH,
        occurred_at=_T,
        evidence_refs=("m=91",),
    )
    later = AnalyzerFinding(
        resource_ref="r1",
        resource_kind="k",
        signal="cpu",
        observation="later",
        severity=Severity.HIGH,
        occurred_at=datetime(2026, 7, 10, 0, 5, tzinfo=UTC),
        evidence_refs=("m=95",),
    )
    recs = build_recommendations([earlier, later])
    assert len(recs) == 1
    assert recs[0].detail == "later"
    assert recs[0].citations == ("m=91", "m=95")


@pytest.mark.asyncio
async def test_paas_analyzers_detect_postgresql_redis_and_key_vault() -> None:
    from fdai.core.investigation.analyzers import (
        key_vault_analyzer,
        postgresql_analyzer,
        redis_analyzer,
    )
    from fdai.shared.providers.metric import MetricPoint

    points = (
        MetricPoint(
            metric_name="postgresql_cpu_percent",
            at=_T,
            value=95.0,
            labels={"resource_id": "pg-1"},
        ),
        MetricPoint(
            metric_name="redis_server_load",
            at=_T,
            value=92.0,
            labels={"resource_id": "redis-1"},
        ),
        MetricPoint(
            metric_name="key_vault_availability",
            at=_T,
            value=97.5,
            labels={"resource_id": "kv-1"},
        ),
    )
    provider = StaticMetricProvider(points)
    pg_findings = await postgresql_analyzer(provider, wall_clock=lambda: _T).analyze(
        resource_ref="pg-1", window_seconds=300.0
    )
    redis_findings = await redis_analyzer(provider, wall_clock=lambda: _T).analyze(
        resource_ref="redis-1", window_seconds=300.0
    )
    kv_findings = await key_vault_analyzer(provider, wall_clock=lambda: _T).analyze(
        resource_ref="kv-1", window_seconds=300.0
    )
    assert len(pg_findings) == 1 and pg_findings[0].signal == "postgresql_cpu"
    assert len(redis_findings) == 1 and redis_findings[0].signal == "redis_load"
    assert len(kv_findings) == 1 and kv_findings[0].signal == "key_vault_availability"


@pytest.mark.asyncio
async def test_p50_p99_and_cosmos_service_bus_analyzers() -> None:
    from fdai.core.investigation.analyzers import cosmos_db_analyzer, service_bus_analyzer
    from fdai.shared.providers.metric import MetricPoint

    assert reduce_values([10.0, 20.0, 30.0, 40.0], Aggregation.P50) == 20.0
    assert reduce_values([10.0, 20.0, 30.0, 100.0], Aggregation.P99) == 100.0
    with pytest.raises(ValueError, match="finite numbers"):
        reduce_values([1.0, float("nan")], Aggregation.MAX)
    with pytest.raises(ValueError, match="finite numbers"):
        reduce_values([True], Aggregation.MAX)  # type: ignore[list-item]

    points = (
        MetricPoint(
            metric_name="cosmos_normalized_ru_consumption_percent",
            at=_T,
            value=95.0,
            labels={"resource_id": "cosmos-1"},
        ),
        MetricPoint(
            metric_name="service_bus_dead_lettered_messages",
            at=_T,
            value=3.0,
            labels={"resource_id": "sb-1"},
        ),
    )
    provider = StaticMetricProvider(points)
    cosmos_findings = await cosmos_db_analyzer(provider, wall_clock=lambda: _T).analyze(
        resource_ref="cosmos-1", window_seconds=300.0
    )
    sb_findings = await service_bus_analyzer(provider, wall_clock=lambda: _T).analyze(
        resource_ref="sb-1", window_seconds=300.0
    )
    assert len(cosmos_findings) == 1 and cosmos_findings[0].signal == "cosmos_ru_saturation"
    assert len(sb_findings) == 1 and sb_findings[0].signal == "service_bus_dead_letter"


def test_recommendations_prefer_remediation_ref_on_same_severity_and_time() -> None:
    without_rem = AnalyzerFinding(
        resource_ref="r1",
        resource_kind="k",
        signal="cpu",
        observation="no remediation",
        severity=Severity.HIGH,
        occurred_at=_T,
        remediation_ref=None,
    )
    with_rem = AnalyzerFinding(
        resource_ref="r1",
        resource_kind="k",
        signal="cpu",
        observation="has remediation",
        severity=Severity.HIGH,
        occurred_at=_T,
        remediation_ref="ops.scale-out",
    )
    recs = build_recommendations([without_rem, with_rem])
    assert len(recs) == 1
    assert recs[0].remediation_ref == "ops.scale-out"


def test_sre_scenarios_slo_irp_warm_pool_and_chaos_invariants() -> None:
    from fdai.core.capacity.warm_pool import WarmCapacityConfig
    from fdai.core.chaos.contract import FaultScenario
    from fdai.core.chaos.sre_contracts import SreScenarioContract
    from fdai.core.investigation.coordinator import InvestigationRequest
    from fdai.core.irp.authoring import PlanNotReadyError, activate, pretest_plan
    from fdai.core.irp.models import (
        HistoricalIncident,
        PlanRequirement,
        PlanStatus,
        RequirementKind,
        ResponsePlan,
        ResponseStep,
    )
    from fdai.core.slo.burn_rate import BurnRate, BurnRateAlert
    from fdai.core.slo.models import BurnRateAlertDef, ErrorBudget

    req = InvestigationRequest(
        requested_by="op-1",
        resources=(("res-1", "aks_cluster"), ("res-1", "aks_cluster")),
    )
    assert req.resources == (("res-1", "aks_cluster"),)

    budget = ErrorBudget(slo_id="slo-1", good_events=90, total_events=100, objective_ratio=0.95)
    assert budget.burned_events == 10
    assert budget.is_exhausted is True
    with pytest.raises(ValueError, match="objective_ratio"):
        ErrorBudget(slo_id="slo-1", good_events=90, total_events=100, objective_ratio=1.5)

    alert_def = BurnRateAlertDef(
        name="fast",
        short_window_minutes=5,
        long_window_minutes=60,
        burn_rate_threshold=14.4,
    )
    with pytest.raises(ValueError, match="BurnRateAlert window"):
        BurnRateAlert(
            slo_id="slo-1",
            alert=alert_def,
            short=BurnRate(window_minutes=10, good_events=9, total_events=10, objective_ratio=0.99),
            long=BurnRate(window_minutes=60, good_events=9, total_events=10, objective_ratio=0.99),
        )

    plan = ResponsePlan(
        plan_id="p-1",
        name="Scale plan",
        trigger_signal="node_cpu",
        steps=(ResponseStep(step_id="s1", action_ref="ops.scale-out", description="scale"),),
        requirements=tuple(
            PlanRequirement(kind=k, description=k.value, satisfied=True) for k in RequirementKind
        ),
        approver_role="Operator",
        notify_channels=("teams",),
        created_by="op-1",
        created_at=_T,
        status=PlanStatus.RETIRED,
    )
    with pytest.raises(PlanNotReadyError, match="retired"):
        activate(plan)

    inc = HistoricalIncident(
        incident_ref="inc-1",
        signals=("node_cpu",),
        resolved_by_action="ops.scale-out",
    )
    pretest = pretest_plan(plan, (inc, inc))
    assert pretest.total == 1 and pretest.matched == 1

    with pytest.raises(ValueError, match="cold_min_replicas"):
        WarmCapacityConfig(cold_min_replicas=3, warm_min_replicas=2)

    with pytest.raises(ValueError, match="duration_seconds"):
        FaultScenario(
            scenario_id="s-1",
            fault_type="pod_kill",
            description="desc",
            target_selector="workload:api",
            expected_signal="pod_restart",
            blast_radius_cap=1,
            duration_seconds=float("nan"),
        )
    with pytest.raises(ValueError, match="SreScenarioContract"):
        SreScenarioContract(
            scenario_id=" ",
            title="t",
            fault=False,
            signals=("pod_restart",),
            causal_mechanism="m",
            chaos_scenario_id=None,
            recovery_probes=(),
            recovery_action_types=(),
        )
