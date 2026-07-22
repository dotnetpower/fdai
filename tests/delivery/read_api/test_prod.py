"""Unit tests for :mod:`fdai.delivery.read_api.prod`.

Env-only composition root - exercised without a live DB (Entra JWKS is
constructed lazily, and ``build_prod_app`` only *creates* config
objects up to the DB round-trip).
"""

from __future__ import annotations

import json
from typing import Final

import pytest
from starlette.applications import Starlette

from fdai.delivery.persistence import PostgresReadInvestigationRunStore
from fdai.delivery.read_api.prod import (
    ProdReadApiConfigError,
    _parse_cors_origins,
    _parse_positive_int,
    _plain_dsn,
    build_prod_app,
    build_prod_read_model,
)

_GOOD_ENV: Final[dict[str, str]] = {
    "FDAI_DATABASE_URL": "postgresql+psycopg://fdai:devonly@localhost:5432/fdai",
    "FDAI_ENTRA_TENANT_ID": "00000000-0000-0000-0000-000000000001",
    "FDAI_API_AUDIENCE": "api://00000000-0000-0000-0000-000000000002",
    "FDAI_RBAC_READERS_GROUP_ID": "00000000-0000-0000-0000-000000000010",
    "FDAI_RBAC_CONTRIBUTORS_GROUP_ID": "00000000-0000-0000-0000-000000000011",
    "FDAI_RBAC_APPROVERS_GROUP_ID": "00000000-0000-0000-0000-000000000012",
    "FDAI_RBAC_OWNERS_GROUP_ID": "00000000-0000-0000-0000-000000000013",
    "FDAI_RBAC_BREAK_GLASS_GROUP_ID": "00000000-0000-0000-0000-000000000014",
    "FDAI_COMMAND_MI_CLIENT_ID": "command-client-id",
}


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_plain_dsn_strips_psycopg_driver_suffix() -> None:
    assert _plain_dsn("postgresql+psycopg://u:p@h/db") == "postgresql://u:p@h/db"


def test_plain_dsn_pass_through_plain_url() -> None:
    assert _plain_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_plain_dsn_accepts_postgres_scheme_alias() -> None:
    # Heroku-style `postgres://` (no `-ql`) is a psycopg-accepted alias.
    assert _plain_dsn("postgres://u:p@h/db") == "postgres://u:p@h/db"


def test_plain_dsn_rejects_asyncpg_driver_suffix() -> None:
    with pytest.raises(ProdReadApiConfigError, match=r"\+asyncpg"):
        _plain_dsn("postgresql+asyncpg://u:p@h/db")


def test_plain_dsn_rejects_psycopg2_driver_suffix() -> None:
    with pytest.raises(ProdReadApiConfigError, match=r"\+psycopg2"):
        _plain_dsn("postgresql+psycopg2://u:p@h/db")


def test_plain_dsn_rejects_non_postgres_scheme() -> None:
    with pytest.raises(ProdReadApiConfigError, match="different scheme"):
        _plain_dsn("mysql://u:p@h/db")


def test_parse_cors_origins_empty_returns_empty_tuple() -> None:
    assert _parse_cors_origins(None) == ()
    assert _parse_cors_origins("") == ()
    assert _parse_cors_origins(" , , ") == ()


def test_parse_cors_origins_splits_and_trims() -> None:
    got = _parse_cors_origins("https://a.example, https://b.example ,https://c.example")
    assert got == ("https://a.example", "https://b.example", "https://c.example")


def test_parse_cors_origins_rejects_wildcard_element() -> None:
    with pytest.raises(ProdReadApiConfigError, match="'\\*'"):
        _parse_cors_origins("*")


def test_parse_cors_origins_rejects_wildcard_mixed_with_named_origins() -> None:
    with pytest.raises(ProdReadApiConfigError, match="'\\*'"):
        _parse_cors_origins("https://a.example, *")


def test_parse_cors_origins_allows_wildcard_subdomain_not_bare_star() -> None:
    # `*.example.com` is a full origin string, not the bare `*` wildcard;
    # allow it (Starlette handles the pattern separately).
    got = _parse_cors_origins("*.example.com")
    assert got == ("*.example.com",)


def test_parse_positive_int_returns_default_when_unset_or_blank() -> None:
    assert _parse_positive_int({}, "K", 42) == 42
    assert _parse_positive_int({"K": "  "}, "K", 42) == 42


def test_parse_positive_int_parses_value() -> None:
    assert _parse_positive_int({"K": "7"}, "K", 42) == 7


def test_parse_positive_int_rejects_non_int() -> None:
    with pytest.raises(ProdReadApiConfigError, match="K"):
        _parse_positive_int({"K": "seven"}, "K", 42)


def test_parse_positive_int_rejects_non_positive() -> None:
    with pytest.raises(ProdReadApiConfigError, match=">= 1"):
        _parse_positive_int({"K": "0"}, "K", 42)


# ---------------------------------------------------------------------------
# build_prod_read_model - no DB round-trip yet (config validation only)
# ---------------------------------------------------------------------------


def test_build_prod_read_model_requires_database_url() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_DATABASE_URL"]
    with pytest.raises(ProdReadApiConfigError, match="FDAI_DATABASE_URL"):
        build_prod_read_model(env)


def test_build_prod_read_model_returns_configured_adapter() -> None:
    reader = build_prod_read_model(_GOOD_ENV)
    # Attribute is private but its presence proves the config path ran.
    assert reader._config.dsn == "postgresql://fdai:devonly@localhost:5432/fdai"
    assert reader._config.statement_timeout_ms == 20_000
    assert reader._config.connect_timeout_s == 10


def test_build_prod_read_model_honors_timeout_overrides() -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_STATEMENT_TIMEOUT_MS"] = "5000"
    env["FDAI_READ_API_CONNECT_TIMEOUT_S"] = "3"
    reader = build_prod_read_model(env)
    assert reader._config.statement_timeout_ms == 5_000
    assert reader._config.connect_timeout_s == 3


# ---------------------------------------------------------------------------
# build_prod_app - full env composition
# ---------------------------------------------------------------------------


def test_build_prod_app_returns_starlette_app() -> None:
    app = build_prod_app(_GOOD_ENV)
    assert isinstance(app, Starlette)
    paths = {route.path for route in app.routes}
    assert "/views/process" in paths
    assert "/views/process/{process_id:str}" in paths
    assert "/workflows/action-types" in paths
    assert "/workflows/validate" in paths
    assert "/workflows/catalog" in paths
    assert "/workflows/run" in paths
    assert "/capabilities" in paths
    assert "/skills" in paths
    assert "/onboarding" in paths
    assert "/stewardship" in paths
    assert "/kpi/llm-cost" in paths
    assert "/chat/busy-input" not in paths
    assert "/chat/busy-input/mode" not in paths
    assert "/chat/busy-input/cancel-current" not in paths
    assert app.state.skill_disclosure.inspect()["installed_count"] == 0


def test_build_prod_app_verifies_postgresql_before_runtime_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_callbacks: tuple[object, ...] = ()

    def capture_build_app(**kwargs: object) -> Starlette:
        nonlocal captured_callbacks
        config = kwargs["config"]
        captured_callbacks = config.startup_callbacks  # type: ignore[attr-defined]
        return Starlette()

    monkeypatch.setattr(
        "fdai.delivery.read_api.production.factory.build_app",
        capture_build_app,
    )

    build_prod_app(_GOOD_ENV)

    assert captured_callbacks
    assert getattr(captured_callbacks[0], "__name__", "") == "verify_connection"


def test_build_prod_app_wires_singleton_read_investigation_run_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_config = None

    def capture_build_app(**kwargs: object) -> Starlette:
        nonlocal captured_config
        captured_config = kwargs["config"]
        return Starlette()

    monkeypatch.setattr(
        "fdai.delivery.read_api.production.factory.build_app",
        capture_build_app,
    )
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    env = dict(_GOOD_ENV)
    env["FDAI_AZURE_READER_SUBSCRIPTION_ID"] = "sub-example"
    env["FDAI_AZURE_READER_CLIENT_ID"] = "reader-client"
    env["FDAI_AZURE_READER_RESOURCE_GROUPS"] = "rg-one"

    build_prod_app(env)

    assert captured_config is not None
    routes_config = captured_config.read_investigations  # type: ignore[attr-defined]
    assert routes_config is not None
    assert isinstance(routes_config.run_store, PostgresReadInvestigationRunStore)


def test_build_prod_app_rejects_unimplemented_identity_provider() -> None:
    env = dict(_GOOD_ENV, FDAI_IAM_DIRECTORY_PROVIDER="aws-identity-center")

    with pytest.raises(ProdReadApiConfigError, match="not implemented"):
        build_prod_app(env)


def test_build_prod_app_wires_managed_identity_narrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    resolved_models = tmp_path / "resolved-models.json"
    resolved_models.write_text(
        json.dumps(
            {
                "narrator": {
                    "endpoint": "https://example.openai.azure.com/",
                    "deployment": "narrator-mini",
                    "api_version": "2024-12-01-preview",
                }
            }
        ),
        encoding="utf-8",
    )
    env = dict(_GOOD_ENV, LLM_RESOLVED_MODELS_PATH=str(resolved_models))
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    app = build_prod_app(env)

    paths = {route.path for route in app.routes}
    assert {"/chat", "/chat/stream", "/chat/health"} <= paths
    assert {
        "/chat/busy-input",
        "/chat/busy-input/mode",
        "/chat/busy-input/cancel-current",
    } <= paths


def test_build_prod_app_rejects_partial_onboarding_probe_config() -> None:
    env = dict(_GOOD_ENV)
    env["AZURE_SUBSCRIPTION_ID"] = "sub-example"
    with pytest.raises(ProdReadApiConfigError, match="onboarding probe configuration"):
        build_prod_app(env)


def test_build_prod_app_enables_live_routes_when_kafka_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_KAFKA_BOOTSTRAP_SERVERS"] = "example.servicebus.windows.net:9093"
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    app = build_prod_app(env)

    paths = {route.path for route in app.routes}
    assert "/live/stream" in paths
    assert "/agents/stream" in paths


def test_build_prod_app_enables_incident_action_when_event_topic_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fdai.delivery.read_api.routes.console_action import ConsoleActionSubmitter

    env = dict(_GOOD_ENV)
    env["FDAI_KAFKA_BOOTSTRAP_SERVERS"] = "example.servicebus.windows.net:9093"
    env["KAFKA_TOPIC_EVENTS"] = "fdai.events"
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    app = build_prod_app(env)

    route = next(route for route in app.routes if route.path == "/chat/action")
    assert route.methods == {"POST"}
    submitter = next(
        cell.cell_contents
        for cell in route.endpoint.__closure__ or ()
        if isinstance(cell.cell_contents, ConsoleActionSubmitter)
    )
    assert "tool.open-incident-ticket" in submitter.action_type_names


def test_build_prod_app_accepts_strict_incident_sla_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_KAFKA_BOOTSTRAP_SERVERS"] = "example.servicebus.windows.net:9093"
    env["KAFKA_TOPIC_EVENTS"] = "fdai.events"
    thresholds = {f"sev{index}": 300 * index for index in range(1, 6)}
    env["FDAI_INCIDENT_SLA_POLICY_JSON"] = json.dumps(
        {
            "acknowledge_seconds": thresholds,
            "resolve_seconds": thresholds,
        }
    )
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    app = build_prod_app(env)

    assert isinstance(app, Starlette)


def test_build_prod_app_rejects_malformed_incident_sla_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_KAFKA_BOOTSTRAP_SERVERS"] = "example.servicebus.windows.net:9093"
    env["KAFKA_TOPIC_EVENTS"] = "fdai.events"
    env["FDAI_INCIDENT_SLA_POLICY_JSON"] = "{}"
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    with pytest.raises(ProdReadApiConfigError, match="FDAI_INCIDENT_SLA_POLICY_JSON"):
        build_prod_app(env)


def test_build_prod_app_opts_into_hil_callback_without_executor_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_CHATOPS_WEBHOOK_SECRET"] = "test-hil-secret"
    env["FDAI_KAFKA_BOOTSTRAP_SERVERS"] = "example.servicebus.windows.net:9093"
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "test-header")

    app = build_prod_app(env)

    paths = {route.path for route in app.routes}
    assert "/hil/{approval_id}/decision" in paths
    # The production read API publishes a decision event; it never receives
    # a HilResumeCoordinator or privileged executor identity.
    route = next(route for route in app.routes if route.path == "/hil/{approval_id}/decision")
    assert route.methods == {"POST"}


def test_build_prod_app_requires_tenant_id() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_ENTRA_TENANT_ID"]
    # EntraJwtVerifier raises its own EntraVerifierConfigError, which is a
    # ValueError subclass - the prod factory does not catch it.
    with pytest.raises(ValueError, match="FDAI_ENTRA_TENANT_ID"):
        build_prod_app(env)


def test_build_prod_app_requires_api_audience() -> None:
    env = dict(_GOOD_ENV)
    del env["FDAI_API_AUDIENCE"]
    with pytest.raises(ValueError, match="FDAI_API_AUDIENCE"):
        build_prod_app(env)


@pytest.mark.parametrize(
    "missing",
    [
        "FDAI_RBAC_READERS_GROUP_ID",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        "FDAI_RBAC_APPROVERS_GROUP_ID",
        "FDAI_RBAC_OWNERS_GROUP_ID",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    ],
)
def test_build_prod_app_requires_every_rbac_slot(missing: str) -> None:
    env = dict(_GOOD_ENV)
    del env[missing]
    with pytest.raises(ProdReadApiConfigError, match=missing):
        build_prod_app(env)


def test_build_prod_app_wildcard_cors_refused_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_CORS_ALLOW_ORIGINS"] = "*"
    # RUNTIME_ENV=prod would have caught this in `build_app` too, but the
    # prod factory now refuses wildcard unconditionally at parse time.
    monkeypatch.setenv("RUNTIME_ENV", "prod")
    with pytest.raises(ProdReadApiConfigError, match="'\\*'"):
        build_prod_app(env)


def test_build_prod_app_wildcard_cors_refused_even_without_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: closes the RUNTIME_ENV-unset footgun.

    ``main.build_app`` only refuses wildcard CORS when
    ``RUNTIME_ENV in ('staging','prod')`` - a deploy that forgets to set
    the variable would slip a wide-open policy through. The prod factory
    MUST catch that at composition time, regardless of RUNTIME_ENV.
    """
    env = dict(_GOOD_ENV)
    env["FDAI_READ_API_CORS_ALLOW_ORIGINS"] = "*"
    monkeypatch.delenv("RUNTIME_ENV", raising=False)
    with pytest.raises(ProdReadApiConfigError, match="'\\*'"):
        build_prod_app(env)


def test_build_prod_app_never_boots_in_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # The prod factory never sets FDAI_READ_API_DEV_MODE; even if the env
    # carries it, build_app refuses because ReadApiConfig.dev_mode is False
    # (we only feed dev_mode=False into build_app).
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    app = build_prod_app(_GOOD_ENV)
    assert isinstance(app, Starlette)


def test_build_prod_app_reports_every_missing_env_in_one_error() -> None:
    """Cold-boot UX: an entirely-unpopulated env yields ONE listing error."""
    with pytest.raises(ProdReadApiConfigError) as excinfo:
        build_prod_app({})
    message = str(excinfo.value)
    # Every required slot MUST be enumerated in a single message.
    for key in (
        "FDAI_DATABASE_URL",
        "FDAI_ENTRA_TENANT_ID",
        "FDAI_API_AUDIENCE",
        "FDAI_RBAC_READERS_GROUP_ID",
        "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
        "FDAI_RBAC_APPROVERS_GROUP_ID",
        "FDAI_RBAC_OWNERS_GROUP_ID",
        "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
    ):
        assert key in message


def test_build_prod_app_rejects_asyncpg_dsn() -> None:
    env = dict(_GOOD_ENV)
    env["FDAI_DATABASE_URL"] = "postgresql+asyncpg://u:p@h/db"
    with pytest.raises(ProdReadApiConfigError, match=r"\+asyncpg"):
        build_prod_app(env)
