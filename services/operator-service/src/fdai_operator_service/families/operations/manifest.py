"""Exact legacy route manifest for the Operator operations family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fdai_service_contracts import OperatorRole

RouteKind = Literal["projection", "proposal", "stream", "webhook"]


@dataclass(frozen=True, slots=True)
class OperationRoute:
    """Declare one stable HTTP route and its non-authoritative service behavior."""

    path: str
    method: Literal["GET", "POST"]
    name: str
    operation: str
    kind: RouteKind = "projection"
    roles: frozenset[OperatorRole] = frozenset(
        {
            OperatorRole.READER,
            OperatorRole.CONTRIBUTOR,
            OperatorRole.APPROVER,
            OperatorRole.OWNER,
        }
    )


OPERATIONS_ROUTE_MANIFEST: tuple[OperationRoute, ...] = (
    OperationRoute("/inventory/graph", "GET", "handler", "inventory.graph"),
    OperationRoute("/ontology/graph", "GET", "handler", "ontology.graph"),
    OperationRoute("/pantheon/graph", "GET", "handler", "pantheon.graph"),
    OperationRoute("/pantheon/workflows", "GET", "handler", "pantheon.workflows"),
    OperationRoute("/views/workflow-apps", "GET", "list_workflow_apps", "process.apps"),
    OperationRoute("/views/process", "GET", "list_processes", "process.list"),
    OperationRoute("/views/process/{process_id:str}", "GET", "render_process", "process.detail"),
    OperationRoute(
        "/views/process/{process_id:str}/events",
        "GET",
        "process_events",
        "process.events",
    ),
    OperationRoute("/detection-readiness", "GET", "handler", "detection.readiness"),
    OperationRoute(
        "/automation-blueprints",
        "GET",
        "handler",
        "automation_blueprint.list",
    ),
    OperationRoute("/audit/{correlation_id}/what-if", "GET", "handler", "audit.what_if"),
    OperationRoute("/scope", "GET", "handler", "scope.effective"),
    OperationRoute("/stewardship", "GET", "handler", "stewardship.coverage"),
    OperationRoute("/reports", "GET", "list_reports", "report.list"),
    OperationRoute("/reports/registry", "GET", "get_registry", "report.registry"),
    OperationRoute("/reports/formats", "GET", "list_formats", "report.formats"),
    OperationRoute("/reports/widget-types", "GET", "list_widget_types", "report.widget_types"),
    OperationRoute("/reports/datasources", "GET", "list_datasource_names", "report.datasources"),
    OperationRoute("/reports/health", "GET", "get_health", "report.health"),
    OperationRoute("/reports/{report_id:str}", "GET", "get_report", "report.detail"),
    OperationRoute("/reports/{report_id:str}/render", "GET", "render_report", "report.render"),
    OperationRoute("/read-investigations", "POST", "start", "read_investigation.start", "proposal"),
    OperationRoute("/simulate/blast-radius", "GET", "handler", "blast_radius.simulate"),
    OperationRoute("/audit/{correlation_id}/bitemporal", "GET", "handler", "audit.bitemporal"),
    OperationRoute("/webhook", "POST", "handler", "webhook.generic", "webhook"),
    OperationRoute("/webhook/azure-monitor", "POST", "handler", "webhook.azure_monitor", "webhook"),
    OperationRoute("/provision/stream", "GET", "handler", "provision", "stream"),
)


__all__ = ["OPERATIONS_ROUTE_MANIFEST", "OperationRoute", "RouteKind"]
