"""Full production composition tests for the independent Operator Service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, cast

from fdai_operator_service.application import create_app
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    TENANT_ENV,
)
from fdai_operator_service.postgres_family_store import PostgresFamilyStore, StoredProposal
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
    return {"oid": f"{token}-operator", "roles": roles}


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
    manifest = aggregate_route_manifest()
    identities = {(item.method, item.path) for item in manifest}
    owner_counts = Counter(item.owner for item in manifest)

    assert len(manifest) == len(identities) == 142
    assert owner_counts == {
        "minimal": 13,
        "conversation": 38,
        "iam": 27,
        "workflow": 38,
        "operations": 26,
    }
    assert tuple(manifest[:13]) == MINIMAL_ROUTE_MANIFEST
    app = cast(Starlette, _client().app)
    assert _registered_identities(app) == identities
    assert len(app.router.routes) == 142


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
        return {"_revision": "revision-7", "items": []}

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
        json={"prompt": "Inspect bounded evidence."},
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
                "payload": {"prompt": "Inspect bounded evidence."},
            },
        }
    ]
