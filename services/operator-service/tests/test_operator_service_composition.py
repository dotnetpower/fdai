"""Service-owned production composition tests for the independent Operator role."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import fdai_operator_service.composition as operator_composition
import pytest
from fdai_operator_service.adapters.narrator_periodic_scheduler import (
    PeriodicNarratorRefreshScheduler,
)
from fdai_operator_service.application import create_app
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.contracts import ReadinessProbe
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    CORS_ORIGINS_ENV,
    DATABASE_ROLE_ENV,
    DATABASE_URL_ENV,
    DEFAULT_LIVE_STAGE_CONSUMER_GROUP,
    GROUP_ENV,
    HIL_DECISION_TOPIC_ENV,
    HOST_ENV,
    KAFKA_BOOTSTRAP_SERVERS_ENV,
    LIVE_STAGE_CONSUMER_GROUP_ENV,
    LOCAL_AZURE_CLI_AUTH_ENV,
    LOCAL_AZURE_NARRATOR_ENV,
    LOCAL_ENTRA_AUTH_ENV,
    MANAGED_IDENTITY_CLIENT_ID_ENV,
    NARRATOR_PROBE_INTERVAL_ENV,
    PORT_ENV,
    READ_INVESTIGATION_REQUEST_TOPIC_ENV,
    SEMANTIC_CONSUMER_GROUP_ENV,
    SEMANTIC_KAFKA_CLIENT_ID_ENV,
    SEMANTIC_OUTBOX_NAMESPACE_ENV,
    SEMANTIC_PHYSICAL_TOPIC_ENV,
    SEMANTIC_PROJECTION_TOPIC_ENV,
    SEMANTIC_REQUEST_TOPIC_ENV,
    TENANT_ENV,
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.families.iam import make_iam_family_routes
from fdai_operator_service.families.iam.hil_decision_outbox import (
    DurableHilDecisionOutboxPublisher,
)
from fdai_operator_service.families.iam.hil_teams_callback import (
    TeamsHilCallbackNormalizer,
)
from fdai_operator_service.local_auth import AzureCliIdentityError, LocalAzureCliIdentity
from fdai_operator_service.main import SERVICE
from fdai_operator_service.parity import BLOCKED_ROUTE_PATHS, PARITY_COMPLETE, ROUTE_PARITY
from fdai_operator_service.postgres import PostgresOperatorReadModel
from fdai_operator_service.production import serve
from fdai_operator_service.projections import ProjectionUnavailableError
from fdai_service_contracts import (
    AgentActivityQuery,
    AuditQuery,
    BrowserEvidenceQuery,
    HilQueueProjection,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentPageProjection,
    IncidentQuery,
    JsonProjection,
    OperatorPrincipal,
    OperatorPrincipalKind,
    OperatorReadModel,
    OperatorRole,
    OperatorTokenVerifier,
    PageProjection,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_SOURCE = REPO_ROOT / "services/operator-service/src/fdai_operator_service"
LEGACY_ADAPTER = SERVICE_SOURCE / "legacy_adapter.py"
BASE_ENV = {
    TENANT_ENV: "tenant",
    AUDIENCE_ENV: "audience",
    **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
}

EXPECTED_ROUTES = (
    (("GET", "HEAD"), "/agents/activity", "get_agent_activity"),
    (("GET", "HEAD"), "/agents/stream", "agent_stream"),
    (("GET", "HEAD"), "/audit", "get_audit"),
    (("GET", "HEAD"), "/audit/{correlation_id}/trace", "rule_fire_trace"),
    (("GET", "HEAD"), "/browser-evidence", "get_browser_evidence"),
    (("GET", "HEAD"), "/healthz", "healthz"),
    (("GET", "HEAD"), "/hil-queue", "get_hil_queue"),
    (("GET", "HEAD"), "/incidents", "panel:incidents"),
    (("GET", "HEAD"), "/incidents/stream", "incident_attention_stream"),
    (("GET", "HEAD"), "/kpi", "get_kpi"),
    (("GET", "HEAD"), "/kpi/llm-cost", "get_llm_cost"),
    (("GET", "HEAD"), "/live/stream", "live_stream"),
    (
        ("GET", "HEAD"),
        "/notification-templates/incident-opened",
        "get_incident_opened_template",
    ),
    (("GET", "HEAD"), "/rca", "panel:rca"),
    (("GET", "HEAD"), "/system/data-sources", "get_data_sources"),
    (("POST",), "/incidents/{correlation_id}/interventions", "post_incident_intervention"),
)


class EmptyReadModel(OperatorReadModel):
    """Authoritative empty projection used only by service boundary tests."""

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        del query
        return JsonProjection({"items": [], "snapshot_at": "", "source": "durable"})

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        del query
        return PageProjection(items=(), next_cursor=None)

    async def list_browser_evidence(self, query: BrowserEvidenceQuery) -> JsonProjection:
        return JsonProjection(
            {"surface": "browser-evidence", "items": [], "count": 0, "limit": query.limit}
        )

    async def dashboard_metrics(self) -> JsonProjection:
        return JsonProjection({"event_count": 0})

    async def llm_usage(self, range_start: datetime, range_end: datetime) -> JsonProjection:
        return JsonProjection(
            {
                "source": "metering",
                "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
            }
        )

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection:
        del query
        return HilQueueProjection(items=(), total=0)

    async def list_incidents(self, query: IncidentQuery) -> IncidentPageProjection:
        del query
        return IncidentPageProjection(items=(), next_cursor=None, metrics={})

    async def incident_attention(
        self, query: IncidentAttentionQuery
    ) -> IncidentAttentionProjection | None:
        del query
        return IncidentAttentionProjection(
            sequence=0,
            payload={"event": "incident_attention.snapshot", "ts": "", "incidents": []},
        )

    async def get_rca(self, correlation_id: str) -> JsonProjection | None:
        del correlation_id
        return None

    async def get_rule_fire_trace(self, correlation_id: str) -> JsonProjection | None:
        del correlation_id
        return None


def _verify(token: str) -> Mapping[str, object]:
    roles: list[str]
    if token == "reader":
        roles = [OperatorRole.READER.value]
    elif token == "approver":
        roles = [OperatorRole.APPROVER.value]
    else:
        roles = []
    return {"oid": "operator", "roles": roles}


def _client(
    *,
    read_model: OperatorReadModel | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> TestClient:
    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=read_model,
        readiness_probe=readiness_probe,
    )
    return TestClient(create_app(BASE_ENV, composition=composition))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _fdai_imports(path: Path) -> set[str]:
    return {name for name in _imports(path) if name == "fdai" or name.startswith("fdai.")}


def test_service_package_has_no_fdai_implementation_import() -> None:
    for path in SERVICE_SOURCE.rglob("*.py"):
        assert _fdai_imports(path) == set()
        assert "importlib" not in _imports(path)
    assert not LEGACY_ADAPTER.exists()


def test_service_distribution_has_no_fdai_runtime_dependency() -> None:
    project = tomllib.loads(
        (REPO_ROOT / "services/operator-service/pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    dependencies = project["dependencies"]
    assert "fdai-service-contracts==0.1.0" in dependencies
    assert not any(dependency.startswith("weasyprint") for dependency in dependencies)
    assert project["optional-dependencies"]["pdf-report"] == ["weasyprint>=66,<70"]
    assert not any(
        dependency == "fdai" or dependency.startswith(("fdai[", "fdai==", "fdai>=", "fdai<"))
        for dependency in dependencies
    )


def test_pdf_report_extra_registers_only_service_local_encoder() -> None:
    pytest.importorskip("weasyprint", reason="requires fdai-operator-service[pdf-report]")
    runtime = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
    ).build_runtime(BASE_ENV)

    encoder = runtime.route_families.report_pdf_encoder

    assert encoder is not None
    assert encoder.name == "pdf"
    assert encoder.content_type == "application/pdf"


def test_service_package_imports_no_fdai_core_module() -> None:
    for path in SERVICE_SOURCE.rglob("*.py"):
        assert {
            name for name in _imports(path) if name == "fdai.core" or name.startswith("fdai.core.")
        } == set()


@pytest.mark.parametrize(
    "layer",
    ["main.py", "application.py", "routes.py", "production.py", "composition.py"],
)
def test_production_layers_import_no_fdai_implementation(layer: str) -> None:
    assert _fdai_imports(SERVICE_SOURCE / layer) == set()


def test_descriptor_identifies_independent_operator_distribution() -> None:
    assert SERVICE.service_id == "operator-service"
    assert SERVICE.distribution == "fdai-operator-service"
    assert SERVICE.entrypoint == "fdai-operator-service"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({HOST_ENV: ""}, HOST_ENV),
        ({PORT_ENV: "zero"}, PORT_ENV),
        ({PORT_ENV: "0"}, PORT_ENV),
        ({PORT_ENV: "65536"}, PORT_ENV),
        ({TENANT_ENV: ""}, TENANT_ENV),
        ({CORS_ORIGINS_ENV: "*"}, CORS_ORIGINS_ENV),
    ],
)
def test_invalid_environment_fails_before_verifier_construction(
    overrides: Mapping[str, str],
    message: str,
) -> None:
    called = False

    def verifier_factory(environment: OperatorEnvironment) -> OperatorTokenVerifier:
        nonlocal called
        del environment
        called = True
        raise AssertionError("invalid configuration MUST fail before verifier loading")

    with pytest.raises(OperatorServiceConfigurationError, match=message):
        create_app(
            {**BASE_ENV, **overrides},
            composition=ProductionOperatorComposition(verifier_factory=verifier_factory),
        )
    assert not called


def test_service_preserves_exact_frozen_minimal_routes() -> None:
    app = cast(Starlette, _client(read_model=EmptyReadModel()).app)
    minimal_paths = {item[1] for item in EXPECTED_ROUTES}
    snapshot = tuple(
        sorted(
            (
                tuple(sorted(getattr(route, "methods", ()) or ())),
                getattr(route, "path", ""),
                getattr(route, "name", ""),
            )
            for route in app.router.routes
            if getattr(route, "path", "") in minimal_paths
        )
    )
    assert snapshot == EXPECTED_ROUTES


def test_health_is_public_and_fails_closed_without_postgres() -> None:
    response = _client().get("/healthz")
    assert (response.status_code, response.json()) == (503, {"status": "not-ready"})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_health_reflects_required_dependency_loss_after_startup() -> None:
    available = True

    async def readiness_probe() -> bool:
        return available

    client = _client(read_model=EmptyReadModel(), readiness_probe=readiness_probe)
    response = client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})

    available = False
    response = client.get("/healthz")
    assert (response.status_code, response.json()) == (503, {"status": "not-ready"})


def _local_cli_identity() -> LocalAzureCliIdentity:
    return LocalAzureCliIdentity(
        principal=OperatorPrincipal(
            subject_id="cli-user",
            roles=frozenset({OperatorRole.CONTRIBUTOR}),
            principal_kind=OperatorPrincipalKind.HUMAN,
        ),
        username="operator@example.com",
        name="Example Operator",
    )


def test_local_cli_mode_projects_profile_and_authorizes_reader_routes() -> None:
    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
        local_cli_identity_factory=_local_cli_identity,
        local_cli_session_token_factory=lambda: "local-session-token",
    )
    client = TestClient(
        create_app(
            {
                **BASE_ENV,
                "RUNTIME_ENV": "dev",
                LOCAL_AZURE_CLI_AUTH_ENV: "1",
                CORS_ORIGINS_ENV: "http://127.0.0.1:5273",
            },
            composition=composition,
        ),
        client=("127.0.0.1", 50000),
    )

    request_headers = {"Origin": "http://127.0.0.1:5273"}
    profile = client.get("/local-auth/me", headers=request_headers)
    audit = client.get(
        "/audit",
        headers={
            **request_headers,
            "Authorization": f"Bearer {profile.headers['x-fdai-local-session']}",
        },
    )

    assert profile.status_code == 200
    assert profile.json() == {
        "oid": "cli-user",
        "username": "operator@example.com",
        "name": "Example Operator",
        "roles": ["Contributor"],
        "source": "azure-cli",
    }
    assert "tenant" not in profile.text
    assert "subscription" not in profile.text
    assert "token" not in profile.text
    assert profile.headers["x-fdai-local-session"] == "local-session-token"
    assert profile.headers["cache-control"] == "no-store"
    assert audit.status_code == 200


def test_local_cli_mode_rejects_non_loopback_requests() -> None:
    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
        local_cli_identity_factory=_local_cli_identity,
        local_cli_session_token_factory=lambda: "local-session-token",
    )
    client = TestClient(
        create_app(
            {
                **BASE_ENV,
                "RUNTIME_ENV": "dev",
                LOCAL_AZURE_CLI_AUTH_ENV: "1",
            },
            composition=composition,
        ),
        client=("192.0.2.1", 50000),
    )

    profile = client.get(
        "/local-auth/me",
        headers={"Origin": "http://127.0.0.1:5273"},
    )
    audit = client.get(
        "/audit",
        headers={"Authorization": "Bearer local-session-token"},
    )

    assert profile.status_code == 403
    assert audit.status_code == 403


def test_local_cli_mode_rejects_untrusted_browser_origin() -> None:
    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
        local_cli_identity_factory=_local_cli_identity,
        local_cli_session_token_factory=lambda: "local-session-token",
    )
    client = TestClient(
        create_app(
            {
                **BASE_ENV,
                "RUNTIME_ENV": "dev",
                LOCAL_AZURE_CLI_AUTH_ENV: "1",
                CORS_ORIGINS_ENV: "http://127.0.0.1:5273",
            },
            composition=composition,
        ),
        client=("127.0.0.1", 50000),
    )

    response = client.get(
        "/local-auth/me",
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 403


def test_local_cli_profile_route_is_absent_when_mode_is_disabled() -> None:
    assert _client(read_model=EmptyReadModel()).get("/local-auth/me").status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {LOCAL_AZURE_CLI_AUTH_ENV: "1", "RUNTIME_ENV": "prod"},
        {
            LOCAL_AZURE_CLI_AUTH_ENV: "1",
            "RUNTIME_ENV": "dev",
            "FDAI_OPERATOR_API_DEV_MODE": "1",
        },
        {
            LOCAL_AZURE_CLI_AUTH_ENV: "1",
            "RUNTIME_ENV": "dev",
            LOCAL_ENTRA_AUTH_ENV: "1",
        },
    ],
)
def test_local_cli_mode_rejects_non_dev_and_conflicting_auth(
    overrides: Mapping[str, str],
) -> None:
    with pytest.raises(OperatorServiceConfigurationError):
        OperatorEnvironment.parse({**BASE_ENV, **overrides})


def test_local_cli_mode_surfaces_unavailable_azure_cli() -> None:
    def unavailable() -> LocalAzureCliIdentity:
        raise AzureCliIdentityError("Azure CLI is unavailable")

    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        local_cli_identity_factory=unavailable,
        local_cli_session_token_factory=lambda: "local-session-token",
    )
    with pytest.raises(AzureCliIdentityError, match="unavailable"):
        composition.build_runtime(
            {
                **BASE_ENV,
                "RUNTIME_ENV": "dev",
                LOCAL_AZURE_CLI_AUTH_ENV: "1",
            }
        )


def test_live_stream_requires_reader_authentication_before_opening() -> None:
    response = _client(read_model=EmptyReadModel()).get("/live/stream")

    assert response.status_code == 401


def test_agent_stream_requires_reader_authentication_before_opening() -> None:
    response = _client(read_model=EmptyReadModel()).get("/agents/stream")

    assert response.status_code == 401


def test_agent_activity_requires_reader_and_returns_durable_snapshot() -> None:
    client = _client(read_model=EmptyReadModel())

    unauthenticated = client.get("/agents/activity")
    success = client.get(
        "/agents/activity?limit=25",
        headers={"Authorization": "Bearer reader"},
    )

    assert unauthenticated.status_code == 401
    assert success.status_code == 200
    assert success.json() == {"items": [], "snapshot_at": "", "source": "durable"}


def test_authenticated_audit_envelopes_are_stable() -> None:
    client = _client(read_model=EmptyReadModel())
    missing = client.get("/audit")
    malformed = client.get("/audit", headers={"Authorization": "Basic token"})
    forbidden = client.get("/audit", headers={"Authorization": "Bearer no-role"})
    invalid = client.get("/audit?limit=invalid", headers={"Authorization": "Bearer reader"})
    success = client.get("/audit", headers={"Authorization": "Bearer reader"})

    assert (missing.status_code, missing.json()) == (
        401,
        {"error": {"status": 401, "message": "Authorization header missing"}},
    )
    assert malformed.status_code == 401
    assert forbidden.status_code == 403
    assert invalid.status_code == 400
    assert (success.status_code, success.json()) == (
        200,
        {"items": [], "next_cursor": None},
    )


def test_browser_evidence_is_reader_scoped_get_only_and_bounded() -> None:
    client = _client(read_model=EmptyReadModel())
    headers = {"Authorization": "Bearer reader"}

    assert client.get("/browser-evidence").status_code == 401
    assert (
        client.get(
            "/browser-evidence",
            headers={"Authorization": "Bearer no-role"},
        ).status_code
        == 403
    )
    assert client.get("/browser-evidence?limit=0", headers=headers).status_code == 400
    success = client.get("/browser-evidence?limit=25", headers=headers)
    assert (success.status_code, success.json()) == (
        200,
        {"surface": "browser-evidence", "items": [], "count": 0, "limit": 25},
    )
    assert client.post("/browser-evidence", headers=headers).status_code == 405


def test_llm_usage_requires_one_bounded_timezone_aware_range() -> None:
    client = _client(read_model=EmptyReadModel())
    headers = {"Authorization": "Bearer reader"}

    missing = client.get("/kpi/llm-cost", headers=headers)
    naive = client.get(
        "/kpi/llm-cost?from=2026-08-01T00:00:00&to=2026-08-02T00:00:00Z",
        headers=headers,
    )
    too_long = client.get(
        "/kpi/llm-cost?from=2026-01-01T00:00:00Z&to=2026-08-02T00:00:00Z",
        headers=headers,
    )
    success = client.get(
        "/kpi/llm-cost?from=2026-08-01T00:00:00Z&to=2026-08-02T00:00:00Z",
        headers=headers,
    )

    assert missing.status_code == 400
    assert naive.status_code == 400
    assert too_long.status_code == 400
    assert (success.status_code, success.json()["source"]) == (200, "metering")


def test_mapping_shaped_roles_claim_does_not_grant_operator_access() -> None:
    def verify_mapping_role(token: str) -> Mapping[str, object]:
        del token
        return {"oid": "operator", "roles": {OperatorRole.OWNER.value: True}}

    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: verify_mapping_role,
        read_model=EmptyReadModel(),
    )
    client = TestClient(create_app(BASE_ENV, composition=composition))

    response = client.get("/audit", headers={"Authorization": "Bearer malformed-role"})

    assert response.status_code == 403


def test_unbound_projection_fails_closed_instead_of_returning_empty_live_state() -> None:
    response = _client().get("/audit", headers={"Authorization": "Bearer reader"})
    assert (response.status_code, response.json()) == (
        503,
        {
            "error": {
                "status": 503,
                "message": "authoritative Operator projection is unavailable",
            }
        },
    )


def test_database_url_binds_service_owned_postgres_projection() -> None:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    runtime = composition.build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    assert isinstance(runtime.read_model, PostgresOperatorReadModel)
    source = next(item for item in runtime.data_sources if item.key == "operational-state")
    assert source.configured is True
    assert source.authoritative is True
    assert "/browser-evidence" in source.routes
    assert runtime.lifecycle is None


def test_unserved_measurement_routes_declare_an_explicit_unavailable_source() -> None:
    """Routes this distribution never serves must be declared, not left undeclared.

    An undeclared route makes the console skip its source check and issue a blind
    request that can only 404, so the panel loses the server-sourced reason.
    """
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    runtime = composition.build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    declared = {route for source in runtime.data_sources for route in source.routes}
    assert "/finops" in declared

    source = next(item for item in runtime.data_sources if item.key == "overview-measurement")
    assert source.availability == "unavailable"
    assert source.configured is False
    assert source.authoritative is False
    assert source.reachable is not True
    assert source.reason


def test_autonomy_measurement_declares_an_authoritative_audit_source() -> None:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    runtime = composition.build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    source = next(item for item in runtime.data_sources if item.key == "autonomy-measurement")
    assert source.routes == ("/kpi/autonomy",)
    assert source.source == "service-local-audit"
    assert source.availability == "unknown"
    assert source.configured is True
    assert source.authoritative is True
    assert source.durable is True
    assert source.reason is None


def test_durable_console_evidence_routes_declare_authoritative_sources() -> None:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    runtime = composition.build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    expected = {
        "configuration-baseline": "/configuration-baselines",
        "conversation-delivery": "/conversation-delivery",
        "detection-readiness": "/detection-readiness",
        "runtime-skill": "/skills",
        "forecast-learning": "/forecast-learning",
        "operator-memory": "/operator-memory",
    }
    for key, route in expected.items():
        source = next(item for item in runtime.data_sources if item.key == key)
        assert source.routes == (route,)
        assert source.availability == "unknown"
        assert source.configured is True
        assert source.authoritative is True
        assert source.durable is True
        assert source.reason is None


def test_repository_catalog_routes_declare_authoritative_durable_sources() -> None:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)
    runtime = composition.build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
        }
    )

    expected = {
        "onboarding-probe": "/onboarding",
        "capability-contract": "/capabilities",
        "promotion-gate-evidence": "/kpi/promotion-gates",
        "workflow-app-catalog": "/views/workflow-apps",
    }
    for key, route in expected.items():
        source = next(item for item in runtime.data_sources if item.key == key)
        assert source.routes == (route,)
        assert source.source == "repository-catalog-projection"
        assert source.availability == "unknown"
        assert source.configured is True
        assert source.authoritative is True
        assert source.durable is True
        assert source.reason is None


def test_local_narrator_binds_periodic_scheduler_lifecycle(tmp_path: Path) -> None:
    model_path = tmp_path / "models.json"
    model_path.write_text(
        '{"narrator":{"endpoint":"https://example.openai.azure.com",'
        '"deployment":"narrator","api_version":"2024-08-01-preview"}}',
        encoding="utf-8",
    )
    runtime = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify
    ).build_runtime(
        {
            **BASE_ENV,
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
            LOCAL_AZURE_NARRATOR_ENV: "1",
            NARRATOR_PROBE_INTERVAL_ENV: "30",
            "RUNTIME_ENV": "dev",
            "LLM_RESOLVED_MODELS_PATH": str(model_path),
        }
    )

    assert isinstance(runtime.lifecycle, PeriodicNarratorRefreshScheduler)
    assert runtime.lifecycle.interval_seconds == 30


@pytest.mark.parametrize(
    "overrides",
    [
        {DATABASE_URL_ENV: "postgresql://example.invalid/fdai"},
        {
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "postgres",
        },
        {DATABASE_ROLE_ENV: "fdai_operator"},
    ],
)
def test_database_url_and_exact_operator_role_must_be_configured_together(
    overrides: Mapping[str, str],
) -> None:
    composition = ProductionOperatorComposition(verifier_factory=lambda environment: _verify)

    with pytest.raises(OperatorServiceConfigurationError, match=DATABASE_ROLE_ENV):
        composition.build_runtime({**BASE_ENV, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093"},
        {SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests"},
        {SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections"},
        {SEMANTIC_PHYSICAL_TOPIC_ENV: "fdai.pantheon.objects"},
    ],
)
def test_semantic_kafka_environment_is_all_or_none(overrides: Mapping[str, str]) -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="configured together"):
        OperatorEnvironment.parse({**BASE_ENV, **overrides})


def test_semantic_kafka_environment_disables_local_narrator() -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="MUST be disabled"):
        OperatorEnvironment.parse(
            {
                **BASE_ENV,
                "RUNTIME_ENV": "dev",
                LOCAL_AZURE_NARRATOR_ENV: "1",
                KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093",
                SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
                SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
            }
        )


def test_semantic_kafka_environment_preserves_optional_transport_ids() -> None:
    environment = OperatorEnvironment.parse(
        {
            **BASE_ENV,
            KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093",
            SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
            SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
            SEMANTIC_PHYSICAL_TOPIC_ENV: "fdai.pantheon.objects",
            SEMANTIC_CONSUMER_GROUP_ENV: "operator-group",
            SEMANTIC_KAFKA_CLIENT_ID_ENV: "operator-client",
            SEMANTIC_OUTBOX_NAMESPACE_ENV: "issue63.run-1",
            READ_INVESTIGATION_REQUEST_TOPIC_ENV: "operator.read-investigation.requests",
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
            MANAGED_IDENTITY_CLIENT_ID_ENV: "command-identity",
        }
    )

    assert environment.semantic_consumer_group_id == "operator-group"
    assert environment.semantic_kafka_client_id == "operator-client"
    assert environment.semantic_physical_topic == "fdai.pantheon.objects"
    assert environment.semantic_outbox_namespace == "issue63.run-1"
    assert environment.read_investigation_request_topic == ("operator.read-investigation.requests")
    assert environment.managed_identity_client_id == "command-identity"
    assert environment.hil_decision_topic == "fdai.hil.decisions"


def test_hil_callback_requires_durable_kafka_transport() -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="PostgreSQL and configured Kafka"):
        OperatorEnvironment.parse(
            {
                **BASE_ENV,
                "FDAI_CHATOPS_WEBHOOK_SECRET": "synthetic-test-secret",
            }
        )


def test_hil_callback_composes_configured_durable_outbox_publisher() -> None:
    runtime = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
    ).build_runtime(
        {
            **BASE_ENV,
            "FDAI_EXECUTION_VENUE": "local",
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
            KAFKA_BOOTSTRAP_SERVERS_ENV: "localhost:9092",
            SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
            SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
            HIL_DECISION_TOPIC_ENV: "configured.hil.decisions",
            "FDAI_CHATOPS_WEBHOOK_SECRET": "synthetic-test-secret",
            "FDAI_TEAMS_APPLICATION_ID": "approval-bot",
            "FDAI_TEAMS_APPROVAL_TEAM_ID": "approval-team",
            "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "approval-channel",
            "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"teams-owner":"owner-1"}',
        }
    )

    outbox = runtime.route_families.iam.hil_outbox
    assert isinstance(outbox, DurableHilDecisionOutboxPublisher)
    assert outbox.topic == "configured.hil.decisions"
    # The durable ledger closes the record only after broker acceptance, so the
    # lease-fenced worker never republishes an already-delivered decision.
    assert outbox.ledger is not None
    # Teams A1 stays unbound until its Bot service surface is configured.
    assert runtime.route_families.iam.hil_teams_normalizer is None


def _teams_a1_environment() -> dict[str, str]:
    return {
        **BASE_ENV,
        "FDAI_EXECUTION_VENUE": "local",
        DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
        DATABASE_ROLE_ENV: "fdai_operator",
        KAFKA_BOOTSTRAP_SERVERS_ENV: "localhost:9092",
        SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
        SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
        "FDAI_CHATOPS_WEBHOOK_SECRET": "synthetic-test-secret",
        "FDAI_TEAMS_APPLICATION_ID": "approval-bot",
        "FDAI_TEAMS_APPROVAL_TEAM_ID": "approval-team",
        "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "approval-channel",
        "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"teams-owner":"owner-1"}',
        "FDAI_TEAMS_TENANT_ID": "tenant-1",
        "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": '["https://smba.example.invalid/amer"]',
        "FDAI_TEAMS_JWKS_URL": "https://login.example.invalid/keys",
    }


def test_teams_a1_receiver_is_composed_with_its_complete_bot_surface() -> None:
    runtime = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
    ).build_runtime(_teams_a1_environment())

    normalizer = runtime.route_families.iam.hil_teams_normalizer
    assert isinstance(normalizer, TeamsHilCallbackNormalizer)
    assert "/hil/teams-activity" in {
        route.path for route in make_iam_family_routes(runtime.route_families.iam)
    }


def test_teams_a1_receiver_fails_closed_without_its_bot_key_source() -> None:
    values = _teams_a1_environment()
    values.pop("FDAI_TEAMS_JWKS_URL")

    runtime = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=EmptyReadModel(),
    ).build_runtime(values)

    assert runtime.route_families.iam.hil_teams_normalizer is None


def test_read_investigation_topic_requires_kafka_and_distinct_identity() -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="requires"):
        OperatorEnvironment.parse(
            {
                **BASE_ENV,
                READ_INVESTIGATION_REQUEST_TOPIC_ENV: "operator.read-investigation.requests",
            }
        )
    with pytest.raises(OperatorServiceConfigurationError, match="MUST be distinct"):
        OperatorEnvironment.parse(
            {
                **BASE_ENV,
                KAFKA_BOOTSTRAP_SERVERS_ENV: "example.servicebus.windows.net:9093",
                SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
                SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
                READ_INVESTIGATION_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
            }
        )


@pytest.mark.parametrize("namespace", ["Issue63", "issue 63", "-issue63", "x" * 65])
def test_semantic_outbox_namespace_rejects_invalid_identifiers(namespace: str) -> None:
    with pytest.raises(OperatorServiceConfigurationError, match="bounded lowercase"):
        OperatorEnvironment.parse(
            {
                **BASE_ENV,
                DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
                DATABASE_ROLE_ENV: "fdai_operator",
                SEMANTIC_OUTBOX_NAMESPACE_ENV: namespace,
            }
        )


def test_live_stage_consumer_group_preserves_default_and_override() -> None:
    default_environment = OperatorEnvironment.parse(BASE_ENV)
    overridden_environment = OperatorEnvironment.parse(
        {**BASE_ENV, LIVE_STAGE_CONSUMER_GROUP_ENV: "operator-live-replica"}
    )

    assert default_environment.live_stage_consumer_group_id == DEFAULT_LIVE_STAGE_CONSUMER_GROUP
    assert overridden_environment.live_stage_consumer_group_id == "operator-live-replica"


def test_composition_forwards_live_stage_consumer_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_group_ids: list[str] = []

    def capture_live_stage_relay(
        *,
        config: Any,
        hub: Any,
        agent_hub: Any,
        credential: Any,
    ) -> object:
        del hub, agent_hub, credential
        captured_group_ids.append(config.group_id)
        return object()

    monkeypatch.setattr(operator_composition, "LiveStageKafkaRelay", capture_live_stage_relay)
    ProductionOperatorComposition(verifier_factory=lambda environment: _verify).build_runtime(
        {
            **BASE_ENV,
            "FDAI_EXECUTION_VENUE": "local",
            DATABASE_URL_ENV: "postgresql://example.invalid/fdai",
            DATABASE_ROLE_ENV: "fdai_operator",
            KAFKA_BOOTSTRAP_SERVERS_ENV: "localhost:9092",
            SEMANTIC_REQUEST_TOPIC_ENV: "operator.semantic-turn.requests",
            SEMANTIC_PROJECTION_TOPIC_ENV: "core.semantic-turn.projections",
            LIVE_STAGE_CONSUMER_GROUP_ENV: "operator-live-replica",
        }
    )

    assert captured_group_ids == ["operator-live-replica"]


def test_incident_and_rca_queries_preserve_stable_error_envelopes() -> None:
    client = _client(read_model=EmptyReadModel())
    headers = {"Authorization": "Bearer reader"}

    bad_status = client.get("/incidents?status=closed", headers=headers)
    bad_vertical = client.get("/incidents?vertical=other", headers=headers)
    missing_rca = client.get("/rca", headers=headers)
    unknown_rca = client.get("/rca?correlation=corr-unknown", headers=headers)
    bad_replay = client.get("/incidents/stream", headers={**headers, "Last-Event-ID": "bad"})

    assert bad_status.status_code == 400
    assert bad_vertical.status_code == 400
    assert missing_rca.status_code == 400
    assert (unknown_rca.status_code, unknown_rca.json()) == (
        404,
        {
            "error": {
                "status": 404,
                "message": "no audit evidence for correlation 'corr-unknown'",
            }
        },
    )
    assert bad_replay.status_code == 400


def test_incident_stream_closes_when_projection_becomes_unavailable() -> None:
    class FailingReplayReadModel(EmptyReadModel):
        calls = 0

        async def incident_attention(
            self, query: IncidentAttentionQuery
        ) -> IncidentAttentionProjection | None:
            self.calls += 1
            if self.calls > 1:
                raise ProjectionUnavailableError("projection query timed out")
            return await super().incident_attention(query)

    read_model = FailingReplayReadModel()
    client = _client(read_model=read_model)

    response = client.get(
        "/incidents/stream",
        headers={"Authorization": "Bearer reader"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: incident-attention" in response.text
    assert read_model.calls == 2


def test_incident_query_normalizes_and_bounds_server_search() -> None:
    class CapturingReadModel(EmptyReadModel):
        query: IncidentQuery | None = None

        async def list_incidents(self, query: IncidentQuery) -> IncidentPageProjection:
            self.query = query
            return IncidentPageProjection(items=(), next_cursor=None, metrics={})

    read_model = CapturingReadModel()
    client = _client(read_model=read_model)
    headers = {"Authorization": "Bearer reader"}

    response = client.get("/incidents", params={"q": "  Compute   VM  "}, headers=headers)
    oversized = client.get("/incidents", params={"q": "x" * 201}, headers=headers)

    assert response.status_code == 200
    assert read_model.query is not None
    assert read_model.query.search == "compute vm"
    assert oversized.status_code == 400


def test_route_parity_manifest_owns_the_frozen_minimal_surface() -> None:
    assert {route.path for route in ROUTE_PARITY} == {route[1] for route in EXPECTED_ROUTES}
    assert PARITY_COMPLETE
    assert BLOCKED_ROUTE_PATHS == set()
    assert all(route.status == "service-owned" for route in ROUTE_PARITY)


def test_server_lifecycle_uses_validated_listener_without_starting_uvicorn() -> None:
    calls: list[tuple[str, bool, str, int]] = []

    def runner(
        factory_reference: str,
        *,
        factory: bool,
        host: str,
        port: int,
    ) -> object:
        calls.append((factory_reference, factory, host, port))
        return None

    assert (
        serve(
            "example.operator:create_app",
            {**BASE_ENV, HOST_ENV: "127.0.0.1", PORT_ENV: "9123"},
            runner=runner,
        )
        == 0
    )
    assert calls == [("example.operator:create_app", True, "127.0.0.1", 9123)]
