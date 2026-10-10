"""Exact legacy route manifest for the Operator operations family."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from fdai_service_contracts import OperatorRole

RouteKind = Literal["projection", "proposal", "stream", "webhook"]

READ_ROLES: Final[frozenset[OperatorRole]] = frozenset(
    {
        OperatorRole.READER,
        OperatorRole.CONTRIBUTOR,
        OperatorRole.APPROVER,
        OperatorRole.OWNER,
    }
)
CONTRIBUTOR_ROLES: Final[frozenset[OperatorRole]] = frozenset(
    {OperatorRole.CONTRIBUTOR, OperatorRole.OWNER}
)
# A review decision carries human approval, so it starts at the approver rung.
# Contributor can propose a blueprint but never accept, reject, or materialize one.
APPROVER_ROLES: Final[frozenset[OperatorRole]] = frozenset(
    {OperatorRole.APPROVER, OperatorRole.OWNER}
)
# Changing which repositories FDAI may scan is an Owner decision.
OWNER_ROLES: Final[frozenset[OperatorRole]] = frozenset({OperatorRole.OWNER})


@dataclass(frozen=True, slots=True)
class OperationRoute:
    """Declare one stable HTTP route and its non-authoritative service behavior."""

    path: str
    method: Literal["GET", "POST"]
    name: str
    operation: str
    kind: RouteKind = "projection"
    roles: frozenset[OperatorRole] = READ_ROLES


OPERATIONS_ROUTE_MANIFEST: tuple[OperationRoute, ...] = (
    OperationRoute(
        "/observer-deployment-proposals",
        "GET",
        "observer_deployment_proposals",
        "observer.deployment.proposals",
    ),
    OperationRoute("/inventory/graph", "GET", "handler", "inventory.graph"),
    OperationRoute("/ontology/graph", "GET", "handler", "ontology.graph"),
    OperationRoute(
        "/ontology/instances",
        "GET",
        "ontology_instances",
        "ontology.instance.list",
    ),
    OperationRoute(
        "/ontology/instances/states",
        "GET",
        "ontology_instance_states",
        "ontology.instance.states",
    ),
    OperationRoute(
        "/ontology/instances/explore",
        "GET",
        "ontology_instance_explore",
        "ontology.instance.explore",
    ),
    OperationRoute(
        "/ontology/instances/stream",
        "GET",
        "ontology_instances_stream",
        "ontology.inventory.invalidations",
        "stream",
    ),
    OperationRoute(
        "/ontology/declarations/{kind:str}/{name:str}",
        "GET",
        "ontology_declaration_detail",
        "ontology.declaration.detail",
    ),
    OperationRoute(
        "/ontology/declarations/{kind:str}/{name:str}/dependents",
        "GET",
        "ontology_declaration_dependents",
        "ontology.declaration.dependents",
    ),
    OperationRoute(
        "/ontology/releases/{candidate_digest:str}/diff",
        "GET",
        "ontology_release_diff",
        "ontology.release.diff",
    ),
    OperationRoute(
        "/ontology/object-types/{name:str}/evidence-health",
        "GET",
        "ontology_object_type_evidence_health",
        "ontology.evidence.health",
    ),
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
    OperationRoute("/detection-coverage", "GET", "handler", "detection.readiness"),
    OperationRoute("/detection-readiness", "GET", "handler", "detection.readiness"),
    OperationRoute(
        "/automation-blueprints",
        "GET",
        "handler",
        "automation_blueprint.list",
    ),
    OperationRoute(
        "/automation-blueprints/accept",
        "POST",
        "handler",
        "automation_blueprint.accept",
        "proposal",
        APPROVER_ROLES,
    ),
    OperationRoute(
        "/automation-blueprints/reject",
        "POST",
        "handler",
        "automation_blueprint.reject",
        "proposal",
        APPROVER_ROLES,
    ),
    OperationRoute(
        "/automation-blueprints/materialize",
        "POST",
        "handler",
        "automation_blueprint.materialize",
        "proposal",
        APPROVER_ROLES,
    ),
    OperationRoute("/audit/{correlation_id}/what-if", "GET", "handler", "audit.what_if"),
    OperationRoute("/scope", "GET", "handler", "scope.effective"),
    OperationRoute("/stewardship", "GET", "handler", "stewardship.coverage"),
    OperationRoute("/assurance-twin/posture", "GET", "handler", "assurance_twin.posture"),
    OperationRoute("/assurance-twin/reviews", "GET", "handler", "assurance_twin.reviews"),
    # The review identity is opaque twin evidence that may contain a slash
    # (for example ``owner/repo#12``), so it travels as an exact query value
    # instead of a path segment that a router would split or canonicalise.
    OperationRoute("/assurance-twin/review", "GET", "handler", "assurance_twin.review_detail"),
    OperationRoute("/code-security/reviews", "GET", "handler", "code_security.reviews"),
    OperationRoute("/code-security/packs", "GET", "handler", "code_security.packs"),
    OperationRoute("/code-security/repositories", "GET", "handler", "code_security.repositories"),
    OperationRoute("/knowledge/github/sources", "GET", "handler", "knowledge.github.sources"),
    OperationRoute(
        "/knowledge/github/sources",
        "POST",
        "handler",
        "code_security.repository_change",
        "proposal",
        OWNER_ROLES,
    ),
    OperationRoute("/code-security/scan-requests", "GET", "handler", "code_security.scan_requests"),
    OperationRoute("/code-security/worker-status", "GET", "handler", "code_security.worker_status"),
    OperationRoute("/code-security/issues", "GET", "handler", "code_security.issues"),
    # A registration change only queues intent for the Core worker, which applies it with
    # compare-and-set and a Heimdall-attributed audit entry.
    OperationRoute(
        "/code-security/repositories",
        "POST",
        "handler",
        "code_security.repository_change",
        "proposal",
        OWNER_ROLES,
    ),
    # A scan request only queues intent for the Heimdall-attributed scan worker; it never scans,
    # writes to a repository, or grants approval or execution authority.
    OperationRoute(
        "/code-security/scan-requests",
        "POST",
        "handler",
        "code_security.scan_request",
        "proposal",
        CONTRIBUTOR_ROLES,
    ),
    OperationRoute("/reports", "GET", "list_reports", "report.list"),
    OperationRoute("/reports/registry", "GET", "get_registry", "report.registry"),
    OperationRoute("/reports/formats", "GET", "list_formats", "report.formats"),
    OperationRoute("/reports/widget-types", "GET", "list_widget_types", "report.widget_types"),
    OperationRoute("/reports/datasources", "GET", "list_datasource_names", "report.datasources"),
    OperationRoute("/reports/health", "GET", "get_health", "report.health"),
    OperationRoute("/reports/{report_id:str}", "GET", "get_report", "report.detail"),
    OperationRoute("/reports/{report_id:str}/render", "GET", "render_report", "report.render"),
    OperationRoute(
        "/read-investigations",
        "POST",
        "start",
        "read_investigation.start",
        "proposal",
        CONTRIBUTOR_ROLES,
    ),
    OperationRoute("/simulate/blast-radius", "GET", "handler", "blast_radius.simulate"),
    OperationRoute("/audit/{correlation_id}/bitemporal", "GET", "handler", "audit.bitemporal"),
    OperationRoute("/webhook", "POST", "handler", "webhook.generic", "webhook"),
    OperationRoute("/webhook/azure-monitor", "POST", "handler", "webhook.azure_monitor", "webhook"),
    OperationRoute("/provision/stream", "GET", "handler", "provision", "stream"),
)


__all__ = [
    "APPROVER_ROLES",
    "CONTRIBUTOR_ROLES",
    "OPERATIONS_ROUTE_MANIFEST",
    "READ_ROLES",
    "OperationRoute",
    "RouteKind",
]
