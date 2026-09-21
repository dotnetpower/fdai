"""Materialize the Incident RCA dossier from authoritative Operator audit rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts import AuditQuery, JsonObject, OperatorReadModel

from fdai_operator_service.families.operations.contracts import (
    ProjectionQuery,
    ProjectionReader,
    ProjectionUnavailableError,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    REPORT_ID as CHAOS_REPORT_ID,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    ChaosResultReader,
    PostgresChaosResultReader,
    PostgresChaosResultReaderConfig,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    registry_source as chaos_registry_source,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    render_report as render_chaos_report,
)
from fdai_operator_service.reporting.chaos_results_projection import (
    report_summary as chaos_report_summary,
)
from fdai_operator_service.reporting.incident_rca_descriptor import (
    REPORT_DESCRIPTION as _REPORT_DESCRIPTION,
)
from fdai_operator_service.reporting.incident_rca_descriptor import (
    REPORT_ID,
)
from fdai_operator_service.reporting.incident_rca_descriptor import (
    REPORT_NAME as _REPORT_NAME,
)
from fdai_operator_service.reporting.incident_rca_descriptor import (
    REPORT_TAGS as _TAGS,
)
from fdai_operator_service.reporting.incident_rca_descriptor import (
    TABLE_SPECS as _TABLE_SPECS,
)


@dataclass(frozen=True, slots=True)
class IncidentRcaReportingProjectionReader:
    """Serve the built-in Incident dossier and delegate unrelated operations."""

    fallback: ProjectionReader
    read_model: OperatorReadModel
    chaos_results: ChaosResultReader | None = None

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        if query.operation == "report.list":
            return _report_list(include_chaos=self.chaos_results is not None)
        if query.operation == "report.registry":
            return _registry(include_chaos=self.chaos_results is not None)
        if query.operation == "report.formats":
            return {"items": [{"name": "json", "content_type": "application/json"}]}
        if query.operation != "report.render":
            return await self.fallback.read(query)
        report_id = query.path.get("report_id")
        if report_id == CHAOS_REPORT_ID:
            if self.chaos_results is None:
                raise ProjectionUnavailableError("chaos result projection is unavailable")
            return await render_chaos_report(
                self.chaos_results,
                window_days=_window_days(query.params),
            )
        if report_id != REPORT_ID:
            raise ProjectionUnavailableError("unknown report")
        correlations = query.params.get("correlation_id", ())
        if len(correlations) != 1 or not correlations[0].strip():
            raise ValueError("correlation_id MUST be supplied exactly once")
        page = await self.read_model.list_audit(
            AuditQuery(limit=500, correlation_id=correlations[0].strip())
        )
        if not page.items:
            raise ProjectionUnavailableError("incident audit evidence is unavailable")
        return _render_report(
            page.items,
            correlation_id=correlations[0].strip(),
            partial=page.next_cursor is not None,
        )


def postgres_incident_rca_reporting_projection(
    fallback: ProjectionReader,
    read_model: OperatorReadModel,
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
) -> IncidentRcaReportingProjectionReader:
    return IncidentRcaReportingProjectionReader(
        fallback,
        read_model,
        PostgresChaosResultReader(
            PostgresChaosResultReaderConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
    )


def _report_list(*, include_chaos: bool) -> Mapping[str, object]:
    items: list[Mapping[str, object]] = [
        {
            "id": REPORT_ID,
            "version": "1.0.0",
            "name": _REPORT_NAME,
            "description": _REPORT_DESCRIPTION,
            "tags": list(_TAGS),
            "widget_count": len(_TABLE_SPECS) + 1,
            "datasources": ["audit"],
            "variables": [
                {
                    "name": "correlation_id",
                    "default": "",
                    "values": [],
                    "description": "Correlation id that scopes every widget in this report.",
                }
            ],
        }
    ]
    if include_chaos:
        items.append(chaos_report_summary())
    return {
        "items": items,
        "formats": ["json"],
    }


def _registry(*, include_chaos: bool) -> Mapping[str, object]:
    datasources = ["audit"]
    provenance: list[Mapping[str, object]] = [
        {
            "datasource": "audit",
            "source": "audit_log",
            "availability": "available",
            "synthetic": False,
            "as_of": None,
        }
    ]
    if include_chaos:
        datasources.append("chaos_results")
        provenance.append(chaos_registry_source())
    return {
        "datasources": datasources,
        "datasource_provenance": provenance,
        "widgets": ["query_value", "table"],
        "formats": ["json"],
    }


def _window_days(params: Mapping[str, Sequence[str]]) -> int:
    values = params.get("window_days", ())
    if len(values) != 1:
        raise ValueError("window_days MUST be supplied exactly once")
    try:
        window_days = int(values[0])
    except ValueError as exc:
        raise ValueError("window_days MUST be an integer") from exc
    if window_days not in {1, 7, 30}:
        raise ValueError("window_days MUST be one of 1, 7, or 30")
    return window_days


def _render_report(
    items: Sequence[JsonObject], *, correlation_id: str, partial: bool
) -> Mapping[str, object]:
    ordered = sorted(items, key=lambda item: _integer(item.get("seq")))
    timestamps = [str(item["recorded_at"]) for item in ordered]
    entries = [_mapping(item.get("entry")) for item in ordered]
    widgets: list[Mapping[str, object]] = [
        {
            "id": "evidence-record-count",
            "type": "query_value",
            "title": "Correlated audit records",
            "data": {"value": len(ordered), "unit": "records"},
            "options": {"unit": "records"},
        }
    ]
    for widget_id, title, projection, columns in _TABLE_SPECS:
        rows = _projection_rows(projection, ordered, entries, correlation_id)
        widgets.append(
            {
                "id": widget_id,
                "type": "table",
                "title": title,
                "data": {
                    "columns": list(columns),
                    "rows": [{column: row.get(column) for column in columns} for row in rows],
                    "total_rows": len(rows),
                },
                "options": {},
            }
        )
    generated_at = datetime.now(UTC).isoformat()
    source = {
        "datasource": "audit",
        "source": "audit_log",
        "availability": "available",
        "synthetic": False,
        "as_of": timestamps[-1],
    }
    return {
        "id": REPORT_ID,
        "version": "1.0.0",
        "name": _REPORT_NAME,
        "description": _REPORT_DESCRIPTION,
        "generated_at": generated_at,
        "time_range": {"from": timestamps[0], "to": timestamps[-1]},
        "variables": {"correlation_id": correlation_id},
        "widgets": widgets,
        "tags": list(_TAGS),
        "provenance": {
            "availability": "partial" if partial else "available",
            "synthetic": False,
            "sources": [source],
        },
    }


def _projection_rows(
    projection: str,
    items: Sequence[JsonObject],
    entries: Sequence[Mapping[str, Any]],
    correlation_id: str,
) -> list[Mapping[str, object]]:
    if projection == "profile":
        return [
            {
                "correlation_id": correlation_id,
                "incident_id": _first(entries, "incident_id"),
                "title": _first(entries, "incident_title", "title"),
                "severity": _first(entries, "severity"),
                "status": _last(entries, "incident_status", "status", "to_state", "state"),
                "vertical": _first(entries, "vertical"),
                "opened_at": str(items[0]["recorded_at"]),
                "last_updated_at": str(items[-1]["recorded_at"]),
                "audit_records": len(items),
            }
        ]
    if projection == "milestones":
        return [
            {
                "recorded_at": item["recorded_at"],
                "actor": item["actor"],
                "action_kind": item["action_kind"],
                "decision": entry.get("decision") or entry.get("gate_decision"),
                "outcome": entry.get("outcome") or entry.get("status"),
                "mode": item["mode"],
                "summary": _first((entry,), "summary", "detail", "reason"),
            }
            for item, entry in zip(items, entries, strict=True)
        ]
    if projection == "hypotheses":
        return [
            {
                "tier": entry.get("rca_tier"),
                "outcome": entry.get("rca_outcome"),
                "cause_domain": entry.get("rca_cause_domain") or "unknown",
                "cause": entry.get("rca_cause"),
                "confidence": entry.get("rca_confidence"),
                "reason": entry.get("rca_reason"),
                "remediation_ref": entry.get("rca_remediation_ref"),
                "mode": item["mode"],
                "recorded_at": item["recorded_at"],
            }
            for item, entry in zip(items, entries, strict=True)
            if item.get("action_kind") == "rca.hypothesis"
        ]
    if projection == "citations":
        return _citation_rows(items, entries)
    if projection == "causal_hops":
        return _causal_rows(entries)
    if projection == "response":
        return [
            {
                "action_kind": item["action_kind"],
                "decision": entry.get("decision") or entry.get("gate_decision"),
                "outcome": entry.get("outcome") or entry.get("status"),
                "mode": item["mode"],
                "rollback_reference": entry.get("rollback_reference") or entry.get("rollback_ref"),
                "actor": item["actor"],
                "recorded_at": item["recorded_at"],
            }
            for item, entry in reversed(tuple(zip(items, entries, strict=True)))
            if item.get("action_kind") != "rca.hypothesis"
        ]
    if projection == "audit":
        return [
            {
                key: item.get(key)
                for key in ("seq", "recorded_at", "actor", "action_kind", "mode", "entry_hash")
            }
            for item in items
        ]
    return _recorded_list(entries, projection)


def _citation_rows(
    items: Sequence[JsonObject], entries: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for item, entry in zip(items, entries, strict=True):
        if item.get("action_kind") != "rca.hypothesis":
            continue
        for citation in _mappings(entry.get("rca_citations")):
            if citation.get("kind") and citation.get("ref"):
                rows.append(
                    {
                        "tier": entry.get("rca_tier"),
                        "kind": citation["kind"],
                        "ref": citation["ref"],
                        "summary": citation.get("summary"),
                        "source_at": citation.get("source_at"),
                        "freshness": citation.get("freshness"),
                        "recorded_at": item["recorded_at"],
                    }
                )
    return rows


def _causal_rows(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for entry in entries:
        chain = _mapping(entry.get("rca_causal_chain"))
        for index, hop in enumerate(_mappings(chain.get("hops")), start=1):
            rows.append({"hop": index, **hop})
    return rows


def _recorded_list(entries: Sequence[Mapping[str, Any]], key: str) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for entry in entries:
        value = entry.get(key)
        values = (value,) if isinstance(value, Mapping) else value
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            rows.extend(dict(item) for item in values if isinstance(item, Mapping))
    return rows


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _first(entries: Sequence[Mapping[str, Any]], *keys: str) -> object | None:
    for entry in entries:
        for key in keys:
            value: object = entry.get(key)
            if value is not None and value != "":
                return value
    return None


def _last(entries: Sequence[Mapping[str, Any]], *keys: str) -> object | None:
    return _first(tuple(reversed(entries)), *keys)


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProjectionUnavailableError("audit sequence is malformed")
    return value


__all__ = [
    "IncidentRcaReportingProjectionReader",
    "REPORT_ID",
    "postgres_incident_rca_reporting_projection",
]
