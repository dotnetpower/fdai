"""Service-owned production composition tests for the independent Operator role."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from fdai_operator_service.application import create_app
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import (
    AUDIENCE_ENV,
    CORS_ORIGINS_ENV,
    DATABASE_URL_ENV,
    GROUP_ENV,
    HOST_ENV,
    PORT_ENV,
    TENANT_ENV,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.main import SERVICE
from fdai_operator_service.parity import BLOCKED_ROUTE_PATHS, PARITY_COMPLETE, ROUTE_PARITY
from fdai_operator_service.postgres import PostgresOperatorReadModel
from fdai_operator_service.production import serve
from fdai_service_contracts import (
    AuditQuery,
    HilQueueProjection,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentQuery,
    JsonProjection,
    OperatorReadModel,
    OperatorRole,
    PageProjection,
)
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_SOURCE = REPO_ROOT / "services/operator-service/src/fdai_operator_service"
LEGACY_ADAPTER = SERVICE_SOURCE / "legacy_adapter.py"
BASE_ENV = {
    TENANT_ENV: "tenant",
    AUDIENCE_ENV: "audience",
    **{key: f"group-{index}" for index, key in enumerate(GROUP_ENV.values())},
}

EXPECTED_ROUTES = (
    (("GET", "HEAD"), "/audit", "get_audit"),
    (("GET", "HEAD"), "/audit/{correlation_id}/trace", "rule_fire_trace"),
    (("GET", "HEAD"), "/healthz", "healthz"),
    (("GET", "HEAD"), "/hil-queue", "get_hil_queue"),
    (("GET", "HEAD"), "/incidents", "panel:incidents"),
    (("GET", "HEAD"), "/incidents/stream", "incident_attention_stream"),
    (("GET", "HEAD"), "/kpi", "get_kpi"),
    (
        ("GET", "HEAD"),
        "/notification-templates/incident-opened",
        "get_incident_opened_template",
    ),
    (("GET", "HEAD"), "/rca", "panel:rca"),
    (("GET", "HEAD"), "/system/data-sources", "get_data_sources"),
)


class EmptyReadModel(OperatorReadModel):
    """Authoritative empty projection used only by service boundary tests."""

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        del query
        return PageProjection(items=(), next_cursor=None)

    async def dashboard_metrics(self) -> JsonProjection:
        return JsonProjection({"event_count": 0})

    async def list_hil_queue(self, query: HilQueueQuery) -> HilQueueProjection:
        del query
        return HilQueueProjection(items=(), total=0)

    async def list_incidents(self, query: IncidentQuery) -> PageProjection:
        del query
        return PageProjection(items=(), next_cursor=None)

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


def _client(*, read_model: OperatorReadModel | None = None) -> TestClient:
    composition = ProductionOperatorComposition(
        verifier_factory=lambda environment: _verify,
        read_model=read_model,
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
    assert not any(
        dependency == "fdai" or dependency.startswith(("fdai[", "fdai==", "fdai>=", "fdai<"))
        for dependency in dependencies
    )


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

    def verifier_factory(environment: object) -> object:
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
    app = _client(read_model=EmptyReadModel()).app
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


def test_health_is_public_and_stable() -> None:
    response = _client().get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


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
        {**BASE_ENV, DATABASE_URL_ENV: "postgresql://example.invalid/fdai"}
    )

    assert isinstance(runtime.read_model, PostgresOperatorReadModel)
    source = next(item for item in runtime.data_sources if item.key == "operational-state")
    assert source.configured is True
    assert source.authoritative is True


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
