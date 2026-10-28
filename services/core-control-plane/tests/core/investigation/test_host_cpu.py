"""Host CPU keeps peak defaults, exact identities and bounded recovery semantics."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.investigation.analyzer import Aggregation
from fdai.core.investigation.host_cpu import (
    KIND_VIRTUAL_MACHINE_SCALE_SET,
    METRIC_HOST_CPU_PERCENT,
    METRIC_VMSS_CPU_PERCENT,
    HostCpuAnalyzer,
    HostCpuPolicy,
    assess_host_cpu,
)
from fdai.shared.providers.metric import MetricPoint, MetricProviderError, StaticMetricProvider

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
SINCE = NOW - timedelta(minutes=5)
REF = "scope-example/resource-group/example/compute/example"


def _points(value=20.0, metric=METRIC_HOST_CPU_PERCENT):
    return tuple(
        MetricPoint(metric, SINCE + timedelta(minutes=minute), value, {"resource_id": REF})
        for minute in range(1, 6)
    )


def _assess(points, **kwargs):
    return assess_host_cpu(
        points,
        resource_ref=REF,
        metric_name=METRIC_HOST_CPU_PERCENT,
        since=SINCE,
        until=NOW,
        policy=kwargs.pop("policy", HostCpuPolicy()),
        **kwargs,
    )


def test_peak_default_is_not_silently_changed_to_average_or_sustained() -> None:
    points = (*_points()[:-1], replace(_points()[-1], value=90.0))
    assert _assess(points).status == "cpu_threshold_observed"
    assert _assess(points, policy=HostCpuPolicy(aggregation=Aggregation.AVG)).status == (
        "cpu_below_threshold"
    )


@pytest.mark.parametrize("aggregation", ["max", Aggregation.SUM, "unsupported"])
def test_cpu_policy_requires_typed_supported_aggregation(aggregation) -> None:
    with pytest.raises(ValueError, match="aggregation"):
        HostCpuPolicy(aggregation=aggregation)


@pytest.mark.parametrize(
    ("points", "status"),
    [
        ((), "metrics_missing"),
        (_points()[:1], "stale"),
        (_points()[2:], "insufficient_evidence"),
        ((_points()[0], _points()[2], _points()[4]), "insufficient_evidence"),
        ((replace(_points()[0], metric_name="cpu_percent"),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], labels={}),), "metric_identity_or_value_invalid"),
        (
            (replace(_points()[0], labels={"resource_id": "another-resource"}),),
            "metric_identity_or_value_invalid",
        ),
        ((replace(_points()[0], value=float("nan")),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], value=float("inf")),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], value=-1),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], value=101),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], at=NOW.replace(tzinfo=None)),), "metric_identity_or_value_invalid"),
        ((replace(_points()[0], at=NOW + timedelta(seconds=1)),), "metric_time_outside_window"),
        ((replace(_points()[0], at=SINCE - timedelta(seconds=1)),), "metric_time_outside_window"),
        ((*_points(), _points()[-1]), "metric_series_ambiguous"),
    ],
)
def test_absent_stale_wrong_scope_or_invalid_metrics_never_prove_recovery(points, status) -> None:
    result = _assess(points, prior_fault_at=SINCE, prior_finding_ref="finding:example")
    assert result.status == status
    assert not result.evidence_complete
    assert result.recovery_closed is None


def test_healthy_reading_alone_is_not_recovery() -> None:
    result = _assess(_points())
    assert result.evidence_complete
    assert result.recovery_closed is None
    assert (
        _assess(
            _points(), prior_fault_at=SINCE, prior_finding_ref="finding:example"
        ).recovery_closed
        is True
    )
    assert (
        _assess(_points(), prior_fault_at=NOW, prior_finding_ref="finding:example").recovery_closed
        is False
    )


async def test_routine_healthy_cpu_does_not_create_new_findings() -> None:
    analyzer = HostCpuAnalyzer(StaticMetricProvider(_points()), wall_clock=lambda: NOW)
    assert not await analyzer.analyze(resource_ref=REF, window_seconds=300)


async def test_cpu_fault_and_prior_bound_recovery_replay_the_same_typed_assessment() -> None:
    clock = [NOW]
    points = _points(95) + tuple(
        replace(point, at=point.at + timedelta(minutes=5)) for point in _points()
    )
    analyzer = HostCpuAnalyzer(StaticMetricProvider(points), wall_clock=lambda: clock[0])
    (fault,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert fault.signal == "host_cpu"
    assert fault.remediation_ref is None
    assert fault.assessment.status == "cpu_threshold_observed"
    clock[0] += timedelta(minutes=5, seconds=1)
    (recovery,) = await analyzer.analyze_recovery(
        prior_finding=fault, finding_ref="finding:cpu-example", window_seconds=300
    )
    assert recovery.assessment.recovery_closed is True
    saved = json.loads(recovery.metadata["assessment_input"])
    result = assess_host_cpu(
        tuple(
            MetricPoint(
                item["metric_name"],
                datetime.fromisoformat(item["at"]),
                item["value"],
                item["labels"],
            )
            for item in saved["points"]
        ),
        resource_ref=saved["resource_ref"],
        metric_name=saved["metric_name"],
        since=datetime.fromisoformat(saved["since"]),
        until=datetime.fromisoformat(saved["until"]),
        policy=HostCpuPolicy(
            **{**saved["policy"], "aggregation": Aggregation(saved["policy"]["aggregation"])}
        ),
        prior_fault_at=datetime.fromisoformat(saved["prior_fault_at"]),
        prior_finding_ref=saved["prior_finding_ref"],
    )
    assert result == recovery.assessment


async def test_vmss_uses_an_additive_metric_name_not_mysql_cpu_percent() -> None:
    analyzer = HostCpuAnalyzer(
        StaticMetricProvider(_points(95, METRIC_VMSS_CPU_PERCENT)),
        resource_kind=KIND_VIRTUAL_MACHINE_SCALE_SET,
        wall_clock=lambda: NOW,
    )
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.resource_kind == KIND_VIRTUAL_MACHINE_SCALE_SET
    assert (
        json.loads(finding.metadata["assessment_input"])["metric_name"] == METRIC_VMSS_CPU_PERCENT
    )


@pytest.mark.parametrize("status", [403, 500])
async def test_provider_failure_after_partial_healthy_points_cannot_clear_a_fault(status) -> None:
    class Provider:
        async def query(self, query):
            yield _points()[-1]
            raise MetricProviderError("private", http_status=status)

    analyzer = HostCpuAnalyzer(Provider(), wall_clock=lambda: NOW)
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == (
        "authorization_denied" if status == 403 else "source_unavailable"
    )
    assert finding.assessment.recovery_closed is None
    assert "private" not in repr(finding)


async def test_bounded_point_limit_cannot_clear_recovery() -> None:
    analyzer = HostCpuAnalyzer(
        StaticMetricProvider(_points()),
        policy=HostCpuPolicy(max_points=2),
        wall_clock=lambda: NOW,
    )
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == "point_limit"
    assert finding.assessment.recovery_closed is None


async def test_wrong_provider_identity_and_dimension_values_never_leak_into_finding() -> None:
    wrong_identity = "/subscriptions/private/providers/compute/private"
    dimension = "private-instance-name"

    class Provider:
        async def query(self, query):
            yield replace(
                _points()[-1],
                labels={
                    "resource_id": wrong_identity,
                    "instance": dimension,
                },
            )

    analyzer = HostCpuAnalyzer(Provider(), wall_clock=lambda: NOW)
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == "metric_identity_or_value_invalid"
    assert wrong_identity not in repr(finding)
    assert dimension not in repr(finding)


async def test_query_timeout_does_not_close_a_fault() -> None:
    import asyncio

    class Provider:
        async def query(self, query):
            await asyncio.sleep(0.1)
            yield _points()[-1]

    analyzer = HostCpuAnalyzer(
        Provider(),
        policy=HostCpuPolicy(query_timeout_seconds=0.001),
        wall_clock=lambda: NOW,
    )
    (finding,) = await analyzer.analyze(resource_ref=REF, window_seconds=300)
    assert finding.assessment.status == "source_timeout"
    assert finding.assessment.recovery_closed is None
