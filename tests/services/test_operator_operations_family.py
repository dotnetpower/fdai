"""Focused parity and authority tests for the Operator operations family."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations import (
    OPERATIONS_ROUTE_MANIFEST,
    EventProposal,
    PanelRoute,
    ProjectionQuery,
    ProjectionUnavailableError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
    build_operations_routes,
)
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILY_ROOT = REPO_ROOT / "services/operator-service/src/fdai_operator_service/families/operations"
HEADERS = {"Authorization": "Bearer reader"}
LEGACY_ROUTE_SNAPSHOT = {
    (("GET", "HEAD"), "/inventory/graph", "handler"),
    (("GET", "HEAD"), "/ontology/graph", "handler"),
    (("GET", "HEAD"), "/pantheon/graph", "handler"),
    (("GET", "HEAD"), "/pantheon/workflows", "handler"),
    (("GET", "HEAD"), "/views/workflow-apps", "list_workflow_apps"),
    (("GET", "HEAD"), "/views/process", "list_processes"),
    (("GET", "HEAD"), "/views/process/{process_id:str}", "render_process"),
    (("GET", "HEAD"), "/views/process/{process_id:str}/events", "process_events"),
    (("GET", "HEAD"), "/detection-readiness", "handler"),
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

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        self.queries.append(query)
        if self.unavailable:
            raise ProjectionUnavailableError
        return {"operation": query.operation, "token": "hidden", "items": []}

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        self.proposals.append(proposal)
        return ProposalReceipt(
            request_id="request-1",
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at="2026-08-08T00:00:00Z",
        )

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        self.replays.append(query)
        return ReplayBatch(
            events=(ReplayEvent(8, "message", {"type": "provision.progress", "secret": "x"}),),
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
    role = OperatorRole.CONTRIBUTOR if token == "contributor" else OperatorRole.READER
    return {"oid": f"{token}-oid", "roles": [role.value]}


def _client(dependencies: RecordingDependencies) -> TestClient:
    routes = build_operations_routes(
        authenticator=OperatorAuthenticator(verifier=_verify, group_ids={}),
        projection_reader=dependencies,
        proposal_writer=dependencies,
        replay_reader=dependencies,
        webhook_verifier=dependencies,
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
    assert len(OPERATIONS_ROUTE_MANIFEST) == 26


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
    )


def test_unavailable_projection_is_explicit_not_fake_empty_state() -> None:
    dependencies = RecordingDependencies()
    dependencies.unavailable = True

    response = _client(dependencies).get("/scope", headers=HEADERS)

    assert (response.status_code, response.json()) == (
        503,
        {"error": {"status": 503, "message": "authoritative projection is unavailable"}},
    )


def test_read_investigation_only_writes_durable_event_proposal() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)
    reader = client.post(
        "/read-investigations",
        headers={**HEADERS, "Idempotency-Key": "idem-1"},
        json={"prompt": "inspect"},
    )
    accepted = client.post(
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-1",
            "X-Correlation-ID": "corr-1",
        },
        json={"prompt": "inspect"},
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
            payload={"prompt": "inspect"},
        )
    ]


def test_webhook_verifies_before_proposing_and_never_mutates_provider() -> None:
    dependencies = RecordingDependencies()
    client = _client(dependencies)
    denied = client.post(
        "/webhook/azure-monitor",
        headers={"Idempotency-Key": "alert-1"},
        json={"data": "signal"},
    )
    accepted = client.post(
        "/webhook/azure-monitor",
        headers={"Idempotency-Key": "alert-1", "X-Webhook-Signature": "valid"},
        json={"data": "signal"},
    )

    assert denied.status_code == 401
    assert accepted.status_code == 202
    assert len(dependencies.proposals) == 1
    assert dependencies.proposals[0].operation == "webhook.azure_monitor"


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

    with _client(dependencies).stream(
        "POST",
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "idem-stream",
            "Last-Event-ID": "7",
            "Accept": "text/event-stream",
        },
        json={"prompt": "inspect"},
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
    assert "id: 8\nevent: message" in body


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
