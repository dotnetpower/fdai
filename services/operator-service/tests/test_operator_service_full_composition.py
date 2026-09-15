"""Full production composition tests for the independent Operator Service."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from inspect import signature
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fdai_operator_service.alert_quality_composition import build_alert_quality_bindings
from fdai_operator_service.alert_quality_runtime import AlertQualityTransport
from fdai_operator_service.alert_quality_settings import StateKvAlertQualityPreferenceStore
from fdai_operator_service.application import create_app
from fdai_operator_service.auth import OperatorAuthenticator
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


def test_assignment_transport_reexports_preserve_the_original_iam_adapters() -> None:
    from fdai_operator_service import composition, iam_composition
    from fdai_operator_service.assignment_outbox import AssignmentNoticeBridge
    from fdai_operator_service.postgres_assignment_outbox import build_assignment_notice_bridge

    assert composition.AssignmentNoticeBridge is AssignmentNoticeBridge
    assert iam_composition.AssignmentNoticeBridge is AssignmentNoticeBridge
    assert composition.build_assignment_notice_bridge is build_assignment_notice_bridge
    assert iam_composition.build_assignment_notice_bridge is build_assignment_notice_bridge


async def test_alert_composition_retains_one_bridge_for_scope_history_and_readiness() -> None:
    from fdai_operator_service import composition, outbox_runtime
    from fdai_operator_service.alert_quality_runtime import AlertQualityBridge

    store = cast(PostgresFamilyStore, object())
    transport = cast(AlertQualityTransport, object())
    authenticator = cast(OperatorAuthenticator, object())
    dependencies, bridge = build_alert_quality_bindings(
        authenticator=authenticator,
        environ={
            "FDAI_ALERT_NOISE_TRANSPORT_KEY": "test-only-transport-key-000000000",
            "FDAI_ALERT_NOISE_PRINCIPAL_SCOPES_JSON": '{"operator":["scope:example"]}',
        },
        store=store,
        transport=transport,
        event_topic="test.events",
        proposal_writer=None,
    )

    assert composition.build_alert_quality_bindings is build_alert_quality_bindings
    assert outbox_runtime.AlertQualityBridge is composition.AlertQualityBridge is AlertQualityBridge
    assert bridge is not None
    assert bridge.store is store and bridge.transport is transport
    assert bridge.scopes == frozenset({"scope:example"})
    assert dependencies.authenticator is authenticator
    assert dependencies.request_source is bridge.requests
    assert dependencies.producer_ready == bridge.producer_ready
    assert isinstance(dependencies.preference_store, StateKvAlertQualityPreferenceStore)
    assert not await dependencies.producer_ready()
    assert not bridge.workers_ready()


@pytest.mark.parametrize("missing", ["store", "transport", "event_topic"])
def test_alert_composition_cannot_replace_missing_durable_prerequisites(missing: str) -> None:
    with pytest.raises(RuntimeError, match="requires durable store and event transport"):
        build_alert_quality_bindings(
            authenticator=cast(OperatorAuthenticator, object()),
            environ={"FDAI_ALERT_NOISE_TRANSPORT_KEY": "test-only-transport-key-000000000"},
            store=None if missing == "store" else cast(PostgresFamilyStore, object()),
            transport=None if missing == "transport" else cast(AlertQualityTransport, object()),
            event_topic=None if missing == "event_topic" else "test.events",
            proposal_writer=None,
        )


def test_unconfigured_alert_composition_has_no_memory_or_worker_fallback() -> None:
    dependencies, bridge = build_alert_quality_bindings(
        authenticator=cast(OperatorAuthenticator, object()),
        environ={},
        store=None,
        transport=None,
        event_topic=None,
        proposal_writer=None,
    )

    assert bridge is None
    assert dependencies.source is dependencies.preference_store is None
    assert dependencies.request_source is dependencies.producer_ready is None
    assert dependencies.principal_scopes == {}


@pytest.mark.parametrize("unready", [None, "alert", "context"])
async def test_alert_and_context_bridges_keep_independent_lifecycle_and_readiness(
    unready: str | None,
) -> None:
    from fdai_operator_service import composition

    events: list[str] = []

    class Bridge:
        def __init__(self, name: str) -> None:
            self.name = name

        async def start(self) -> None:
            events.append("start:" + self.name)

        async def aclose(self) -> None:
            events.append("close:" + self.name)

        def workers_ready(self) -> bool:
            return self.name != unready

    alert, context = Bridge("alert"), Bridge("context")
    # Isolate the two merged lifecycle inputs; unrelated dependencies are absent.
    lifecycle_args: dict[str, Any] = {
        name: None for name in signature(composition._application_lifecycle).parameters
    }
    lifecycle_args.update(alert_quality_bridge=alert, test_context_bridge=context)
    lifecycle = composition._application_lifecycle(**lifecycle_args)
    assert isinstance(lifecycle, composition._CompositeLifecycle)
    assert lifecycle.services == (alert, context)
    await lifecycle.start()
    await lifecycle.aclose()
    assert events == ["start:alert", "start:context", "close:context", "close:alert"]

    probe_args: dict[str, Any] = {
        name: None for name in signature(composition._readiness_probe).parameters
    }
    probe_args.update(
        store=AsyncMock(probe_readiness=AsyncMock(return_value=True)),
        bus=AsyncMock(probe_readiness=AsyncMock(return_value=True)),
        alert_quality_bridge=alert,
        test_context_bridge=context,
    )
    assert await composition._readiness_probe(**probe_args)() is (unready is None)


def test_aggregate_manifest_and_registered_routes_have_exact_unique_ownership() -> None:
    manifest = aggregate_route_manifest(
        REFERENCE_PANEL_ROUTES,
        include_cost_governance=True,
    )
    identities = {(item.method, item.path) for item in manifest}
    owner_counts = Counter(item.owner for item in manifest)

    assert len(manifest) == len(identities) == 216
    assert ("GET", "/handover/readiness") in identities
    assert owner_counts == {
        "minimal": 17,
        "conversation": 43,
        "iam": 48,
        "workflow": 43,
        "operations": 42,
        "operations-panel": 8,
        "cost-governance": 8,
        "alert-quality": 7,
    }
    assert tuple(manifest[:17]) == MINIMAL_ROUTE_MANIFEST
    app = cast(Starlette, _client().app)
    assert _registered_identities(app) == identities
    assert len(app.router.routes) == 216
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
