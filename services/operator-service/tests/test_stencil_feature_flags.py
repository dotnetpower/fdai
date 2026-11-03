"""Unit and ASGI middleware tests for Operator Service Stencil feature-flag enforcement."""

from __future__ import annotations

import json

import pytest
from fdai_operator_service.stencil_feature_flags import (
    LOCKED_STENCIL_LOOPS,
    LOCKED_STENCIL_PANELS,
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
        Route("/kpi", ok_handler),
        Route("/audit", ok_handler),
        Route("/incidents", ok_handler),
        Route("/live/stream", ok_handler),
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
            "audit,dashboard,incidents,live,detection-readiness,alert-quality,"
            "configuration-baselines,conversation-delivery,pantheon,agent-activity,"
            "rules,trace,settings-general,settings-integrations"
        ),
        "FDAI_STENCIL_ENABLED_LOOPS": (
            "anomaly-analyzer,inventory-reconciliation,notification-dispatch,saga-audit"
        ),
        "FDAI_STENCIL_ENFORCE_INACTIVE_MENUS": "1",
    }
    app = wrap_with_stencil_feature_flags(_dummy_operator_app(), environ)
    client = TestClient(app)

    # Enabled Lite Observe & Alert endpoints succeed and carry Stencil headers.
    for allowed_path in ("/healthz", "/kpi", "/audit", "/incidents", "/live/stream"):
        res = client.get(allowed_path)
        assert res.status_code == 200, allowed_path
        assert res.headers["x-fdai-stencil-enforcement"] == "fail-closed"
        assert res.headers["x-fdai-stencil-id"] == "lite-observe-alert"

    # Deactivated menu endpoints fail closed with 403 before reaching handlers.
    for blocked_path, expected_panel in (
        ("/aks-commerce/overview", "aks-commerce"),
        ("/cost-governance/summary", "cost-governance"),
        ("/code-security/reviews", "code-security"),
        ("/assurance-twin/posture", "assurance-twin"),
        ("/hil-queue", "hil-queue"),
        ("/rca", "rca"),
        ("/reports", "reports"),
        ("/workflows", "workflow-builder"),
        ("/stewardship", "handover"),
    ):
        res = client.get(blocked_path)
        assert res.status_code == 403, blocked_path
        err = res.json()["error"]
        assert err["code"] == "stencil_feature_flag_disabled"
        assert err["stencil_id"] == "lite-observe-alert"
        assert expected_panel in err["blocked_panels"]

    # Inspection endpoint reports active Stencil feature flags.
    flag_res = client.get("/system/stencil-feature-flags")
    assert flag_res.status_code == 200
    payload = flag_res.json()
    assert payload["schema_version"] == STENCIL_FEATURE_FLAGS_SCHEMA
    assert payload["active"] is True
    assert payload["stencil_id"] == "lite-observe-alert"
    assert payload["enforcement_mode"] == "fail-closed"
    assert set(LOCKED_STENCIL_PANELS).issubset(payload["enabled_panel_ids"])
    assert set(LOCKED_STENCIL_LOOPS).issubset(payload["enabled_loops"])


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
