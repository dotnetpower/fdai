"""Unit and ASGI middleware tests for Operator Service Stencil feature-flag enforcement."""

from __future__ import annotations

import json

import pytest
from fdai_operator_service.stencil_feature_flags import (
    ALWAYS_ALLOWED_OPERATOR_PATHS,
    LOCKED_STENCIL_ADDONS,
    LOCKED_STENCIL_LOOPS,
    LOCKED_STENCIL_PANELS,
    LOCKED_STENCIL_SCHEDULED_JOBS,
    LOCKED_STENCIL_WORKLOADS,
    STENCIL_FEATURE_FLAGS_SCHEMA,
    StencilFeatureFlagConfig,
    wrap_with_stencil_feature_flags,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _dummy_operator_app() -> Starlette:
    async def ok_handler(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "path": request.url.path})

    routes = [
        Route("/healthz", ok_handler),
        Route("/iam/self", ok_handler),
        Route("/iam", ok_handler),
        Route("/iam/directory/users", ok_handler),
        Route("/access-grants/stream", ok_handler),
        Route("/models/settings", ok_handler),
        Route("/me/model-preferences", ok_handler),
        Route("/me/memories", ok_handler),
        Route("/me/conversations/search", ok_handler),
        Route("/conversation-assurance", ok_handler),
        Route("/background-tasks", ok_handler),
        Route("/task-workers", ok_handler),
        Route("/python-tasks/capabilities", ok_handler),
        Route("/kpi/promotion-gates", ok_handler),
        Route("/policy/revisions", ok_handler),
        Route("/configuration-baselines/review/run", ok_handler),
        Route("/runtime/integrations/teams-workflow/test", ok_handler),
        Route("/runtime/settings", ok_handler),
        Route("/audit/{correlation_id}/trace", ok_handler),
        Route("/kpi", ok_handler),
        Route("/audit", ok_handler),
        Route("/incidents", ok_handler),
        Route("/live/stream", ok_handler),
        Route("/agents", ok_handler),
        Route("/ontology/instances/states", ok_handler),
        Route("/aks-commerce/overview", ok_handler),
        Route("/cost-governance/summary", ok_handler),
        Route("/code-security/reviews", ok_handler),
        Route("/assurance-twin/posture", ok_handler),
        Route("/hil-queue", ok_handler),
        Route("/rca", ok_handler),
        Route("/reports", ok_handler),
        Route("/workflows", ok_handler),
        Route("/stewardship", ok_handler),
    ]
    return Starlette(routes=routes)


def test_default_unscoped_environment_leaves_all_routes_enabled() -> None:
    config = StencilFeatureFlagConfig.from_environ({})
    assert config.active is False
    assert config.enforcement_mode == "unscoped"
    assert config.evaluate_path("/aks-commerce/overview").allowed is True
    assert config.evaluate_path("/cost-governance/summary").allowed is True

    app = wrap_with_stencil_feature_flags(_dummy_operator_app(), {})
    assert isinstance(app, Starlette)
    assert hasattr(app, "router")
    client = TestClient(app)

    res = client.get("/aks-commerce/overview")
    assert res.status_code == 200
    assert "x-fdai-stencil-enforcement" not in res.headers

    status_res = client.get("/system/stencil-feature-flags")
    assert status_res.status_code == 200
    assert status_res.json()["active"] is False


def test_lite_observe_alert_stencil_blocks_deactivated_menu_endpoints_fail_closed() -> None:
    environ = {
        "FDAI_STENCIL_ID": "lite-observe-alert",
        "FDAI_STENCIL_ENABLED_PANELS": (
            "audit,dashboard,agents,incidents,live,detection-readiness,alert-quality,"
            "configuration-baselines,conversation-delivery,pantheon,agent-activity,"
            "rules,trace,settings-general,settings-integrations,settings-models"
        ),
        "FDAI_STENCIL_ENABLED_LOOPS": (
            "anomaly-analyzer,inventory-reconciliation,notification-dispatch,saga-audit"
        ),
        "FDAI_STENCIL_ENFORCE_INACTIVE_MENUS": "1",
    }
    app = wrap_with_stencil_feature_flags(_dummy_operator_app(), environ)
    client = TestClient(app)

    # Enabled Lite Observe & Alert endpoints succeed and carry Stencil headers.
    for allowed_path in (
        "/healthz",
        "/iam/self",
        "/agents",
        "/access-grants/stream",
        "/ontology/instances/states",
        "/kpi",
        "/audit",
        "/audit/corr-123/trace",
        "/incidents",
        "/live/stream",
        "/configuration-baselines/review/run",
        "/runtime/integrations/teams-workflow/test",
        "/runtime/settings",
        "/models/settings",
        "/me/model-preferences",
    ):
        res = client.get(allowed_path)
        assert res.status_code == 200, allowed_path
        assert res.headers["x-fdai-stencil-enforcement"] == "fail-closed"
        assert res.headers["x-fdai-stencil-id"] == "lite-observe-alert"

    # Deactivated menu endpoints fail closed with 403 before reaching handlers (H01-H15, H20).
    for blocked_path, expected_panel in (
        ("/aks-commerce/overview", "aks-commerce"),
        ("/cost-governance/summary", "cost-governance"),
        ("/code-security/reviews", "code-security"),
        ("/assurance-twin/posture", "assurance-twin"),
        ("/hil-queue", "hil-queue"),
        ("/iam", "settings-iam"),
        ("/iam/directory/users", "settings-iam"),
        ("/me/memories", "settings-memory"),
        ("/me/conversations/search", "conversation-search"),
        ("/conversation-assurance", "conversation-assurance"),
        ("/background-tasks", "background-tasks"),
        ("/task-workers", "background-tasks"),
        ("/python-tasks/capabilities", "workflow-builder"),
        ("/kpi/promotion-gates", "promotion-gates"),
        ("/policy/revisions", "settings-runtime"),
        ("/rca", "rca"),
        ("/reports", "reports"),
        ("/workflows", "workflow-builder"),
        ("/stewardship", "handover"),
    ):
        res = client.get(blocked_path)
        assert res.status_code == 403, blocked_path
        assert res.headers["cache-control"] == "no-store"
        assert res.headers["x-content-type-options"] == "nosniff"
        err = res.json()["error"]
        assert err["code"] == "stencil_feature_flag_disabled"
        assert err["stencil_id"] == "lite-observe-alert"
        assert expected_panel in err["blocked_panels"]

    # Inspection endpoint reports active Stencil feature flags with security headers.
    flag_res = client.get("/system/stencil-feature-flags")
    assert flag_res.status_code == 200
    assert flag_res.headers["cache-control"] == "no-store"
    assert flag_res.headers["x-content-type-options"] == "nosniff"
    payload = flag_res.json()
    assert payload["schema_version"] == STENCIL_FEATURE_FLAGS_SCHEMA
    assert payload["active"] is True
    assert payload["stencil_id"] == "lite-observe-alert"
    assert payload["enforcement_mode"] == "fail-closed"
    assert set(LOCKED_STENCIL_PANELS).issubset(payload["enabled_panel_ids"])
    assert set(LOCKED_STENCIL_LOOPS).issubset(payload["enabled_loops"])
    assert set(LOCKED_STENCIL_WORKLOADS) == set(payload["locked_workloads"])
    assert set(LOCKED_STENCIL_SCHEDULED_JOBS) == set(payload["locked_scheduled_jobs"])
    assert set(LOCKED_STENCIL_ADDONS) == set(payload["locked_addons"])


def test_feature_flags_json_manifest_and_locked_safety_core_guards() -> None:
    manifest_json = json.dumps(
        {
            "schema_version": STENCIL_FEATURE_FLAGS_SCHEMA,
            "stencil_id": "custom-lite",
            "enforcement_mode": "fail-closed",
            "panel_flags": {
                "audit": True,
                "dashboard": True,
                "settings-general": True,
                "live": True,
                "cost-governance": False,
                "aks-commerce": False,
            },
            "loop_flags": {
                "anomaly-analyzer": True,
                "inventory-reconciliation": True,
                "notification-dispatch": True,
                "saga-audit": True,
                "cost-governance": False,
            },
        }
    )
    config = StencilFeatureFlagConfig.from_environ(
        {"FDAI_STENCIL_FEATURE_FLAGS_JSON": manifest_json}
    )
    assert config.active is True
    assert config.stencil_id == "custom-lite"
    assert config.is_panel_enabled("live") is True
    assert config.is_panel_enabled("cost-governance") is False
    assert config.is_loop_enabled("cost-governance") is False
    assert config.evaluate_path("/cost-governance/summary").allowed is False

    # Disabling a locked safety-core panel or loop is rejected fail-closed.
    with pytest.raises(ValueError, match="Cannot disable locked safety-core Stencil panel"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_DISABLED_PANELS": "audit"})

    with pytest.raises(ValueError, match="Cannot disable locked safety-core Stencil loop"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_DISABLED_LOOPS": "saga-audit"})

    with pytest.raises(ValueError, match="Invalid FDAI_STENCIL_ENABLED_PANELS identifier"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_ENABLED_PANELS": "Bad_Panel"})


def test_url_normalization_axis_flags_and_strict_json_guards() -> None:
    config = StencilFeatureFlagConfig.from_environ(
        {
            "FDAI_STENCIL_ID": "minimal-core",
            "FDAI_STENCIL_ENABLED_PANELS": "audit,dashboard,settings-general,live",
            "FDAI_STENCIL_ENABLED_WORKLOADS": "core-control-plane,operator-service",
            "FDAI_STENCIL_ENABLED_JOBS": "analyzer,inventory",
            "FDAI_STENCIL_ENABLED_ADDONS": "notifications,read-only-console",
        }
    )
    # H16: Percent-encoded, double-slash, dot-segment, and control-char paths cannot bypass rules.
    assert config.evaluate_path("/%61ks-commerce/overview").allowed is False
    assert config.evaluate_path("//aks-commerce///overview").allowed is False
    assert config.evaluate_path("/audit/../aks-commerce").allowed is False
    assert config.evaluate_path("/live\x00/stream").allowed is False
    # H14: /audit/{id}/trace is blocked when 'trace' is disabled while /audit stays allowed.
    assert config.evaluate_path("/audit").allowed is True
    assert config.evaluate_path("/audit/corr-1/trace").allowed is False
    # H17: Always-allowed operator bootstrap/health paths remain permitted.
    for path in ALWAYS_ALLOWED_OPERATOR_PATHS:
        assert config.evaluate_path(path).allowed is True

    # H18: Workload, job, and addon flags are evaluated and locked safety-core axes are enforced.
    assert config.is_workload_enabled("core-control-plane") is True
    assert config.is_workload_enabled("isolated-executor") is False
    assert config.is_scheduled_job_enabled("analyzer") is True
    assert config.is_scheduled_job_enabled("cost-collector") is False
    assert config.is_addon_enabled("read-only-console") is True
    assert config.is_addon_enabled("governed-execution") is False

    with pytest.raises(ValueError, match="Cannot disable locked safety-core Stencil workload"):
        StencilFeatureFlagConfig.from_environ(
            {"FDAI_STENCIL_DISABLED_WORKLOADS": "operator-service"}
        )
    with pytest.raises(ValueError, match="Cannot disable locked safety-core Stencil scheduled job"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_DISABLED_JOBS": "inventory"})
    with pytest.raises(ValueError, match="Cannot disable locked safety-core Stencil add-on"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_DISABLED_ADDONS": "read-only-console"})

    # H19: Duplicate JSON keys, unknown keys, and invalid boolean tokens fail closed.
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        StencilFeatureFlagConfig.from_environ(
            {"FDAI_STENCIL_FEATURE_FLAGS_JSON": ('{"stencil_id":"a","stencil_id":"b"}')}
        )
    with pytest.raises(ValueError, match="Unsupported Stencil feature-flags JSON field"):
        StencilFeatureFlagConfig.from_environ(
            {"FDAI_STENCIL_FEATURE_FLAGS_JSON": '{"unexpected_field":true}'}
        )
    with pytest.raises(ValueError, match="Invalid FDAI_STENCIL_ENFORCE_INACTIVE_MENUS"):
        StencilFeatureFlagConfig.from_environ({"FDAI_STENCIL_ENFORCE_INACTIVE_MENUS": "maybe"})
