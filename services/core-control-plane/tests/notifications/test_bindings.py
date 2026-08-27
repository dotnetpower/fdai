"""Named notification binding parsing and runtime composition."""

from __future__ import annotations

import json

import httpx
import pytest
from fdai.delivery.notifications import (
    NotificationBindingKind,
    TeamsWorkflowAuthMode,
    parse_notification_bindings,
)
from fdai.runtime.delivery import _build_notification_registry
from fdai.shared.providers.notifications import TrustTier


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
            }
        )
    )

    assert specs[0].kind is NotificationBindingKind.TEAMS_WORKFLOW
    assert specs[0].auth_mode is TeamsWorkflowAuthMode.WORKLOAD_IDENTITY
    assert specs[0].endpoint_env == "FDAI_TEAMS_OPS_ENDPOINT"
    assert specs[1].enabled is False


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
    }
    monkeypatch.setenv("FDAI_NOTIFICATION_BINDINGS_JSON", json.dumps(bindings))
    monkeypatch.setenv("FDAI_TEAMS_OPS_ENDPOINT", "https://flow.example.com/trigger")
    monkeypatch.setenv("FDAI_EMAIL_OPS_ENDPOINT", "https://acs.example.com")
    monkeypatch.setenv("FDAI_EMAIL_OPS_SENDER", "no-reply@example.com")
    monkeypatch.setenv("FDAI_EMAIL_OPS_RECIPIENTS", '["oncall@example.com"]')
    monkeypatch.setenv("FDAI_NOTIFICATION_MI_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost/metadata/identity/oauth2/token")
    monkeypatch.setenv("IDENTITY_HEADER", "identity-header")

    registry = _build_notification_registry(httpx.AsyncClient())

    assert set(registry.channels) == {"teams-ops", "email-oncall"}
    assert all(binding.enabled and binding.configured for binding in registry.bindings.values())
    assert registry.bindings["teams-ops"].trust_tiers == frozenset({TrustTier.A2_OPERATIONAL_ALERT})
