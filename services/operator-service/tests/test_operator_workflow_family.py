"""Focused parity and authority tests for the service-local workflow family."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest
from fdai_operator_service.families.workflow import (
    WORKFLOW_FAMILY_ROUTE_MANIFEST,
    ProjectionProvenance,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
    build_workflow_family_routes,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_service_contracts import (
    GoalTaskReceipt,
    OperatorPrincipal,
    OperatorRole,
    RuleSearchProjection,
    RuleSearchReceipt,
    query_content_digest,
    rule_search_query_digest,
)
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Route
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_ROOT = REPO_ROOT / "services/operator-service/src/fdai_operator_service/families/workflow"

EXPECTED_MANIFEST = (
    ("GET", "/rules", "list_handler"),
    ("POST", "/rules/search", "search_handler"),
    ("GET", "/rules/findings-summary", "summary_handler"),
    ("GET", "/rules/{rule_id}/findings", "findings_handler"),
    ("GET", "/rules/{rule_id}", "detail_handler"),
    ("GET", "/best-practices", "list_handler"),
    ("GET", "/best-practices/{best_practice_id}", "detail_handler"),
    ("GET", "/mcsb-controls", "list_handler"),
    ("GET", "/mcsb-controls/{benchmark_version}/{control_id}", "detail_handler"),
    ("GET", "/kpi/promotion-gates", "handler"),
    ("GET", "/workflows/action-types", "handler"),
    ("POST", "/workflows/validate", "handler"),
    ("GET", "/workflows/catalog", "handler"),
    ("POST", "/workflows/run", "handler"),
    ("POST", "/workflows/{process_id}/resume", "handler"),
    ("POST", "/workflows/{process_id}/cancel", "handler"),
    ("POST", "/workflows/{process_id}/retry", "handler"),
    ("GET", "/python-tasks/capabilities", "capabilities"),
    ("POST", "/python-tasks/generate", "generate_task"),
    ("POST", "/python-tasks/validate", "validate_task"),
    ("POST", "/python-tasks/stage", "stage_task"),
    ("POST", "/python-tasks/test", "test_task"),
    ("POST", "/python-tasks/request-run", "request_run"),
    ("POST", "/python-tasks/schedule", "create_schedule"),
    ("GET", "/api/v1/skill-sources/browse", "browse"),
    ("GET", "/api/v1/skill-sources/search", "search"),
    ("GET", "/api/v1/skill-sources/{source_id:str}/inspect", "inspect"),
    ("GET", "/api/v1/skill-sources/{source_id:str}/check-update", "check_update"),
    ("GET", "/api/v1/skill-sources/{source_id:str}/candidates", "candidates"),
    ("POST", "/api/v1/skill-sources/{source_id:str}/approve-candidate", "approve"),
    ("POST", "/api/v1/skill-sources/{source_id:str}/revoke", "revoke"),
    ("GET", "/admin/trajectory-datasets", "list_datasets"),
    ("GET", "/admin/trajectory-datasets/{dataset_id}", "get_dataset"),
    ("GET", "/workflows/definitions", "catalog"),
    ("POST", "/workflows/definitions", "create_definition"),
    ("POST", "/workflows/bindings", "create_binding"),
    ("PUT", "/workflows/bindings/{binding_id:str}", "update_binding"),
    ("DELETE", "/workflows/bindings/{binding_id:str}", "delete_binding"),
)


class RecordingAuthorizer:
    """Enforce manifest roles with a selected test principal."""

    def __init__(self, role: OperatorRole) -> None:
        self.principal = OperatorPrincipal("operator", frozenset({role}))
        self.required: list[frozenset[OperatorRole]] = []

    async def __call__(self, request, required_roles):  # type: ignore[no-untyped-def]
        del request
        self.required.append(required_roles)
        if self.principal.roles.isdisjoint(required_roles):
            raise HTTPException(status_code=403, detail="principal lacks required role")
        return self.principal


class RecordingReadStore:
    """Return explicit authoritative results and retain typed requests."""

    def __init__(self) -> None:
        self.requests: list[WorkflowReadRequest] = []

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        self.requests.append(request)
        return WorkflowReadResult(
            payload={"operation": request.operation.value},
            provenance=ProjectionProvenance("catalog:commit", "revision-7"),
        )


class RecordingProposalWriter:
    """Return durable-looking receipts without executing test proposals."""

    def __init__(self) -> None:
        self.proposals: list[WorkflowProposal] = []
        self.receipts: dict[str, WorkflowProposalReceipt] = {}

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        self.proposals.append(proposal)
        receipt = self.receipts.get(proposal.idempotency_key)
        if receipt is None:
            receipt = WorkflowProposalReceipt("proposal-1", "revision-8")
            self.receipts[proposal.idempotency_key] = receipt
            return receipt
        return WorkflowProposalReceipt(receipt.proposal_id, receipt.revision, duplicate=True)


def _client(
    *, role: OperatorRole = OperatorRole.OWNER
) -> tuple[TestClient, RecordingAuthorizer, RecordingReadStore, RecordingProposalWriter]:
    authorizer = RecordingAuthorizer(role)
    reads = RecordingReadStore()
    proposals = RecordingProposalWriter()
    routes = build_workflow_family_routes(
        authorize=authorizer,
        read_store=reads,
        proposal_writer=proposals,
    )
    return TestClient(Starlette(routes=list(routes))), authorizer, reads, proposals


def _route_contract(base_route: BaseRoute) -> tuple[str, str, str]:
    route = cast(Route, base_route)
    methods = route.methods or set()
    method = next(
        candidate for candidate in ("GET", "POST", "PUT", "DELETE") if candidate in methods
    )
    return method, route.path, route.name


def test_manifest_preserves_exact_legacy_method_path_and_name_surface() -> None:
    assert (
        tuple((spec.method, spec.path, spec.name) for spec in WORKFLOW_FAMILY_ROUTE_MANIFEST)
        == EXPECTED_MANIFEST
    )
    assert len(WORKFLOW_FAMILY_ROUTE_MANIFEST) == 38
    assert sum(spec.dispatch == "proposal" for spec in WORKFLOW_FAMILY_ROUTE_MANIFEST) == 13

    client, _, _, _ = _client()
    snapshot = tuple(_route_contract(route) for route in cast(Starlette, client.app).routes)
    assert snapshot == EXPECTED_MANIFEST


def test_catalog_read_preserves_pagination_and_provenance() -> None:
    client, _, reads, proposals = _client(role=OperatorRole.READER)

    response = client.get("/rules?limit=500&offset=3&origin=active")

    assert response.status_code == 200
    assert response.headers["x-fdai-provenance"] == "catalog:commit"
    assert response.headers["x-fdai-revision"] == "revision-7"
    assert reads.requests[0].limit == 500
    assert reads.requests[0].offset == 3
    assert reads.requests[0].query == {"origin": "active"}
    assert proposals.proposals == []


def test_rule_search_validates_and_canonicalizes_exact_body() -> None:
    client, _, reads, _ = _client(role=OperatorRole.READER)
    body = {
        "query": "find retry rules",
        "operation": "discover",
        "corpus": "active",
        "limit": 7,
    }

    response = client.post("/rules/search", json=body)

    assert response.status_code == 200
    assert reads.requests[0].principal_id == "operator"
    assert reads.requests[0].body == body


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": "", "operation": "discover", "corpus": "active", "limit": 1},
        {"query": "   ", "operation": "discover", "corpus": "active", "limit": 1},
        {"query": "rules", "operation": "discover", "corpus": "active", "limit": 21},
        {
            "query": "rules",
            "operation": "discover",
            "corpus": "active",
            "limit": 1,
            "execution_authority": True,
        },
    ],
)
def test_rule_search_rejects_invalid_or_authority_bearing_body(body: object) -> None:
    client, _, reads, _ = _client(role=OperatorRole.READER)

    response = client.post("/rules/search", json=body)

    assert response.status_code == 400
    assert reads.requests == []


async def test_rule_search_adapter_reads_exact_principal_and_query_projection() -> None:
    body = {
        "query": "find retry rules",
        "operation": "discover",
        "corpus": "active",
        "limit": 7,
    }
    query_digest = rule_search_query_digest(body)
    receipt = RuleSearchReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "query_digest": query_digest,
            "operation": "discover",
            "corpus": "active",
            "catalog_digest": f"sha256:{'c' * 64}",
            "semantic_state": "available",
            "generation_digest": f"sha256:{'d' * 64}",
            "results": [],
            "execution_authority": False,
        }
    )
    function_receipt = GoalTaskReceipt.model_validate(
        {
            "task_id": "query:resources",
            "goal_id": "resources",
            "intent": "function",
            "capability": "query.function",
            "evidence_mode": "operational",
            "status": "completed",
            "duration_ms": 5,
            "evidence_refs": ["catalog:rule.one"],
            "started_at": "2026-08-11T00:00:00Z",
            "completed_at": "2026-08-11T00:00:00Z",
        }
    )
    projection = RuleSearchProjection.model_validate(
        {
            "query_digest": query_digest,
            "retrieval_receipt_digest": receipt.digest,
            "function_invocation_receipt_digest": query_content_digest(
                function_receipt.model_dump(mode="json")
            ),
            "candidates": [],
            "retrieval_receipt": receipt.model_dump(mode="json"),
            "function_invocation_receipt": function_receipt.model_dump(mode="json"),
            "authority": "candidate_only",
            "execution_authority": False,
        }
    ).model_dump(mode="json")

    class ExactStore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def read_rule_search_projection(
            self,
            *,
            principal_id: str,
            query_digest: str,
        ) -> dict[str, object]:
            self.calls.append((principal_id, query_digest))
            return {"_revision": "projection-7", "data": projection}

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            raise AssertionError(f"unexpected global read: {family}:{operation}")

    store = ExactStore()
    adapter = PostgresWorkflowAdapters(cast(Any, store))
    result = await adapter.read(
        WorkflowReadRequest(
            operation=next(
                spec.operation
                for spec in WORKFLOW_FAMILY_ROUTE_MANIFEST
                if spec.path == "/rules/search"
            ),
            principal_id="operator-a",
            query={},
            path_parameters={},
            body=body,
        )
    )

    assert store.calls == [("operator-a", query_digest)]
    assert result.payload == projection
    assert result.provenance.revision == "projection-7"
    assert result.provenance.source_ref.startswith(
        "state_kv:operator-projection:workflow:rule.search:"
    )


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "limit=many", "offset=-1"])
def test_catalog_pagination_rejects_legacy_invalid_bounds(query: str) -> None:
    client, _, reads, _ = _client(role=OperatorRole.READER)
    assert client.get(f"/rules?{query}").status_code == 400
    assert reads.requests == []


def test_read_routes_enforce_specific_owner_and_search_validation() -> None:
    reader, _, reads, _ = _client(role=OperatorRole.READER)
    assert (
        reader.get("/admin/trajectory-datasets?purpose=review&access_scope=team").status_code == 403
    )
    assert reader.get("/api/v1/skill-sources/search?q=").status_code == 400
    assert reads.requests == []

    owner, _, owner_reads, _ = _client(role=OperatorRole.OWNER)
    accepted = owner.get("/admin/trajectory-datasets?purpose=review&access_scope=team&limit=25")
    assert accepted.status_code == 200
    assert owner_reads.requests[0].limit == 25


def test_mutation_routes_require_revision_and_idempotency_before_submission() -> None:
    client, _, _, proposals = _client(role=OperatorRole.CONTRIBUTOR)
    payload = {"workflow": "sample", "target_resource_id": "resource-1"}

    assert client.post("/workflows/run", json=payload).status_code == 428
    assert (
        client.post(
            "/workflows/run",
            json=payload,
            headers={"Idempotency-Key": "request-1"},
        ).status_code
        == 428
    )
    assert proposals.proposals == []

    accepted = client.post(
        "/workflows/run",
        json=payload,
        headers={"Idempotency-Key": "request-1", "If-Match": "workflow-revision-2"},
    )
    duplicate = client.post(
        "/workflows/run",
        json=payload,
        headers={"Idempotency-Key": "request-1", "If-Match": "workflow-revision-2"},
    )

    assert accepted.status_code == 202
    assert accepted.json()["mode"] == "shadow"
    assert duplicate.json()["duplicate"] is True
    assert proposals.proposals[0].expected_revision == "workflow-revision-2"
    assert proposals.proposals[0].request_source == "operator-http:handler"


def test_enforce_request_is_rejected_without_calling_proposal_writer() -> None:
    client, _, _, proposals = _client(role=OperatorRole.OWNER)
    response = client.post(
        "/workflows/run",
        json={
            "workflow": "sample",
            "target_resource_id": "resource-1",
            "mode": "enforce",
        },
        headers={"Idempotency-Key": "request-1", "If-Match": "revision-1"},
    )
    assert response.status_code == 409
    assert proposals.proposals == []


def test_skill_candidate_approval_is_an_approver_gated_proposal() -> None:
    contributor, _, _, contributor_proposals = _client(role=OperatorRole.CONTRIBUTOR)
    headers = {"Idempotency-Key": "approval-1", "If-Match": "candidate-revision-4"}
    assert (
        contributor.post(
            "/api/v1/skill-sources/source-a/approve-candidate",
            json={"candidate_id": "candidate-a"},
            headers=headers,
        ).status_code
        == 403
    )
    assert contributor_proposals.proposals == []

    approver, _, _, proposals = _client(role=OperatorRole.APPROVER)
    response = approver.post(
        "/api/v1/skill-sources/source-a/approve-candidate",
        json={"candidate_id": "candidate-a"},
        headers=headers,
    )
    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert "promoted" not in response.json()
    assert proposals.proposals[0].path_parameters == {"source_id": "source-a"}


def test_payload_caps_fail_before_any_store_or_writer_call() -> None:
    client, _, reads, proposals = _client(role=OperatorRole.OWNER)
    oversized = {"blob": "x" * 4_097}
    response = client.post(
        "/api/v1/skill-sources/source-a/revoke",
        json=oversized,
        headers={"Idempotency-Key": "revoke-1", "If-Match": "revision-1"},
    )
    assert response.status_code == 413
    assert reads.requests == []
    assert proposals.proposals == []


def test_family_has_no_fdai_import_or_direct_authority_call() -> None:
    for path in FAMILY_ROOT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name == "fdai" or name.startswith("fdai.") for name in imported)
        assert ".execute(" not in source
        assert ".promote(" not in source


def test_synthetic_projection_is_rejected_at_the_contract_boundary() -> None:
    with pytest.raises(ValueError, match="MUST NOT return synthetic"):
        ProjectionProvenance("fixture", "revision-1", synthetic=True)
