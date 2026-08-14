"""Focused parity and authority tests for the Operator operations family."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations import (
    OPERATIONS_ROUTE_MANIFEST,
    EventProposal,
    PanelRoute,
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
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
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
        self.projections: dict[str, Mapping[str, object]] = {}
        self.replay_events = (
            ReplayEvent(8, "message", {"type": "provision.progress", "secret": "x"}),
        )

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        self.queries.append(query)
        if self.unavailable:
            raise ProjectionUnavailableError
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
    assert len(OPERATIONS_ROUTE_MANIFEST) == 30


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
    )


def test_unavailable_projection_is_explicit_not_fake_empty_state() -> None:
    dependencies = RecordingDependencies()
    dependencies.unavailable = True

    response = _client(dependencies).get("/scope", headers=HEADERS)

    assert (response.status_code, response.json()) == (
        503,
        {"error": {"status": 503, "message": "authoritative projection is unavailable"}},
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
