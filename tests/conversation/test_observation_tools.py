"""Wave M1.5b - Observation-depth console tools (log/metric/deployments/incident)."""

from __future__ import annotations

from fdai.core.conversation import (
    CorrelateIncidentTool,
    QueryDeploymentsTool,
    QueryLogTool,
    QueryMetricTool,
)
from fdai.core.conversation.session import Principal, Role
from fdai.shared.providers.conversation_channel import (
    AgentHandoffActivity,
    ConversationExecutionStatus,
    ObservedExecutionActivity,
)
from fdai.shared.providers.observation import (
    DeploymentHistoryError,
    DeploymentRecord,
    IncidentCorrelation,
    IncidentCorrelationError,
    LogQueryError,
    LogQueryResult,
    MetricQueryError,
)
from fdai.shared.providers.testing.observation import (
    InMemoryDeploymentHistoryProvider,
    InMemoryIncidentCorrelator,
    InMemoryLogQueryProvider,
    InMemoryMetricQueryProvider,
    make_log_row,
    make_metric_point,
)


def _p(role: Role = Role.READER) -> Principal:
    return Principal(id="user-1", role=role)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_every_tool_is_reader_read_class() -> None:
    for tool_cls in (QueryLogTool, QueryMetricTool, QueryDeploymentsTool, CorrelateIncidentTool):
        assert tool_cls.rbac_floor is Role.READER, tool_cls
        assert tool_cls.side_effect_class == "read", tool_cls


# ---------------------------------------------------------------------------
# query_log
# ---------------------------------------------------------------------------


def test_query_log_returns_seeded_rows() -> None:
    prov = InMemoryLogQueryProvider()
    prov.seed(
        "AzureActivity",
        LogQueryResult(rows=(make_log_row(id="r1", msg="hi"),), truncated=False, scanned_records=1),
    )
    result = QueryLogTool(provider=prov).call(
        arguments={"query": "AzureActivity", "window": "PT1H"},
        principal=_p(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert data["rows"] == [{"id": "r1", "msg": "hi"}]
    assert data["truncated"] is False
    _assert_observation_activities(result, tool="query_log")


def test_query_log_empty_result_abstains() -> None:
    result = QueryLogTool(provider=InMemoryLogQueryProvider()).call(
        arguments={"query": "unknown", "window": "PT1H"},
        principal=_p(),
    )
    assert result.status == "abstain"


def test_query_log_provider_error_abstains_not_raises() -> None:
    prov = InMemoryLogQueryProvider()
    prov.next_error(LogQueryError("kql syntax"))
    result = QueryLogTool(provider=prov).call(
        arguments={"query": "bad", "window": "PT1H"},
        principal=_p(),
    )
    assert result.status == "abstain"
    assert "abstains" in (result.preview or "")


def test_query_log_missing_query_returns_error() -> None:
    result = QueryLogTool(provider=InMemoryLogQueryProvider()).call(
        arguments={"query": "  ", "window": "PT1H"},
        principal=_p(),
    )
    assert result.status == "error"
    assert "query" in (result.preview or "")


def test_query_log_missing_window_returns_error() -> None:
    result = QueryLogTool(provider=InMemoryLogQueryProvider()).call(
        arguments={"query": "x", "window": ""},
        principal=_p(),
    )
    assert result.status == "error"
    assert "window" in (result.preview or "")


def test_query_log_max_rows_default_and_cap() -> None:
    prov = InMemoryLogQueryProvider()
    rows = tuple(make_log_row(i=i) for i in range(600))
    prov.seed("q", LogQueryResult(rows=rows, truncated=False, scanned_records=600))
    # Default: 100 (still truncated by the fake below cap).
    result = QueryLogTool(provider=prov).call(
        arguments={"query": "q", "window": "PT1H"},
        principal=_p(),
    )
    assert result.status == "ok"
    assert len((result.data or {})["rows"]) == 100
    assert (result.data or {})["truncated"] is True


def test_query_log_max_rows_over_cap_raises() -> None:
    """``_optional_int`` validates the range; > 500 raises ValueError."""

    prov = InMemoryLogQueryProvider()
    prov.seed("q", LogQueryResult(rows=(make_log_row(i=0),), truncated=False, scanned_records=1))
    import pytest

    with pytest.raises(ValueError):
        QueryLogTool(provider=prov).call(
            arguments={"query": "q", "window": "PT1H", "max_rows": 5000},
            principal=_p(),
        )


# ---------------------------------------------------------------------------
# query_metric
# ---------------------------------------------------------------------------


def test_query_metric_returns_seeded_points() -> None:
    prov = InMemoryMetricQueryProvider()
    prov.seed(
        namespace="ns",
        metric="m",
        aggregation="Average",
        points=(
            make_metric_point("2026-07-07T00:00:00Z", 1.0),
            make_metric_point("2026-07-07T00:05:00Z", 2.0),
        ),
    )
    result = QueryMetricTool(provider=prov).call(
        arguments={
            "namespace": "ns",
            "metric": "m",
            "aggregation": "Average",
            "window": "PT5M",
        },
        principal=_p(),
    )
    assert result.status == "ok"
    points = (result.data or {})["points"]
    assert len(points) == 2
    assert points[0]["value"] == 1.0
    _assert_observation_activities(result, tool="query_metric")


def test_query_metric_empty_abstains() -> None:
    result = QueryMetricTool(provider=InMemoryMetricQueryProvider()).call(
        arguments={
            "namespace": "ns",
            "metric": "m",
            "aggregation": "Average",
            "window": "PT5M",
        },
        principal=_p(),
    )
    assert result.status == "abstain"


def test_query_metric_provider_error_abstains() -> None:
    prov = InMemoryMetricQueryProvider()
    prov.next_error(MetricQueryError("metrics 429"))
    result = QueryMetricTool(provider=prov).call(
        arguments={
            "namespace": "ns",
            "metric": "m",
            "aggregation": "Average",
            "window": "PT5M",
        },
        principal=_p(),
    )
    assert result.status == "abstain"


def test_query_metric_missing_arg_returns_error() -> None:
    result = QueryMetricTool(provider=InMemoryMetricQueryProvider()).call(
        arguments={"namespace": "ns", "metric": "  ", "aggregation": "Average", "window": "PT5M"},
        principal=_p(),
    )
    assert result.status == "error"
    assert "metric" in (result.preview or "")


# ---------------------------------------------------------------------------
# query_deployments
# ---------------------------------------------------------------------------


def test_query_deployments_returns_records() -> None:
    prov = InMemoryDeploymentHistoryProvider()
    prov.seed(
        DeploymentRecord(
            deployment_ref="d-1",
            timestamp="2026-07-07T00:00:00Z",
            author="alice",
            resource_refs=("rg/vm-a",),
            status="succeeded",
        )
    )
    result = QueryDeploymentsTool(provider=prov).call(
        arguments={"window": "P1D"},
        principal=_p(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert len(data["records"]) == 1
    assert data["records"][0]["deployment_ref"] == "d-1"
    assert result.evidence_refs == ("deployment:d-1",)
    _assert_observation_activities(result, tool="query_deployments")


def test_query_deployments_resource_ref_filter() -> None:
    prov = InMemoryDeploymentHistoryProvider()
    prov.seed(
        DeploymentRecord(
            deployment_ref="d-1",
            timestamp="t",
            author="a",
            resource_refs=("rg/vm-a",),
            status="succeeded",
        )
    )
    prov.seed(
        DeploymentRecord(
            deployment_ref="d-2",
            timestamp="t",
            author="b",
            resource_refs=("rg/vm-b",),
            status="succeeded",
        )
    )
    result = QueryDeploymentsTool(provider=prov).call(
        arguments={"window": "P1D", "resource_ref": "rg/vm-a"},
        principal=_p(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert [r["deployment_ref"] for r in data["records"]] == ["d-1"]


def test_query_deployments_empty_result_abstains() -> None:
    result = QueryDeploymentsTool(provider=InMemoryDeploymentHistoryProvider()).call(
        arguments={"window": "P1D"},
        principal=_p(),
    )
    assert result.status == "abstain"


def test_query_deployments_provider_error_abstains() -> None:
    prov = InMemoryDeploymentHistoryProvider()
    prov.next_error(DeploymentHistoryError("arm 500"))
    result = QueryDeploymentsTool(provider=prov).call(
        arguments={"window": "P1D"},
        principal=_p(),
    )
    assert result.status == "abstain"


def test_query_deployments_empty_window_returns_error() -> None:
    result = QueryDeploymentsTool(provider=InMemoryDeploymentHistoryProvider()).call(
        arguments={"window": "  "},
        principal=_p(),
    )
    assert result.status == "error"


# ---------------------------------------------------------------------------
# correlate_incident
# ---------------------------------------------------------------------------


def test_correlate_incident_returns_seeded_correlation() -> None:
    corr = InMemoryIncidentCorrelator()
    corr.seed(
        IncidentCorrelation(
            incident_id="INC-1",
            events=({"e": 1},),
            audit_entries=({"a": 1},),
            log_hits=(),
            metric_points=(make_metric_point("t", 1.0),),
            deployments=(
                DeploymentRecord(
                    deployment_ref="d-1",
                    timestamp="t",
                    author="a",
                    resource_refs=("rg/x",),
                    status="succeeded",
                ),
            ),
        )
    )
    result = CorrelateIncidentTool(correlator=corr).call(
        arguments={"incident_id": "INC-1"},
        principal=_p(),
    )
    assert result.status == "ok"
    data = result.data or {}
    assert data["incident_id"] == "INC-1"
    assert data["events"] == [{"e": 1}]
    assert data["deployments"][0]["deployment_ref"] == "d-1"
    assert result.evidence_refs == ("incident:INC-1",)
    _assert_observation_activities(result, tool="correlate_incident")


def _assert_observation_activities(result: object, *, tool: str) -> None:
    activities = result.activities  # type: ignore[attr-defined]
    assert len(activities) == 2
    assert activities[0] == AgentHandoffActivity(
        from_agent="Bragi",
        to_agent="Heimdall",
        task=f"{activities[1].label} with a read-only server tool.",
    )
    execution = activities[1]
    assert isinstance(execution, ObservedExecutionActivity)
    assert execution.agent == "Heimdall"
    assert execution.tool == tool
    assert execution.status is ConversationExecutionStatus.COMPLETED
    assert execution.redacted is True
    assert execution.output


def test_correlate_incident_unknown_id_abstains() -> None:
    result = CorrelateIncidentTool(correlator=InMemoryIncidentCorrelator()).call(
        arguments={"incident_id": "INC-missing"},
        principal=_p(),
    )
    assert result.status == "abstain"
    assert "INC-missing" in (result.preview or "")


def test_correlate_incident_error_abstains() -> None:
    corr = InMemoryIncidentCorrelator()
    corr.next_error(IncidentCorrelationError("boom"))
    result = CorrelateIncidentTool(correlator=corr).call(
        arguments={"incident_id": "INC-1"},
        principal=_p(),
    )
    assert result.status == "abstain"


def test_correlate_incident_empty_id_returns_error() -> None:
    result = CorrelateIncidentTool(correlator=InMemoryIncidentCorrelator()).call(
        arguments={"incident_id": "  "},
        principal=_p(),
    )
    assert result.status == "error"
