"""Focused tests for authoritative Incident RCA report materialization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.reporting.incident_rca_projection import (
    IncidentRcaReportingProjectionReader,
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


def _query(operation: str, *, correlation: str | None = None) -> ProjectionQuery:
    return ProjectionQuery(
        operation=operation,
        principal_id="reader",
        path={"report_id": "incident-rca-dossier"},
        params={"correlation_id": (correlation,)} if correlation is not None else {},
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
    assert cast(dict[str, object], hypotheses["data"])["total_rows"] == 1
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
