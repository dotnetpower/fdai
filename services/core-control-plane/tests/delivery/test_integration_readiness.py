"""Source-attributed integration readiness rows shared by both venues."""

from __future__ import annotations

import json

from fdai.delivery.integration_readiness import (
    endpoint_is_placeholder,
    integration_projection,
)

_A1_SEND = {
    "FDAI_TEAMS_APPROVAL_ACTIVITY_URL": "https://smba.example.com/activities",
    "FDAI_TEAMS_APPROVAL_TEAM_ID": "team-1",
    "FDAI_TEAMS_APPROVAL_CHANNEL_ID": "channel-1",
}
_A1_CALLBACK = {
    "FDAI_TEAMS_APPLICATION_ID": "00000000-0000-0000-0000-000000000000",
    "FDAI_TEAMS_TENANT_ID": "00000000-0000-0000-0000-000000000001",
    "FDAI_TEAMS_JWKS_URL": "https://login.example.com/keys",
    "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": '["https://smba.example.com/"]',
    "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"29:abc": "00000000-0000-0000-0000-000000000002"}',
    "FDAI_CHATOPS_WEBHOOK_SECRET": "synthetic-secret",
    "FDAI_HIL_DECISION_TOPIC": "fdai.hil.decisions",
    "FDAI_STATE_STORE_DSN": "postgresql://localhost/fdai",
}


def _rows(env: dict[str, str]) -> dict[str, dict[str, object]]:
    return {str(row["key"]): row for row in integration_projection(env)}


def test_teams_categories_are_distinct_rows() -> None:
    rows = _rows({})

    assert [
        "teams-a1-approval-send",
        "teams-a1-approval-callback",
        "teams-a2-operational-alert",
        "teams-a4-digest",
        "teams-a3-conversation",
    ] == [key for key in rows if key.startswith("teams-")]
    assert "chatops" not in rows


def test_a1_send_is_ready_only_with_the_complete_bot_destination() -> None:
    partial = _rows({"FDAI_TEAMS_APPROVAL_ACTIVITY_URL": "https://smba.example.com/activities"})
    assert partial["teams-a1-approval-send"]["configured"] is True
    assert partial["teams-a1-approval-send"]["ready"] is False
    assert partial["teams-a1-approval-send"]["reason"] == "configuration is incomplete"

    complete = _rows(dict(_A1_SEND))
    assert complete["teams-a1-approval-send"]["ready"] is True
    assert complete["teams-a1-approval-send"]["source"] == "core-control-plane"


def test_a1_callback_reports_unobserved_rather_than_unconfigured() -> None:
    unobserved = _rows(dict(_A1_SEND))["teams-a1-approval-callback"]
    assert unobserved["observed"] is False
    assert unobserved["configured"] is False
    assert unobserved["ready"] is False

    complete = _rows(dict(_A1_CALLBACK))["teams-a1-approval-callback"]
    assert complete["observed"] is True
    assert complete["ready"] is True
    assert complete["source"] == "operator-service"

    invalid = _rows({**_A1_CALLBACK, "FDAI_TEAMS_PRINCIPAL_MAP_JSON": "[]"})
    assert invalid["teams-a1-approval-callback"]["ready"] is False
    assert invalid["teams-a1-approval-callback"]["reason"] == "configuration is invalid"


def test_a2_and_a4_track_activation_separately() -> None:
    bindings = {
        "teams-ops": {
            "kind": "teams_workflow",
            "enabled": True,
            "trust_tiers": ["a2_operational_alert"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
        },
        "teams-digest": {
            "kind": "teams_workflow",
            "enabled": False,
            "trust_tiers": ["a4_digest"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_DIGEST_ENDPOINT",
        },
    }
    rows = _rows(
        {
            "FDAI_NOTIFICATION_BINDINGS_JSON": json.dumps(bindings),
            "FDAI_TEAMS_OPS_ENDPOINT": "https://example.environment.api.powerplatform.com/x",
        }
    )

    assert rows["teams-a2-operational-alert"]["ready"] is True
    assert rows["teams-a4-digest"]["configured"] is True
    assert rows["teams-a4-digest"]["ready"] is False
    assert rows["teams-a4-digest"]["reason"] == "a binding exists but is not activated for delivery"


def test_an_activated_binding_with_a_placeholder_endpoint_is_not_ready() -> None:
    bindings = {
        "teams-ops": {
            "kind": "teams_workflow",
            "enabled": True,
            "trust_tiers": ["a2_operational_alert"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
        }
    }
    rows = _rows(
        {
            "FDAI_NOTIFICATION_BINDINGS_JSON": json.dumps(bindings),
            "FDAI_TEAMS_OPS_ENDPOINT": "unconfigured",
        }
    )

    assert rows["teams-a2-operational-alert"]["ready"] is False
    assert rows["teams-a2-operational-alert"]["reason"] == (
        "an activated binding has no saved endpoint value yet"
    )


def test_a3_reports_the_edge_owner_and_disabled_channel_set() -> None:
    disabled = _rows({"FDAI_CHANNEL_EDGE_ENABLED_CHANNELS": "slack"})["teams-a3-conversation"]
    assert disabled["observed"] is True
    assert disabled["ready"] is False
    assert disabled["reason"] == "the channel edge does not enable Teams conversations"

    enabled = _rows(
        {
            "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS": "teams",
            "FDAI_TEAMS_APPLICATION_ID": "00000000-0000-0000-0000-000000000000",
            "FDAI_TEAMS_TENANT_ID": "00000000-0000-0000-0000-000000000001",
            "FDAI_TEAMS_PRINCIPAL_MAP_JSON": "{}",
            "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": "[]",
        }
    )["teams-a3-conversation"]
    assert enabled["ready"] is True
    assert enabled["source"] == "operator-service"


def test_no_row_infers_provider_health_from_configuration() -> None:
    rows = _rows({**_A1_SEND, **_A1_CALLBACK})

    for row in rows.values():
        assert set(row) >= {"key", "source", "observed", "configured", "ready", "mode", "reason"}
        assert "healthy" not in row
        assert "reachable" not in row


def test_placeholder_detection_refuses_non_https_and_sentinels() -> None:
    assert endpoint_is_placeholder("unconfigured") is True
    assert endpoint_is_placeholder("  ") is True
    assert endpoint_is_placeholder("http://example.invalid") is True
    assert endpoint_is_placeholder("https://example.invalid/trigger") is False
