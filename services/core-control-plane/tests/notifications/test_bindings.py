"""Named notification binding parsing and runtime composition."""

from __future__ import annotations

import json

import httpx
import pytest
from fdai.delivery.notifications import (
    NotificationBindingKind,
    TeamsWorkflowAuthMode,
    default_notification_bindings_from_env,
    parse_notification_bindings,
)
from fdai.runtime.delivery import _build_notification_registry
from fdai.shared.providers.notifications import TrustTier


def _clear_default_notification_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FDAI_NOTIFICATION_BINDINGS_JSON",
        "FDAI_TEAMS_OPS_ENDPOINT",
        "FDAI_SLACK_OPS_WEBHOOK_URL",
        "FDAI_EMAIL_ENDPOINT",
        "FDAI_EMAIL_SENDER_ADDRESS",
        "FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON",
        "FDAI_NOTIFICATION_MI_CLIENT_ID",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_binding_parser_preserves_named_enablement_and_secret_references() -> None:
    specs = parse_notification_bindings(
        json.dumps(
            {
                "teams-ops": {
                    "kind": "teams_workflow",
                    "enabled": True,
                    "trust_tiers": ["a2_operational_alert"],
                    "auth_mode": "workload_identity",
                    "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
                },
                "email-oncall": {
                    "kind": "acs_email",
                    "enabled": False,
                    "trust_tiers": ["a2_operational_alert", "a4_digest"],
                },
                "slack-ops": {
                    "kind": "slack_webhook",
                    "enabled": True,
                    "trust_tiers": ["a2_operational_alert"],
                    "endpoint_env": "FDAI_SLACK_OPS_WEBHOOK_URL",
                },
            }
        )
    )

    assert specs[0].kind is NotificationBindingKind.TEAMS_WORKFLOW
    assert specs[0].auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY
    assert specs[0].endpoint_env == "FDAI_TEAMS_OPS_ENDPOINT"
    assert specs[1].enabled is False
    assert specs[2].kind is NotificationBindingKind.SLACK_WEBHOOK


def test_enabled_binding_with_incomplete_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires 'endpoint_env'"):
        parse_notification_bindings(
            json.dumps(
                {
                    "teams-ops": {
                        "kind": "teams_workflow",
                        "enabled": True,
                        "trust_tiers": ["a2_operational_alert"],
                        "auth_mode": "anyone",
                    }
                }
            )
        )


def test_runtime_binds_two_named_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    bindings = {
        "teams-ops": {
            "kind": "teams_workflow",
            "enabled": True,
            "trust_tiers": ["a2_operational_alert"],
            "auth_mode": "anyone",
            "endpoint_env": "FDAI_TEAMS_OPS_ENDPOINT",
        },
        "email-oncall": {
            "kind": "acs_email",
            "enabled": True,
            "trust_tiers": ["a2_operational_alert"],
            "endpoint_env": "FDAI_EMAIL_OPS_ENDPOINT",
            "sender_address_env": "FDAI_EMAIL_OPS_SENDER",
            "recipient_addresses_env": "FDAI_EMAIL_OPS_RECIPIENTS",
        },
        "slack-ops": {
            "kind": "slack_webhook",
            "enabled": True,
            "trust_tiers": ["a2_operational_alert"],
            "endpoint_env": "FDAI_SLACK_OPS_WEBHOOK_URL",
        },
    }
    monkeypatch.setenv("FDAI_NOTIFICATION_BINDINGS_JSON", json.dumps(bindings))
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", "https://flow.example.com/trigger")
    monkeypatch.setenv("FDAI_EMAIL_OPS_ENDPOINT", "https://acs.example.com")
    monkeypatch.setenv("FDAI_EMAIL_OPS_SENDER", "no-reply@example.com")
    monkeypatch.setenv("FDAI_EMAIL_OPS_RECIPIENTS", '["oncall@example.com"]')
    monkeypatch.setenv(
        "FDAI_SLACK_OPS_WEBHOOK_URL",
        "https://hooks.slack.com/services/T000/B000/abcdefghijklmnopqrstuvwxyz",
    )
    monkeypatch.setenv("FDAI_NOTIFICATION_MI_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/metadata/identity/oauth2/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    registry = _build_notification_registry(httpx.AsyncClient())

    assert set(registry.channels) == {"teams-ops", "email-oncall", "slack-ops"}
    assert all(binding.enabled and binding.configured for binding in registry.bindings.values())
    assert registry.bindings["teams-ops"].trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})


def test_url_only_configuration_builds_default_matrix_bindings_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_default_notification_env(monkeypatch)
    teams_url = "https://flow.example.com/trigger/default"
    slack_url = "https://hooks.slack.com/services/T000/B000/default"
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", teams_url)
    monkeypatch.setenv("FDAI_SLACK_OPS_WEBHOOK_URL", slack_url)

    raw = default_notification_bindings_from_env(
        {
            "FDAI_TEAMS_OPS_ENDPOINT": teams_url,
            "FDAI_SLACK_OPS_WEBHOOK_URL": slack_url,
        }
    )
    registry = _build_notification_registry(httpx.AsyncClient())

    assert teams_url not in raw
    assert slack_url not in raw
    assert set(registry.channels) == {
        "teams-ops-prd",
        "teams-hil-prd",
        "slack-ops-prd",
    }
    assert registry.bindings["teams-ops-prd"].trust_tiers == frozenset(
        {TrustTier.A2_OPERATIONAL_ALERT}
    )
    assert registry.bindings["teams-hil-prd"].trust_tiers == frozenset({TrustTier.A4_DIGEST})
    assert registry.bindings["slack-ops-prd"].trust_tiers == frozenset(
        {TrustTier.A2_OPERATIONAL_ALERT}
    )
    assert registry.channels["teams-ops-prd"]._config.auth_mode is TeamsWorkflowAuthMode.ANYONE
    assert registry.channels["teams-hil-prd"]._config.webhook_url == teams_url


def test_explicit_binding_json_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_default_notification_env(monkeypatch)
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", "https://flow.example.com/trigger/default")
    monkeypatch.setenv(
        "FDAI_SLACK_OPS_WEBHOOK_URL",
        "https://hooks.slack.com/services/T000/B000/default",
    )
    monkeypatch.setenv(
        "FDAI_NOTIFICATION_BINDINGS_JSON",
        json.dumps(
            {
                "slack-custom": {
                    "kind": "slack_webhook",
                    "enabled": True,
                    "trust_tiers": ["a4_digest"],
                    "endpoint_env": "FDAI_SLACK_OPS_WEBHOOK_URL",
                }
            }
        ),
    )

    registry = _build_notification_registry(httpx.AsyncClient())

    assert set(registry.channels) == {"slack-custom"}


def test_url_only_configuration_requires_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_default_notification_env(monkeypatch)
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", "https://flow.example.com/trigger/default")

    with pytest.raises(RuntimeError, match="webhook URL is set but no HTTP client"):
        _build_notification_registry(None)


def test_url_only_webhooks_coexist_with_legacy_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_default_notification_env(monkeypatch)
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", "https://flow.example.com/trigger/default")
    monkeypatch.setenv(
        "FDAI_SLACK_OPS_WEBHOOK_URL",
        "https://hooks.slack.com/services/T000/B000/default",
    )
    monkeypatch.setenv("FDAI_EMAIL_ENDPOINT", "https://acs.example.com")
    monkeypatch.setenv("FDAI_EMAIL_SENDER_ADDRESS", "no-reply@example.com")
    monkeypatch.setenv("FDAI_EMAIL_RECIPIENT_ADDRESSES_JSON", '["oncall@example.com"]')
    monkeypatch.setenv("FDAI_NOTIFICATION_MI_CLIENT_ID", "notification-client")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/identity")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    registry = _build_notification_registry(httpx.AsyncClient())

    assert set(registry.channels) == {
        "teams-ops-prd",
        "teams-hil-prd",
        "slack-ops-prd",
        "email-oncall",
        "email-governance",
    }
