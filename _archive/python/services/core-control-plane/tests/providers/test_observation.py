"""Wave M1.5 - Observation-depth Protocols + fakes."""

from __future__ import annotations

import pytest
from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentHistoryProvider,
    DeploymentHistoryResult,
    DeploymentRecord,
    IncidentCorrelation,
    IncidentCorrelationError,
    IncidentCorrelator,
    LogQueryError,
    LogQueryProvider,
    LogQueryResult,
    MetricQueryError,
    MetricQueryProvider,
    ObservationError,
)
from fdai.shared.providers.testing.observation import (
    InMemoryDeploymentHistoryProvider,
    InMemoryIncidentCorrelator,
    InMemoryLogQueryProvider,
    InMemoryMetricQueryProvider,
    make_log_row,
    make_metric_point,
)

# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_domain_errors_all_derive_from_observation_error() -> None:
    for err_cls in (
        LogQueryError,
        MetricQueryError,
        DeploymentHistoryError,
        IncidentCorrelationError,
    ):
        assert issubclass(err_cls, ObservationError)


def test_fakes_satisfy_the_protocols() -> None:
    assert isinstance(InMemoryLogQueryProvider(), LogQueryProvider)
    assert isinstance(InMemoryMetricQueryProvider(), MetricQueryProvider)
    assert isinstance(InMemoryDeploymentHistoryProvider(), DeploymentHistoryProvider)
    assert isinstance(InMemoryIncidentCorrelator(), IncidentCorrelator)


# ---------------------------------------------------------------------------
# Log query fake
# ---------------------------------------------------------------------------


async def test_log_query_returns_seeded_rows() -> None:
    fake = InMemoryLogQueryProvider()
    row = make_log_row(TimeGenerated="2026-07-07T00:00:00Z", Level="Error", Message="boom")
    fake.seed(
        "AzureActivity | where Level == 'Error'",
        LogQueryResult(rows=(row,), truncated=False, scanned_records=1),
    )
    result = await fake.query_log(
        query="AzureActivity | where Level == 'Error'",
        window="PT1H",
    )
    assert result.rows == (row,)
    assert result.truncated is False


async def test_log_query_returns_empty_when_unseeded() -> None:
    fake = InMemoryLogQueryProvider()
    result = await fake.query_log(query="unknown", window="PT1H")
    assert result.rows == ()
    assert result.scanned_records == 0


async def test_log_query_clips_to_max_rows_and_marks_truncated() -> None:
    fake = InMemoryLogQueryProvider()
    rows = tuple(make_log_row(idx=i) for i in range(10))
    fake.seed("q", LogQueryResult(rows=rows, truncated=False, scanned_records=10))
    result = await fake.query_log(query="q", window="PT1H", max_rows=3)
    assert len(result.rows) == 3
    assert result.truncated is True


async def test_log_query_next_error_raises_once() -> None:
    fake = InMemoryLogQueryProvider()
    fake.next_error(LogQueryError("kql syntax"))
    with pytest.raises(LogQueryError):
        await fake.query_log(query="q", window="PT1H")
    # Second call recovers to empty.
    result = await fake.query_log(query="q", window="PT1H")
    assert result.rows == ()


def test_log_query_records_calls() -> None:
    async def _run() -> None:
        fake = InMemoryLogQueryProvider()
        await fake.query_log(query="a", window="PT1H")
        await fake.query_log(query="b", window="PT2H", max_rows=5)
        assert fake.calls == (("a", "PT1H", 100), ("b", "PT2H", 5))

    import asyncio

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Metric query fake
# ---------------------------------------------------------------------------


async def test_metric_query_returns_seeded_points() -> None:
    fake = InMemoryMetricQueryProvider()
    points = (
        make_metric_point("2026-07-07T00:00:00Z", 1.0),
        make_metric_point("2026-07-07T00:05:00Z", 1.5),
    )
    fake.seed(
        namespace="Microsoft.Compute/virtualMachines",
        metric="Percentage CPU",
        aggregation="Average",
        points=points,
    )
    result = await fake.query_metric(
        namespace="Microsoft.Compute/virtualMachines",
        metric="Percentage CPU",
        aggregation="Average",
        window="PT5M",
    )
    assert result.points == points


async def test_metric_query_returns_empty_points_when_unseeded() -> None:
    fake = InMemoryMetricQueryProvider()
    result = await fake.query_metric(
        namespace="ns", metric="m", aggregation="Average", window="PT1M"
    )
    assert result.namespace == "ns"
    assert result.metric == "m"
    assert result.points == ()


async def test_metric_query_next_error_raises_once() -> None:
    fake = InMemoryMetricQueryProvider()
    fake.next_error(MetricQueryError("metrics 429"))
    with pytest.raises(MetricQueryError):
        await fake.query_metric(namespace="a", metric="b", aggregation="c", window="d")
    # Recovers.
    result = await fake.query_metric(namespace="a", metric="b", aggregation="c", window="d")
    assert result.points == ()


# ---------------------------------------------------------------------------
# Deployment-history fake
# ---------------------------------------------------------------------------


async def test_deployment_history_filters_by_resource() -> None:
    fake = InMemoryDeploymentHistoryProvider()
    fake.seed(
        DeploymentRecord(
            deployment_ref="d-1",
            timestamp="2026-07-07T00:00:00Z",
            author="alice",
            resource_refs=("rg/vm-a",),
            status="succeeded",
        )
    )
    fake.seed(
        DeploymentRecord(
            deployment_ref="d-2",
            timestamp="2026-07-07T01:00:00Z",
            author="bob",
            resource_refs=("rg/vm-b",),
            status="succeeded",
        )
    )
    all_records = await fake.query_deployments(window="PT1D")
    assert len(all_records.records) == 2

    only_vm_a = await fake.query_deployments(window="PT1D", resource_ref="rg/vm-a")
    assert len(only_vm_a.records) == 1
    assert only_vm_a.records[0].deployment_ref == "d-1"


async def test_deployment_history_next_error_raises_once() -> None:
    fake = InMemoryDeploymentHistoryProvider()
    fake.next_error(DeploymentHistoryError("arm 500"))
    with pytest.raises(DeploymentHistoryError):
        await fake.query_deployments(window="PT1D")
    # Recovers to empty.
    result = await fake.query_deployments(window="PT1D")
    assert isinstance(result, DeploymentHistoryResult)
    assert result.records == ()


# ---------------------------------------------------------------------------
# Incident correlator fake
# ---------------------------------------------------------------------------


async def test_incident_correlator_returns_seeded_correlation() -> None:
    fake = InMemoryIncidentCorrelator()
    seed = IncidentCorrelation(
        incident_id="INC-1",
        events=({"kind": "event", "id": "e-1"},),
        audit_entries=({"kind": "audit", "id": "a-1"},),
        log_hits=(),
        metric_points=(make_metric_point("2026-07-07T00:00:00Z", 1.0),),
        deployments=(),
    )
    fake.seed(seed)
    got = await fake.correlate(incident_id="INC-1")
    assert got == seed


async def test_incident_correlator_unknown_id_raises() -> None:
    fake = InMemoryIncidentCorrelator()
    with pytest.raises(IncidentCorrelationError):
        await fake.correlate(incident_id="INC-unknown")


async def test_incident_correlator_next_error_raises_once() -> None:
    fake = InMemoryIncidentCorrelator()
    fake.next_error(IncidentCorrelationError("transport"))
    with pytest.raises(IncidentCorrelationError):
        await fake.correlate(incident_id="INC-1")


# ---------------------------------------------------------------------------
# Result dataclass shape
# ---------------------------------------------------------------------------


def test_log_query_result_carries_metadata() -> None:
    r = LogQueryResult(rows=(), truncated=False, metadata={"scope": "sub-1"})
    assert r.metadata == {"scope": "sub-1"}


def test_metric_point_is_immutable() -> None:
    p = make_metric_point("2026-07-07T00:00:00Z", 1.0)
    with pytest.raises(AttributeError):
        p.value = 2.0  # type: ignore[misc]
