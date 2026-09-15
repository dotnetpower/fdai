"""Full production composition tests for the independent Operator Service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, cast

import pytest
from fdai_operator_service.application import create_app
from fdai_operator_service.composition import REFERENCE_PANEL_ROUTES, ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    TENANT_ENV,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStore, StoredProposal
from fdai_operator_service.postgres_test_context import PostgresTestContextOutbox
from fdai_operator_service.routes import MINIMAL_ROUTE_MANIFEST, aggregate_route_manifest
from fdai_service_contracts import OperatorRole
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

BASE_ENV = {
    TENANT_ENV: "tenant",
    AUDIENCE_ENV: "audience",
    **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
}


def _verify(token: str) -> Mapping[str, object]:
    roles = {
        "reader": [OperatorRole.READER.value],
        "contributor": [OperatorRole.CONTRIBUTOR.value],
        "approver": [OperatorRole.APPROVER.value],
        "owner": [OperatorRole.OWNER.value],
    }.get(token, [])
    return {"oid": f"{token}-operator", "idtyp": "user", "roles": roles}


def _client(overrides: Mapping[str, str] | None = None) -> TestClient:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    return TestClient(create_app({**BASE_ENV, **dict(overrides or {})}, composition=composition))


def _registered_identities(app: Starlette) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.router.routes
        if isinstance(route, Route)
        for method in (route.methods or set())
        if method not in {"HEAD", "OPTIONS"}
    }


def test_aggregate_manifest_and_registered_routes_have_exact_unique_ownership() -> None:
    manifest = aggregate_route_manifest(
        REFERENCE_PANEL_ROUTES,
        include_cost_governance=True,
    )
    identities = {(item.method, item.path) for item in manifest}
    owner_counts = Counter(item.owner for item in manifest)

    assert len(manifest) == len(identities) == 201
    assert owner_counts == {
        "minimal": 16,
        "conversation": 43,
        "iam": 41,
        "workflow": 43,
        "operations": 42,
        "operations-panel": 8,
        "cost-governance": 8,
    }
    assert tuple(manifest[:16]) == MINIMAL_ROUTE_MANIFEST
    app = cast(Starlette, _client().app)
    assert _registered_identities(app) == identities
    assert len(app.router.routes) == 201
    assert {
        ("POST", "/test-context/proposals"),
        ("POST", "/test-context/reviews"),
        ("POST", "/test-context/revocations"),
    } <= identities


def test_unavailable_families_enforce_authentication_and_rbac_before_503() -> None:
    client = _client()

    unauthenticated = client.get("/me/context")
    unavailable_read = client.get(
        "/me/context",
        headers={"Authorization": "Bearer reader"},
    )
    forbidden_write = client.post(
        "/workflows/run",
        headers={
            "Authorization": "Bearer reader",
            "Idempotency-Key": "workflow-1",
            "If-Match": "revision-1",
        },
        json={"workflow": "sample"},
    )
    unavailable_write = client.post(
        "/workflows/run",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "workflow-1",
            "If-Match": "revision-1",
        },
        json={"workflow": "sample"},
    )
    unavailable_directory = client.get(
        "/iam/directory/users?q=operator",
        headers={"Authorization": "Bearer owner"},
    )
    unsigned_callback = client.post("/hil/approval-1/decision", json={})

    assert unauthenticated.status_code == 401
    assert unavailable_read.status_code == 503
    assert unavailable_read.json()["error"]["code"] == "unavailable"
    assert forbidden_write.status_code == 403
    assert unavailable_write.status_code == 503
    assert unavailable_directory.status_code == 503
    assert unsigned_callback.status_code == 503


def _context_request():
    return {
        "operation": "propose",
        "context_id": "example",
        "access_scope_digest": "a" * 64,
        "target_ref": "resource-example",
        "signal_code": "cpu_percent",
        "expected_revision": 0,
        "policy_revision": "policy:example",
        "source_ref": "turn:example",
        "semantic_receipt": "sha256:" + "b" * 64,
        "expected_min": 60,
        "expected_max": 90,
        "effective_from": "2026-09-15T00:00:00+00:00",
        "effective_to": "2026-09-15T01:00:00+00:00",
    }


@pytest.mark.parametrize(
    "operation,path,role,status",
    [
        ("propose", "proposals", "reader", 403),
        ("propose", "proposals", "contributor", 202),
        ("review", "reviews", "contributor", 403),
        ("review", "reviews", "approver", 202),
        ("revoke", "revocations", "contributor", 403),
        ("revoke", "revocations", "owner", 202),
    ],
)
def test_context_routes_authenticate_role_before_durable_acceptance(
    monkeypatch, operation, path, role, status
):
    from unittest.mock import AsyncMock

    captured = AsyncMock(
        return_value=StoredProposal(
            proposal_id="operator-proposal-1",
            accepted_at="2026-09-15T00:00:00+00:00",
            duplicate=False,
            record={},
        )
    )
    monkeypatch.setattr(PostgresFamilyStore, "append_proposal", captured)
    client = _client(
        {DATABASE_URL_ENV: "postgresql://example.invalid/fdai", DATABASE_ROLE_ENV: "fdai_operator"}
    )
    body = _context_request()
    if operation != "propose":
        for key in ("expected_min", "expected_max", "effective_from", "effective_to"):
            body.pop(key)
        body.update(operation=operation, expected_revision=1)
    response = client.post(
        "/test-context/" + path,
        headers={"Authorization": "Bearer " + role, "Idempotency-Key": "context-http"},
        json=body,
    )
    assert response.status_code == status, response.text
    if status == 202:
        captured.assert_awaited_once()
        values = captured.await_args.kwargs
        assert values["principal_id"] == role + "-operator"
        assert values["payload"]["scope"]["subject_id"] == values["principal_id"]
        assert values["operation"] == "test-context." + operation
    else:
        captured.assert_not_awaited()


@pytest.mark.parametrize("owner", [True, False])
def test_context_status_returns_only_own_delivery_and_never_claims_policy_application(
    monkeypatch, owner
):
    from unittest.mock import AsyncMock

    stored = {
        "proposal_id": "operator-example",
        "operation": "test-context.propose",
        "dispatch_status": "published",
        "accepted_at": "2026-09-15T00:00:00+00:00",
    }
    read = AsyncMock(return_value=stored if owner else None)
    monkeypatch.setattr(PostgresTestContextOutbox, "read_test_context_command", read)
    client = _client(
        {DATABASE_URL_ENV: "postgresql://example.invalid/fdai", DATABASE_ROLE_ENV: "fdai_operator"}
    )
    response = client.get(
        "/test-context/commands/operator-example", headers={"Authorization": "Bearer contributor"}
    )
    assert response.status_code == (200 if owner else 404)
    read.assert_awaited_once_with(
        proposal_id="operator-example", principal_id="contributor-operator"
    )
    if owner:
        assert response.json()["policy_application"] == "unknown"
        assert response.json()["execution_authority"] is False


def test_context_http_rejects_actor_injection_before_outbox(monkeypatch):
    from unittest.mock import AsyncMock

    captured = AsyncMock()
    monkeypatch.setattr(PostgresFamilyStore, "append_proposal", captured)
    client = _client(
        {DATABASE_URL_ENV: "postgresql://example.invalid/fdai", DATABASE_ROLE_ENV: "fdai_operator"}
    )
    response = client.post(
        "/test-context/proposals",
        headers={"Authorization": "Bearer contributor", "Idempotency-Key": "context-http"},
        json={**_context_request(), "actor_id": "other-operator"},
    )
    assert response.status_code == 422
    captured.assert_not_awaited()


def test_configured_postgres_adapters_dispatch_reads_and_typed_proposals(
    monkeypatch: Any,
) -> None:
    reads: list[tuple[str, str]] = []
    proposals: list[dict[str, object]] = []

    async def read_projection(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
    ) -> dict[str, object]:
        del self
        reads.append((family, operation))
        return {"_revision": "revision-7", "rules": [], "details": {}}

    async def append_proposal(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> StoredProposal:
        del self
        proposals.append(
            {
                "family": family,
                "operation": operation,
                "principal_id": principal_id,
                "idempotency_key": idempotency_key,
                "payload": dict(payload),
            }
        )
        return StoredProposal(
            proposal_id="operator-proposal-1",
            accepted_at="2026-08-08T00:00:00+00:00",
            duplicate=False,
            record={},
        )

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    monkeypatch.setattr(PostgresFamilyStore, "append_proposal", append_proposal)
    client = _client(
        {
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    projected = client.get("/rules", headers={"Authorization": "Bearer reader"})
    proposed = client.post(
        "/read-investigations",
        headers={
            "Authorization": "Bearer contributor",
            "Idempotency-Key": "investigation-1",
            "X-Correlation-ID": "correlation-1",
        },
        json={
            "prompt": "Inspect bounded evidence.",
            "intent": "resource_state",
            "resource_name": "service-one",
        },
    )

    assert projected.status_code == 200
    assert projected.headers["x-fdai-provenance"].startswith("state_kv:")
    assert reads == [("workflow", "rule.list")]
    assert proposed.status_code == 202
    assert proposed.json()["dispatch_status"] == "pending"
    assert proposals == [
        {
            "family": "operations",
            "operation": "read_investigation.start",
            "principal_id": "contributor-operator",
            "idempotency_key": "investigation-1",
            "payload": {
                "operation": "read_investigation.start",
                "principal_id": "contributor-operator",
                "idempotency_key": "investigation-1",
                "correlation_id": "correlation-1",
                "payload": {
                    "prompt": "Inspect bounded evidence.",
                    "intent": "resource_state",
                    "resource_name": "service-one",
                    "explicit_deep": False,
                },
            },
        }
    ]
