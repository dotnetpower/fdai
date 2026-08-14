"""Service-owned production composition tests for the independent Operator role."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

import fdai_operator_service.composition as operator_composition
import pytest
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
    HOST_ENV,
    KAFKA_BOOTSTRAP_SERVERS_ENV,
    LIVE_STAGE_CONSUMER_GROUP_ENV,
    LOCAL_AZURE_NARRATOR_ENV,
    MANAGED_IDENTITY_CLIENT_ID_ENV,
    PORT_ENV,
    SEMANTIC_CONSUMER_GROUP_ENV,
    SEMANTIC_KAFKA_CLIENT_ID_ENV,
    SEMANTIC_PHYSICAL_TOPIC_ENV,
    SEMANTIC_PROJECTION_TOPIC_ENV,
    SEMANTIC_REQUEST_TOPIC_ENV,
    TENANT_ENV,
    OperatorEnvironment,
    OperatorServiceConfigurationError,
)
from fdai_operator_service.main import SERVICE
from fdai_operator_service.parity import BLOCKED_ROUTE_PATHS, PARITY_COMPLETE, ROUTE_PARITY
from fdai_operator_service.postgres import PostgresOperatorReadModel
from fdai_operator_service.production import serve
from fdai_service_contracts import (
    AgentActivityQuery,
    AuditQuery,
    HilQueueProjection,
    HilQueueQuery,
    IncidentAttentionProjection,
    IncidentAttentionQuery,
    IncidentPageProjection,
    IncidentQuery,
    JsonProjection,
    OperatorReadModel,
    OperatorRole,
    PageProjection,
)
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
)


class EmptyReadModel(OperatorReadModel):
    """Authoritative empty projection used only by service boundary tests."""

    async def list_agent_activity(self, query: AgentActivityQuery) -> JsonProjection:
        del query
        return JsonProjection({"items": [], "snapshot_at": "", "source": "durable"})

    async def list_audit(self, query: AuditQuery) -> PageProjection:
        del query
        return PageProjection(items=(), next_cursor=None)

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
        {SEMANTIC_PHYSICAL_TOPIC_ENV: "aw.pantheon.objects"},
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
            SEMANTIC_PHYSICAL_TOPIC_ENV: "aw.pantheon.objects",
            SEMANTIC_CONSUMER_GROUP_ENV: "operator-group",
            SEMANTIC_KAFKA_CLIENT_ID_ENV: "operator-client",
            MANAGED_IDENTITY_CLIENT_ID_ENV: "command-identity",
        }
    )

    assert environment.semantic_consumer_group_id == "operator-group"
    assert environment.semantic_kafka_client_id == "operator-client"
    assert environment.semantic_physical_topic == "aw.pantheon.objects"
    assert environment.managed_identity_client_id == "command-identity"


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

    def capture_live_stage_relay(*, config, hub, agent_hub, credential):
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
