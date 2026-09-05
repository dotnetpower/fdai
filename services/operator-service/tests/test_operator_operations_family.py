"""Focused parity and authority tests for the Operator operations family."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import fdai_operator_service.families.operations.factory as operations_factory
import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations import (
    OPERATIONS_ROUTE_MANIFEST,
    EventProposal,
    PanelRoute,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
    ProposalConflictError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
    ReportPdfEncodingError,
    build_operations_routes,
)
from fdai_operator_service.families.operations.instance_states import (
    InventoryGenerationChangedError,
    OntologyGenerationChangedError,
)
from fdai_operator_service.families.operations.manifest import READ_ROLES
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.read_investigation import read_investigation_task_id
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

# Sentinel placed in RecordingDependencies.replay_batches to end a persistent
# stream test deterministically by simulating the durable reader becoming
# unavailable, since the inventory invalidation stream never has a terminal
# event of its own.
_REPLAY_UNAVAILABLE = object()

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_ROOT = REPO_ROOT / "services/operator-service/src/fdai_operator_service/families/operations"
HEADERS = {"Authorization": "Bearer reader"}
LEGACY_ROUTE_SNAPSHOT = {
    (("GET", "HEAD"), "/inventory/graph", "handler"),
    (("GET", "HEAD"), "/ontology/graph", "handler"),
    (("GET", "HEAD"), "/ontology/instances", "ontology_instances"),
    (("GET", "HEAD"), "/ontology/instances/states", "ontology_instance_states"),
    (("GET", "HEAD"), "/ontology/instances/explore", "ontology_instance_explore"),
    (("GET", "HEAD"), "/ontology/instances/stream", "ontology_instances_stream"),
    (
        ("GET", "HEAD"),
        "/ontology/declarations/{kind:str}/{name:str}",
        "ontology_declaration_detail",
    ),
    (
        ("GET", "HEAD"),
        "/ontology/declarations/{kind:str}/{name:str}/dependents",
        "ontology_declaration_dependents",
    ),
    (
        ("GET", "HEAD"),
        "/ontology/releases/{candidate_digest:str}/diff",
        "ontology_release_diff",
    ),
    (
        ("GET", "HEAD"),
        "/ontology/object-types/{name:str}/evidence-health",
        "ontology_object_type_evidence_health",
    ),
    (("GET", "HEAD"), "/pantheon/graph", "handler"),
    (("GET", "HEAD"), "/pantheon/workflows", "handler"),
    (("GET", "HEAD"), "/views/workflow-apps", "list_workflow_apps"),
    (("GET", "HEAD"), "/views/process", "list_processes"),
    (("GET", "HEAD"), "/views/process/{process_id:str}", "render_process"),
    (("GET", "HEAD"), "/views/process/{process_id:str}/events", "process_events"),
    (("GET", "HEAD"), "/detection-readiness", "handler"),
    (("GET", "HEAD"), "/automation-blueprints", "handler"),
    (("POST",), "/automation-blueprints/accept", "handler"),
    (("POST",), "/automation-blueprints/reject", "handler"),
    (("POST",), "/automation-blueprints/materialize", "handler"),
    (("GET", "HEAD"), "/audit/{correlation_id}/what-if", "handler"),
    (("GET", "HEAD"), "/scope", "handler"),
    (("GET", "HEAD"), "/stewardship", "handler"),
    (("GET", "HEAD"), "/reports", "list_reports"),
    (("GET", "HEAD"), "/reports/registry", "get_registry"),
    (("GET", "HEAD"), "/reports/formats", "list_formats"),
    (("GET", "HEAD"), "/reports/widget-types", "list_widget_types"),
    (("GET", "HEAD"), "/reports/datasources", "list_datasource_names"),
    (("GET", "HEAD"), "/reports/health", "get_health"),
    (("GET", "HEAD"), "/reports/{report_id:str}", "get_report"),
    (("GET", "HEAD"), "/reports/{report_id:str}/render", "render_report"),
    (("POST",), "/read-investigations", "start"),
    (("GET", "HEAD"), "/simulate/blast-radius", "handler"),
    (("GET", "HEAD"), "/audit/{correlation_id}/bitemporal", "handler"),
    (("POST",), "/webhook", "handler"),
    (("POST",), "/webhook/azure-monitor", "handler"),
    (("GET", "HEAD"), "/provision/stream", "handler"),
}


class RecordingDependencies:
    """Record injected calls without manufacturing authoritative projections."""

    def __init__(self) -> None:
        self.queries: list[ProjectionQuery] = []
        self.proposals: list[EventProposal] = []
        self.replays: list[ReplayQuery] = []
        self.unavailable = False
        self.conflict = False
        self.not_found_operations: set[str] = set()
        self.projections: dict[str, Mapping[str, object]] = {}
        self.replay_events = (
            ReplayEvent(8, "message", {"type": "provision.progress", "secret": "x"}),
        )
        self.replay_batches: list[ReplayBatch | object] = []

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        self.queries.append(query)
        if self.unavailable:
            raise ProjectionUnavailableError
        if query.operation in self.not_found_operations:
            raise ProjectionNotFoundError
        return self.projections.get(
            query.operation,
            {"operation": query.operation, "token": "hidden", "items": []},
        )

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        self.proposals.append(proposal)
        if self.conflict:
            raise ProposalConflictError
        return ProposalReceipt(
            request_id="request-1",
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at="2026-08-08T00:00:00Z",
        )

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        self.replays.append(query)
        if self.replay_batches:
            next_batch = self.replay_batches.pop(0)
            if next_batch is _REPLAY_UNAVAILABLE:
                raise ProjectionUnavailableError
            assert isinstance(next_batch, ReplayBatch)
            return next_batch
        return ReplayBatch(
            events=self.replay_events,
            watermark=8,
        )

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        del operation, body
        return headers.get("x-webhook-signature") == "valid"


def _verify(token: str) -> Mapping[str, object]:
    role = {
        "contributor": OperatorRole.CONTRIBUTOR,
        "approver": OperatorRole.APPROVER,
    }.get(token, OperatorRole.READER)
    return {"oid": f"{token}-oid", "roles": [role.value]}


class RecordingPdfEncoder:
    """Record the already-redacted report envelope passed to PDF delivery."""

    name = "pdf"
    content_type = "application/pdf"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.reports: list[Mapping[str, object]] = []

    def encode(self, report: Mapping[str, object]) -> bytes:
        self.reports.append(report)
        if self.fail:
            raise ReportPdfEncodingError("private renderer detail")
        return b"%PDF-1.7\n%%EOF\n"


def _client(
    dependencies: RecordingDependencies,
    *,
    pdf_encoder: RecordingPdfEncoder | None = None,
) -> TestClient:
    routes = build_operations_routes(
        authenticator=OperatorAuthenticator(verifier=_verify, group_ids={}),
        projection_reader=dependencies,
        proposal_writer=dependencies,
        replay_reader=dependencies,
        webhook_verifier=dependencies,
        report_pdf_encoder=pdf_encoder,
        panels=(PanelRoute("/capabilities", "capabilities", "panel.capabilities"),),
    )
    return TestClient(Starlette(routes=list(routes)))


def test_manifest_preserves_exact_legacy_paths_methods_and_names() -> None:
    dependencies = RecordingDependencies()
    app = cast(Starlette, _client(dependencies).app)
    actual = {
        (tuple(sorted(route.methods or ())), route.path, route.name)
        for route in app.router.routes
        if isinstance(route, Route)
    }
    expected = set(LEGACY_ROUTE_SNAPSHOT)
    expected.add((("GET", "HEAD"), "/capabilities", "panel:capabilities"))
    assert actual == expected
    assert {
        (
            ("GET", "HEAD") if entry.method == "GET" else ("POST",),
            entry.path,
            entry.name,
        )
        for entry in OPERATIONS_ROUTE_MANIFEST
    } == LEGACY_ROUTE_SNAPSHOT
    assert len(OPERATIONS_ROUTE_MANIFEST) == 38


def test_recorded_state_route_is_authenticated_and_preserves_bounded_query_context() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)
    assert client.get("/ontology/instances/states").status_code == 401
    response = client.get(
        "/ontology/instances/states?limit=500&search=example&cursor=page-selector",
        headers=HEADERS,
    )
    assert response.status_code == 200
    query = dependencies.queries[-1]
    assert query.operation == "ontology.instance.states"
    assert query.principal_id == "reader-oid"
    assert query.roles == frozenset({OperatorRole.READER})
    assert query.purpose == "operations-review"
    assert query.limit == 500
    assert query.cursor == "page-selector"
    assert query.params["search"] == ("example",)
    assert client.get("/ontology/instances/states?limit=501", headers=HEADERS).status_code == 400
    assert not dependencies.proposals


def test_recorded_state_route_reports_generation_change_explicitly() -> None:
    class ChangedDependencies(RecordingDependencies):
        async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
            del query
            raise InventoryGenerationChangedError

    response = _client(ChangedDependencies()).get("/ontology/instances/states", headers=HEADERS)
    assert response.status_code == 409
    assert response.json() == {"error": {"status": 409, "message": "inventory_generation_changed"}}


def test_recorded_state_route_reports_ontology_generation_change_explicitly() -> None:
    class ChangedDependencies(RecordingDependencies):
        async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
            del query
            raise OntologyGenerationChangedError

    response = _client(ChangedDependencies()).get("/ontology/instances/states", headers=HEADERS)
    assert response.status_code == 409
    assert response.json() == {"error": {"status": 409, "message": "ontology_generation_changed"}}


def test_automation_blueprints_projection_is_reader_gated_and_read_only() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["automation_blueprint.list"] = {
        "candidates": [{"id": "cand-1", "state": "proposed", "token": "hidden"}],
        "metrics": {"proposed": 1},
    }
    client = _client(dependencies)

    assert client.get("/automation-blueprints").status_code == 401
    response = client.get("/automation-blueprints?limit=10", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [{"id": "cand-1", "state": "proposed", "token": "[REDACTED]"}],
        "metrics": {"proposed": 1},
    }
    assert dependencies.queries[-1].operation == "automation_blueprint.list"
    assert dependencies.queries[-1].principal_id == "reader-oid"
    # Reader is the floor, not the ceiling: every ladder role keeps read access.
    entry = next(
        item for item in OPERATIONS_ROUTE_MANIFEST if item.path == "/automation-blueprints"
    )
    assert entry.kind == "projection"
    assert entry.roles == frozenset(
        {
            OperatorRole.READER,
            OperatorRole.CONTRIBUTOR,
            OperatorRole.APPROVER,
            OperatorRole.OWNER,
        }
    )
    # The candidate surface is inert: no write method is registered for it.
    app = cast(Starlette, client.app)
    blueprint_methods = {
        method
        for route in app.router.routes
        if isinstance(route, Route) and route.path == "/automation-blueprints"
        for method in route.methods or ()
    }
    assert blueprint_methods == {"GET", "HEAD"}


def test_automation_blueprints_projection_fails_closed_when_unavailable() -> None:
    dependencies = RecordingDependencies()
    dependencies.unavailable = True

    response = _client(dependencies).get("/automation-blueprints", headers=HEADERS)

    assert response.status_code == 503
    assert "candidates" not in response.text


@pytest.mark.parametrize(
    ("path", "operation"),
    [
        ("/automation-blueprints/accept", "automation_blueprint.accept"),
        ("/automation-blueprints/reject", "automation_blueprint.reject"),
        ("/automation-blueprints/materialize", "automation_blueprint.materialize"),
    ],
)
def test_blueprint_review_routes_are_separately_authorized_proposals(
    path: str, operation: str
) -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)

    unauthenticated = client.post(path, json={"candidate_id": "cand-1"})
    # The reader who may read the candidate list may not act on it.
    reader = client.post(
        path, headers={**HEADERS, "Idempotency-Key": "idem-1"}, json={"candidate_id": "cand-1"}
    )
    # A review decision carries human approval, so proposing is not enough:
    # the contributor who can propose a blueprint cannot review one.
    contributor = client.post(
        path,
        headers={"Authorization": "Bearer contributor", "Idempotency-Key": "idem-1"},
        json={"candidate_id": "cand-1"},
    )
    without_key = client.post(
        path,
        headers={"Authorization": "Bearer approver"},
        json={"candidate_id": "cand-1"},
    )
    accepted = client.post(
        path,
        headers={
            "Authorization": "Bearer approver",
            "Idempotency-Key": "idem-1",
            "X-Correlation-ID": "corr-1",
        },
        json={"candidate_id": "cand-1", "reason": "recurring and bounded"},
    )

    assert unauthenticated.status_code == 401
    assert reader.status_code == 403
    assert contributor.status_code == 403
    assert without_key.status_code == 400
    assert accepted.status_code == 202
    assert accepted.json()["durably_queued"] is True
    # The route only queues intent; it never reviews or materializes itself.
    assert dependencies.proposals == [
        EventProposal(
            operation=operation,
            principal_id="approver-oid",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            payload={"candidate_id": "cand-1", "reason": "recurring and bounded"},
        )
    ]
    assert dependencies.queries == []


def test_no_proposal_route_is_reachable_at_the_read_floor() -> None:
    # A proposal writes intent on the caller's behalf, so a manifest entry that
    # forgot to narrow its roles must fail construction, not ship silently.
    for entry in OPERATIONS_ROUTE_MANIFEST:
        if entry.kind == "proposal":
            assert OperatorRole.READER not in entry.roles, entry.path


def test_blueprint_review_routes_reject_a_conflicting_idempotency_key() -> None:
    dependencies = RecordingDependencies()
    dependencies.conflict = True

    response = _client(dependencies).post(
        "/automation-blueprints/accept",
        headers={"Authorization": "Bearer approver", "Idempotency-Key": "idem-1"},
        json={"candidate_id": "cand-1"},
    )

    assert response.status_code == 409


def test_projection_requires_reader_bounds_pagination_and_redacts() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)

    assert client.get("/inventory/graph").status_code == 401
    oversized = client.get("/inventory/graph?limit=501", headers=HEADERS)
    response = client.get(
        "/inventory/graph?limit=25&cursor=next&link=contains&link=depends_on",
        headers=HEADERS,
    )

    assert oversized.status_code == 400
    assert (response.status_code, response.json()) == (
        200,
        {"operation": "inventory.graph", "token": "[REDACTED]", "items": []},
    )
    assert dependencies.queries[-1] == ProjectionQuery(
        operation="inventory.graph",
        principal_id="reader-oid",
        path={},
        params={"limit": ("25",), "cursor": ("next",), "link": ("contains", "depends_on")},
        limit=25,
        cursor="next",
        roles=frozenset({OperatorRole.READER}),
        purpose="operations-review",
    )


def test_detection_lifecycle_projection_requires_an_authenticated_reader() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["detection.readiness"] = {
        "source": "postgresql:state_kv:detection-readiness",
        "targets": [],
        "lifecycle": {
            "source": "postgresql:state_kv:analyzer-finding-receipt",
            "targets": [],
        },
    }
    client = _client(dependencies)

    assert client.get("/detection-readiness").status_code == 401
    response = client.get("/detection-readiness", headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["lifecycle"]["targets"] == []
    assert dependencies.queries[-1].operation == "detection.readiness"
    assert dependencies.queries[-1].roles == frozenset({OperatorRole.READER})


def test_instance_explorer_forwards_bounded_root_and_activity_query() -> None:
    dependencies = RecordingDependencies()
    response = _client(dependencies).get(
        "/ontology/instances/explore?root=resource-one&activity_limit=20&limit=50",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert dependencies.queries[-1] == ProjectionQuery(
        operation="ontology.instance.explore",
        principal_id="reader-oid",
        path={},
        params={
            "root": ("resource-one",),
            "activity_limit": ("20",),
            "limit": ("50",),
        },
        limit=50,
        cursor=None,
        roles=frozenset({OperatorRole.READER}),
        purpose="operations-review",
    )


def test_instance_directory_forwards_bounded_search() -> None:
    dependencies = RecordingDependencies()
    response = _client(dependencies).get(
        "/ontology/instances?search=container-app&limit=25",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert dependencies.queries[-1] == ProjectionQuery(
        operation="ontology.instance.list",
        principal_id="reader-oid",
        path={},
        params={"search": ("container-app",), "limit": ("25",)},
        limit=25,
        cursor=None,
        roles=frozenset({OperatorRole.READER}),
        purpose="operations-review",
    )


def test_declaration_detail_route_binds_exact_path_role_and_purpose() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["ontology.declaration.detail"] = {
        "schema_version": "1.0.0",
        "declaration_name": "Decision",
        "mutation_authority": False,
    }

    response = _client(dependencies).get(
        "/ontology/declarations/object-types/Decision",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["declaration_name"] == "Decision"
    assert dependencies.queries[-1] == ProjectionQuery(
        operation="ontology.declaration.detail",
        principal_id="reader-oid",
        path={"kind": "object-types", "name": "Decision"},
        params={},
        limit=100,
        cursor=None,
        roles=frozenset({OperatorRole.READER}),
        purpose="operations-review",
    )


def test_declaration_dependents_route_keeps_the_same_read_boundary() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["ontology.declaration.dependents"] = {
        "schema_version": "1.0.0",
        "declaration_name": "Decision",
        "mutation_authority": False,
        "dependents": [],
    }

    response = _client(dependencies).get(
        "/ontology/declarations/object-types/Decision/dependents",
        headers=HEADERS,
    )

    assert response.status_code == 200
    query = dependencies.queries[-1]
    assert query.operation == "ontology.declaration.dependents"
    assert query.path == {"kind": "object-types", "name": "Decision"}
    assert query.roles == frozenset({OperatorRole.READER})
    assert query.purpose == "operations-review"


def test_release_diff_route_binds_candidate_and_base_without_mutation() -> None:
    dependencies = RecordingDependencies()
    candidate = f"sha256:{'a' * 64}"
    base = f"sha256:{'b' * 64}"
    dependencies.projections["ontology.release.diff"] = {
        "schema_version": "1.0.0",
        "candidate_release_digest": candidate,
        "base_release_digest": base,
        "mutation_authority": False,
    }

    response = _client(dependencies).get(
        f"/ontology/releases/{candidate}/diff?base={base}",
        headers=HEADERS,
    )

    assert response.status_code == 200
    query = dependencies.queries[-1]
    assert query.operation == "ontology.release.diff"
    assert query.path == {"candidate_digest": candidate}
    assert query.params == {"base": (base,)}


def test_evidence_health_route_binds_the_exact_object_type() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["ontology.evidence.health"] = {
        "schema_version": "1.0.0",
        "object_type": "Decision",
        "availability": "unavailable",
        "mutation_authority": False,
    }

    response = _client(dependencies).get(
        "/ontology/object-types/Decision/evidence-health",
        headers=HEADERS,
    )

    assert response.status_code == 200
    query = dependencies.queries[-1]
    assert query.operation == "ontology.evidence.health"
    assert query.path == {"name": "Decision"}
    assert query.roles == frozenset({OperatorRole.READER})


def test_unavailable_projection_is_explicit_not_fake_empty_state() -> None:
    dependencies = RecordingDependencies()
    dependencies.unavailable = True

    response = _client(dependencies).get("/scope", headers=HEADERS)

    assert (response.status_code, response.json()) == (
        503,
        {"error": {"status": 503, "message": "authoritative projection is unavailable"}},
    )


def test_not_found_projection_uses_operation_specific_public_message() -> None:
    dependencies = RecordingDependencies()
    dependencies.not_found_operations.update(
        {"blast_radius.simulate", "ontology.declaration.detail"}
    )
    client = _client(dependencies)

    impact = client.get(
        "/simulate/blast-radius?target=missing&depth=1&link=contains",
        headers=HEADERS,
    )
    declaration = client.get(
        "/ontology/declarations/object-types/Missing",
        headers=HEADERS,
    )

    assert (impact.status_code, impact.json()) == (
        404,
        {
            "error": {
                "status": 404,
                "message": "target resource is not available in the active inventory",
            }
        },
    )
    assert (declaration.status_code, declaration.json()) == (
        404,
        {"error": {"status": 404, "message": "ontology declaration is not available"}},
    )


def test_pdf_format_is_absent_and_blocked_before_projection_without_extra() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["report.list"] = {"items": [], "formats": ["json", "pdf"]}
    client = _client(dependencies)

    catalog = client.get("/reports", headers=HEADERS)
    before = len(dependencies.queries)
    download = client.get(
        "/reports/incident-rca-dossier/render?format=pdf",
        headers=HEADERS,
    )

    assert catalog.json()["formats"] == ["json"]
    assert (download.status_code, download.json()) == (
        400,
        {"error": {"status": 400, "message": "unknown format 'pdf'"}},
    )
    assert len(dependencies.queries) == before


def test_registered_pdf_is_advertised_and_encodes_redacted_projection() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections.update(
        {
            "report.list": {"items": [], "formats": ["json"]},
            "report.registry": {"datasources": [], "widgets": [], "formats": ["json"]},
            "report.formats": {"items": [{"name": "json", "content_type": "application/json"}]},
            "report.render": {
                "id": "incident-rca-dossier",
                "version": "1.0.0",
                "name": "Incident RCA Dossier",
                "generated_at": "2026-08-14T00:00:00Z",
                "widgets": [],
                "secret": "must-not-leak",
            },
        }
    )
    encoder = RecordingPdfEncoder()
    client = _client(dependencies, pdf_encoder=encoder)

    catalog = client.get("/reports", headers=HEADERS).json()
    registry = client.get("/reports/registry", headers=HEADERS).json()
    formats = client.get("/reports/formats", headers=HEADERS).json()
    response = client.get(
        "/reports/incident-rca-dossier/render?format=pdf&correlation_id=corr-1",
        headers=HEADERS,
    )

    assert catalog["formats"] == ["json", "pdf"]
    assert registry["formats"] == ["json", "pdf"]
    assert formats["items"][-1] == {"name": "pdf", "content_type": "application/pdf"}
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        'attachment; filename="incident-rca-dossier.pdf"'
    )
    assert response.content.startswith(b"%PDF-")
    assert encoder.reports == [
        {
            "id": "incident-rca-dossier",
            "version": "1.0.0",
            "name": "Incident RCA Dossier",
            "generated_at": "2026-08-14T00:00:00Z",
            "widgets": [],
            "secret": "[REDACTED]",
        }
    ]


def test_pdf_encoding_failure_is_sanitized_and_fail_closed() -> None:
    dependencies = RecordingDependencies()
    dependencies.projections["report.render"] = {"id": "incident-rca-dossier"}

    response = _client(
        dependencies,
        pdf_encoder=RecordingPdfEncoder(fail=True),
    ).get("/reports/incident-rca-dossier/render?format=pdf", headers=HEADERS)

    assert (response.status_code, response.json()) == (
        503,
        {"error": {"status": 503, "message": "report PDF encoding is unavailable"}},
    )


def test_read_investigation_only_writes_durable_event_proposal() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)
    reader = client.post(
        "/read-investigations",
        headers={**HEADERS, "Idempotency-Key": "idem-1"},
        json={
            "prompt": "inspect",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    )
    accepted = client.post(
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-1",
            "X-Correlation-ID": "corr-1",
        },
        json={
            "prompt": "inspect",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    )

    assert reader.status_code == 403
    assert accepted.status_code == 202
    assert accepted.json()["durably_queued"] is True
    assert dependencies.proposals == [
        EventProposal(
            operation="read_investigation.start",
            principal_id="contributor-oid",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            payload={
                "prompt": "inspect",
                "intent": "resource_state",
                "resource_name": "service-one",
                "explicit_deep": False,
            },
        )
    ]


def test_read_investigation_rejects_untyped_body_before_durable_acceptance() -> None:
    dependencies = RecordingDependencies()

    response = _client(dependencies).post(
        "/read-investigations",
        headers={"Authorization": "Bearer contributor", "Idempotency-Key": "idem-1"},
        json={"prompt": "inspect"},
    )

    assert response.status_code == 400
    assert dependencies.proposals == []


def _azure_monitor_alert() -> dict[str, object]:
    return {
        "schemaId": "azureMonitorCommonAlertSchema",
        "data": {
            "essentials": {
                "alertId": "alert-instance-1",
                "alertRule": "example-cpu-alert",
                "severity": "Sev2",
                "signalType": "Metric",
                "monitorCondition": "Fired",
                "monitoringService": "Platform",
                "alertTargetIDs": [
                    "/subscriptions/00000000-0000-0000-0000-000000000001/"
                    "resourceGroups/rg-example/providers/Example/widgets/a"
                ],
                "firedDateTime": "2020-01-01T00:00:00+00:00",
            }
        },
    }


def test_webhook_verifies_before_proposing_and_never_mutates_provider() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)
    denied = client.post(
        "/webhook/azure-monitor",
        headers={"Idempotency-Key": "alert-1"},
        json=_azure_monitor_alert(),
    )
    accepted = client.post(
        "/webhook/azure-monitor",
        headers={"Idempotency-Key": "alert-1", "X-Webhook-Signature": "valid"},
        json=_azure_monitor_alert(),
    )

    assert denied.status_code == 401
    assert accepted.status_code == 202
    assert len(dependencies.proposals) == 1
    assert dependencies.proposals[0].operation == "webhook.azure_monitor"
    assert dependencies.proposals[0].correlation_id is not None
    events = dependencies.proposals[0].payload["events"]
    assert isinstance(events, list)
    assert events[0]["event_type"] == "metric_alert_fired"
    assert "alertTargetIDs" not in str(dependencies.proposals[0].payload)


def test_azure_monitor_webhook_rejects_authenticated_malformed_body() -> None:
    dependencies = RecordingDependencies()

    response = _client(dependencies).post(
        "/webhook/azure-monitor",
        headers={"Idempotency-Key": "alert-1", "X-Webhook-Signature": "valid"},
        json={"data": "signal"},
    )

    assert response.status_code == 400
    assert dependencies.proposals == []


def test_provision_stream_replays_from_durable_last_event_id_and_redacts() -> None:
    dependencies = RecordingDependencies()

    with _client(dependencies).stream(
        "GET",
        "/provision/stream",
        headers={**HEADERS, "Last-Event-ID": "7"},
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert dependencies.replays == [
        ReplayQuery(
            stream="provision",
            principal_id="reader-oid",
            after_sequence=7,
            limit=500,
        )
    ]
    assert "id: 8\nevent: message" in body
    assert '"secret":"[REDACTED]"' in body
    assert 'event: watermark\ndata: {"sequence": 8}' in body


def test_read_investigation_sse_replays_only_after_durable_proposal() -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_events = (
        ReplayEvent(1008, "investigation.completed", {"status": "succeeded"}),
    )

    with _client(dependencies).stream(
        "POST",
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-stream",
            "Last-Event-ID": "7",
            "Accept": "text/event-stream",
        },
        json={
            "prompt": "inspect",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert len(dependencies.proposals) == 1
    assert dependencies.replays == [
        ReplayQuery(
            stream="read-investigation:request-1",
            principal_id="contributor-oid",
            after_sequence=7,
            limit=500,
        )
    ]
    assert "id: 1008\nevent: investigation.completed" in body


def test_read_investigation_acceptance_returns_canonical_task_id() -> None:
    dependencies = RecordingDependencies()

    response = _client(dependencies).post(
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-cancel-address",
        },
        json={
            "prompt": "inspect",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    )

    assert response.status_code == 202
    assert response.json()["task_id"] == read_investigation_task_id(
        "contributor-oid",
        "idem-cancel-address",
    )


def test_read_investigation_sse_polls_progress_to_terminal_with_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_batches = [
        ReplayBatch(
            events=(ReplayEvent(8, "resource.resolved", {"kind": "resource.resolved"}),),
            watermark=8,
        ),
        ReplayBatch(
            events=(ReplayEvent(1008, "investigation.completed", {"status": "succeeded"}),),
            watermark=1008,
        ),
    ]
    monkeypatch.setattr(operations_factory, "READ_INVESTIGATION_POLL_SECONDS", 0.0)
    monkeypatch.setattr(operations_factory, "READ_INVESTIGATION_HEARTBEAT_SECONDS", 0.0)

    with _client(dependencies).stream(
        "POST",
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-live-stream",
            "Last-Event-ID": "7",
            "Accept": "text/event-stream",
        },
        json={
            "prompt": "inspect",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "id: 8\nevent: resource.resolved" in body
    assert ": heartbeat\n\n" in body
    assert "id: 1008\nevent: investigation.completed" in body
    assert dependencies.replays == [
        ReplayQuery(
            stream="read-investigation:request-1",
            principal_id="contributor-oid",
            after_sequence=7,
            limit=500,
        ),
        ReplayQuery(
            stream="read-investigation:request-1",
            principal_id="contributor-oid",
            after_sequence=8,
            limit=500,
        ),
    ]


def test_operations_sse_rejects_multiline_event_names() -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_events = (ReplayEvent(8, "message\ndata: forged", {"ok": True}),)

    with _client(dependencies).stream("GET", "/provision/stream", headers=HEADERS) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert "forged" not in body
    assert "event: invalid" in body


def test_operations_sse_caps_serialized_frames_at_256_kib() -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_events = (ReplayEvent(8, "message", {"value": "x" * (256 * 1024)}),)

    with _client(dependencies).stream("GET", "/provision/stream", headers=HEADERS) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    frames = [frame for frame in body.split(b"\n\n") if frame]
    assert all(len(frame) + 2 <= 256 * 1024 for frame in frames)
    assert b'"error":"frame_too_large"' in body


def test_operations_sse_redaction_bounds_recursive_containers() -> None:
    dependencies = RecordingDependencies()
    nested: object = "leaf"
    for _ in range(20):
        nested = {"child": nested}
    dependencies.replay_events = (ReplayEvent(8, "message", {"root": nested}),)

    with _client(dependencies).stream("GET", "/provision/stream", headers=HEADERS) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert '"[REDACTED]"' in body
    assert "leaf" not in body


def test_operations_sse_redaction_bounds_mapping_and_sequence_width() -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_events = (
        ReplayEvent(
            8,
            "message",
            {
                "mapping": {f"key-{index}": index for index in range(600)},
                "sequence": list(range(600)),
            },
        ),
    )

    with _client(dependencies).stream("GET", "/provision/stream", headers=HEADERS) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert '"key-499":499' in body
    assert '"key-500":500' not in body
    assert '"sequence":[0,1,2' in body
    assert ",499]" in body
    assert ",500]" not in body


def test_family_has_no_fdai_implementation_imports() -> None:
    for path in FAMILY_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name == "fdai" or name.startswith("fdai.") for name in imports)


def test_inventory_invalidation_manifest_route_is_reader_gated_with_no_mutation_authority() -> None:
    entry = next(
        item for item in OPERATIONS_ROUTE_MANIFEST if item.path == "/ontology/instances/stream"
    )
    assert entry.method == "GET"
    assert entry.name == "ontology_instances_stream"
    assert entry.operation == "ontology.inventory.invalidations"
    assert entry.kind == "stream"
    # Reader is the floor: no separate contributor/approver ladder guards this
    # read-only invalidation signal, and it carries no mutation authority.
    assert entry.roles == READ_ROLES
    assert OperatorRole.READER in entry.roles


def test_inventory_invalidation_stream_rejects_unauthenticated_requests() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)

    response = client.get("/ontology/instances/stream")

    assert response.status_code == 401
    assert dependencies.replays == []


def test_inventory_invalidation_stream_establishes_watermark_without_a_replay_storm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_POLL_SECONDS", 0.0)
    dependencies.replay_batches = [
        ReplayBatch(
            events=(
                ReplayEvent(
                    42,
                    "inventory.invalidated",
                    {
                        "schema_version": "1.0.0",
                        "watermark": 42,
                        "observation_count": 3,
                        "observed_at": "2026-09-06T01:00:00+00:00",
                        "recorded_at": "2026-09-06T01:00:05+00:00",
                        "complete": False,
                        "execution_authority": False,
                        "mutation_authority": False,
                    },
                ),
            ),
            watermark=42,
        ),
        _REPLAY_UNAVAILABLE,
    ]

    with _client(dependencies).stream(
        "GET",
        "/ontology/instances/stream",
        headers=HEADERS,
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    # No Last-Event-ID means the very first replay call establishes the
    # current watermark; it must not request an unbounded history replay.
    assert dependencies.replays[0] == ReplayQuery(
        stream="ontology.inventory.invalidations",
        principal_id="reader-oid",
        after_sequence=None,
        limit=500,
    )
    # SSE id equals the coalesced event's watermark.
    assert "id: 42\nevent: inventory.invalidated" in body
    assert '"watermark":42' in body
    assert '"observation_count":3' in body


def test_inventory_invalidation_stream_honors_last_event_id_on_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_POLL_SECONDS", 0.0)
    dependencies.replay_batches = [
        ReplayBatch(events=(), watermark=99),
        _REPLAY_UNAVAILABLE,
    ]

    with _client(dependencies).stream(
        "GET",
        "/ontology/instances/stream",
        headers={**HEADERS, "Last-Event-ID": "99"},
    ) as response:
        b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert dependencies.replays[0] == ReplayQuery(
        stream="ontology.inventory.invalidations",
        principal_id="reader-oid",
        after_sequence=99,
        limit=500,
    )


def test_inventory_invalidation_stream_coalesces_page_and_exposes_no_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_POLL_SECONDS", 0.0)
    dependencies.replay_batches = [
        ReplayBatch(
            events=(
                ReplayEvent(
                    50,
                    "inventory.invalidated",
                    {
                        "schema_version": "1.0.0",
                        "watermark": 50,
                        "observation_count": 5,
                        "observed_at": "2026-09-06T01:00:00+00:00",
                        "recorded_at": "2026-09-06T01:00:05+00:00",
                        "complete": False,
                        "execution_authority": False,
                        "mutation_authority": False,
                    },
                ),
            ),
            watermark=50,
        ),
        _REPLAY_UNAVAILABLE,
    ]

    with _client(dependencies).stream(
        "GET",
        "/ontology/instances/stream",
        headers=HEADERS,
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert body.count("event: inventory.invalidated") == 1
    for forbidden in (
        "resource",
        "provider_ref",
        "subject_ref",
        "principal",
        "tenant",
        "properties",
        "oid",
    ):
        assert forbidden not in body


def test_inventory_invalidation_stream_polls_persistently_and_emits_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_batches = [
        ReplayBatch(events=(), watermark=0),
        ReplayBatch(
            events=(ReplayEvent(51, "inventory.invalidated", {"watermark": 51}),),
            watermark=51,
        ),
        _REPLAY_UNAVAILABLE,
    ]
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_POLL_SECONDS", 0.0)
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_HEARTBEAT_SECONDS", 0.0)

    with _client(dependencies).stream(
        "GET",
        "/ontology/instances/stream",
        headers=HEADERS,
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert response.status_code == 200
    assert ": heartbeat\n\n" in body
    assert "id: 51\nevent: inventory.invalidated" in body
    # Every poll durably re-requests the stream past the last seen watermark.
    assert all(query.stream == "ontology.inventory.invalidations" for query in dependencies.replays)
    assert len(dependencies.replays) >= 3


def test_inventory_invalidation_stream_terminates_when_the_reader_becomes_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_batches = [
        ReplayBatch(events=(), watermark=0),
        _REPLAY_UNAVAILABLE,
    ]
    monkeypatch.setattr(operations_factory, "INVENTORY_INVALIDATION_POLL_SECONDS", 0.0)

    with _client(dependencies).stream(
        "GET",
        "/ontology/instances/stream",
        headers=HEADERS,
    ) as response:
        body = b"".join(response.iter_bytes())

    # The generator returns (ending the SSE body) instead of raising once the
    # durable reader reports it is unavailable mid-poll.
    assert response.status_code == 200
    assert body == b""
    assert len(dependencies.replays) == 2


def test_inventory_invalidation_stream_fails_closed_when_unavailable_on_initial_connect() -> None:
    dependencies = RecordingDependencies()
    dependencies.replay_batches = [_REPLAY_UNAVAILABLE]

    response = _client(dependencies).get(
        "/ontology/instances/stream",
        headers=HEADERS,
    )

    # The very first (pre-stream) replay call happens synchronously in the
    # route handler, so an unavailable reader fails the request closed with
    # 503 instead of opening an empty SSE body.
    assert response.status_code == 503
    assert len(dependencies.replays) == 1
