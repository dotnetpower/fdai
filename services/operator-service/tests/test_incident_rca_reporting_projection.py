"""Focused tests for authoritative Incident RCA report materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    ChaosResult,
    PostgresChaosResultReader,
)
from fdai_operator_service.reporting.incident_rca_projection import (
    IncidentRcaReportingProjectionReader,
    postgres_incident_rca_reporting_projection,
)
from fdai_service_contracts import AuditQuery, JsonObject, PageProjection


class Fallback:
    async def read(self, query: ProjectionQuery) -> dict[str, object]:
        return {"operation": query.operation}


class AuditReader:
    def __init__(self, items: tuple[JsonObject, ...], *, next_cursor: str | None = None) -> None:
        self.items = items
        self.next_cursor = next_cursor
        self.queries: list[AuditQuery] = []

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        self.queries.append(query)
        return PageProjection(items=self.items, next_cursor=self.next_cursor)


class ChaosReader:
    def __init__(self, results: tuple[ChaosResult, ...]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    async def list_results(self, **kwargs: object) -> tuple[ChaosResult, ...]:
        self.calls.append(kwargs)
        return self.results


def _query(
    operation: str,
    *,
    correlation: str | None = None,
    report_id: str = "incident-rca-dossier",
    window_days: str | None = None,
) -> ProjectionQuery:
    params: dict[str, tuple[str, ...]] = {}
    if correlation is not None:
        params["correlation_id"] = (correlation,)
    if window_days is not None:
        params["window_days"] = (window_days,)
    return ProjectionQuery(
        operation=operation,
        principal_id="reader",
        path={"report_id": report_id},
        params=params,
        limit=100,
        cursor=None,
    )


def _item(seq: int, action_kind: str, entry: JsonObject) -> JsonObject:
    return {
        "seq": seq,
        "event_id": f"event-{seq}",
        "correlation_id": "corr-1",
        "actor": "saga",
        "action_kind": action_kind,
        "mode": "shadow",
        "entry": entry,
        "entry_hash": f"hash-{seq}",
        "previous_hash": f"hash-{seq - 1}",
        "recorded_at": datetime(2026, 8, 14, 1, seq, tzinfo=UTC).isoformat(),
    }


def test_postgres_factory_binds_measured_chaos_reader() -> None:
    projection = postgres_incident_rca_reporting_projection(
        Fallback(),
        cast(object, AuditReader(())),
        dsn="postgresql://example",
        statement_timeout_ms=1_000,
        connect_timeout_s=2,
    )

    assert isinstance(projection.chaos_results, PostgresChaosResultReader)


@pytest.mark.asyncio
async def test_catalog_registry_and_unrelated_projection_contracts() -> None:
    reader = IncidentRcaReportingProjectionReader(Fallback(), cast(object, AuditReader(())))

    catalog = await reader.read(_query("report.list"))
    registry = await reader.read(_query("report.registry"))
    delegated = await reader.read(_query("scope.list"))

    assert catalog["items"][0]["id"] == "incident-rca-dossier"  # type: ignore[index]
    assert catalog["items"][0]["widget_count"] == 15  # type: ignore[index]
    assert registry == {
        "datasources": ["audit"],
        "datasource_provenance": [
            {
                "datasource": "audit",
                "source": "audit_log",
                "availability": "available",
                "synthetic": False,
                "as_of": None,
            }
        ],
        "widgets": ["query_value", "table"],
        "formats": ["json"],
    }
    assert delegated == {"operation": "scope.list"}


@pytest.mark.asyncio
async def test_configured_chaos_results_extend_catalog_and_render_measured_rows() -> None:
    ended_at = datetime(2026, 9, 21, 11, 2, tzinfo=UTC)
    chaos = ChaosReader(
        (
            ChaosResult(
                signal_id="chaos-1",
                severity="high",
                resource_ref="app=example",
                occurred_at=ended_at,
                scenario_id="vm-mem-stress",
                outcome="not_detected",
                mode="enforce",
                expected_signal="host_memory",
                detected=False,
                reverted=True,
                injected=True,
                stopped=True,
                approval_ref="approval:test-sweep",
            ),
        )
    )
    reader = IncidentRcaReportingProjectionReader(Fallback(), cast(object, AuditReader(())), chaos)

    catalog = await reader.read(_query("report.list"))
    registry = await reader.read(_query("report.registry"))
    report = await reader.read(
        _query(
            "report.render",
            report_id="chaos-enforce-results",
            window_days="7",
        )
    )

    assert [item["id"] for item in catalog["items"]] == [  # type: ignore[index]
        "incident-rca-dossier",
        "chaos-enforce-results",
    ]
    assert registry["datasources"] == ["audit", "chaos_results"]
    assert report["provenance"]["synthetic"] is False  # type: ignore[index]
    widgets = cast(list[dict[str, object]], report["widgets"])
    rows = cast(dict[str, object], widgets[-1]["data"])["rows"]
    assert rows == [
        {
            "scenario": "vm-mem-stress",
            "outcome": "not_detected",
            "detected": False,
            "reverted": True,
            "severity": "high",
            "target": "app=example",
            "expected_signal": "host_memory",
            "at": ended_at.isoformat(),
        }
    ]


@pytest.mark.asyncio
async def test_chaos_report_rejects_unsupported_window_before_reading() -> None:
    chaos = ChaosReader(())
    reader = IncidentRcaReportingProjectionReader(
        Fallback(),
        cast(object, AuditReader(())),
        chaos,
    )

    with pytest.raises(ValueError, match="one of 1, 7, or 30"):
        await reader.read(
            _query(
                "report.render",
                report_id="chaos-enforce-results",
                window_days="365",
            )
        )

    assert chaos.calls == []


@pytest.mark.asyncio
async def test_render_projects_only_recorded_audit_evidence() -> None:
    audit = AuditReader(
        (
            _item(
                1,
                "incident.open",
                {
                    "incident_id": "incident-1",
                    "title": "Example incident",
                    "severity": "high",
                    "state": "open",
                    "vertical": "resilience",
                },
            ),
            _item(
                2,
                "rca.hypothesis",
                {
                    "rca_tier": "t1",
                    "rca_outcome": "grounded",
                    "rca_cause_domain": "shared_dependency",
                    "rca_cause": "Recorded cause",
                    "rca_confidence": 0.8,
                    "rca_citations": [{"kind": "event", "ref": "event-1"}],
                },
            ),
        )
    )
    reader = IncidentRcaReportingProjectionReader(Fallback(), cast(object, audit))

    report = await reader.read(_query("report.render", correlation="corr-1"))

    widgets = cast(list[dict[str, object]], report["widgets"])
    hypotheses = next(item for item in widgets if item["id"] == "root-cause-hypotheses")
    citations = next(item for item in widgets if item["id"] == "grounded-citations")
    limitations = next(item for item in widgets if item["id"] == "limitations")
    assert report["variables"] == {"correlation_id": "corr-1"}
    hypothesis_data = cast(dict[str, object], hypotheses["data"])
    assert hypothesis_data["total_rows"] == 1
    assert hypothesis_data["rows"][0]["cause_domain"] == "shared_dependency"  # type: ignore[index]
    assert cast(dict[str, object], citations["data"])["total_rows"] == 1
    assert cast(dict[str, object], limitations["data"])["total_rows"] == 0
    assert audit.queries == [AuditQuery(limit=500, correlation_id="corr-1")]


@pytest.mark.asyncio
async def test_render_rejects_missing_or_unknown_evidence() -> None:
    reader = IncidentRcaReportingProjectionReader(Fallback(), cast(object, AuditReader(())))

    with pytest.raises(ValueError, match="correlation_id MUST"):
        await reader.read(_query("report.render"))
    with pytest.raises(ProjectionUnavailableError, match="audit evidence"):
        await reader.read(_query("report.render", correlation="corr-1"))
