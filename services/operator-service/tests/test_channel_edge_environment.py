"""Fail-fast configuration tests for the standalone Operator channel edge."""

from __future__ import annotations

import json

import pytest
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.environment import (
    ChannelEdgeConfigurationError,
    ChannelEdgeEnvironment,
)
from fdai_service_contracts.venue import ExecutionVenue


def _environment(*, channels: str = "slack") -> dict[str, str]:
    return {
        "FDAI_EXECUTION_VENUE": "local",
        "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS": channels,
        "FDAI_DATABASE_URL": "postgresql://operator@example.invalid/fdai",
        "FDAI_DATABASE_ROLE": "fdai_operator",
        "FDAI_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:19092",
        "FDAI_SEMANTIC_TURN_REQUEST_TOPIC": "operator.semantic-turn.requests",
        "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC": "core.semantic-turn.projections",
        "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON": json.dumps(
            {
                "principal-example": {
                    "scope_ref": "scope://operator/example",
                    "roles": ["Reader"],
                    "locale": "en",
                }
            }
        ),
        "FDAI_SLACK_SIGNING_SECRET": "test-signing-secret",
        "FDAI_SLACK_BOT_TOKEN": "test-bot-token",
        "FDAI_SLACK_TEAM_ID": "team-example",
        "FDAI_SLACK_PRINCIPAL_MAP_JSON": '{"sender-example":"principal-example"}',
        "FDAI_TEAMS_APPLICATION_ID": "application-example",
        "FDAI_TEAMS_TENANT_ID": "tenant-example",
        "FDAI_TEAMS_PRINCIPAL_MAP_JSON": '{"aad-example":"principal-example"}',
        "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON": '["https://service.example.com"]',
        "FDAI_TEAMS_JWKS_URL": "https://keys.example.com/jwks",
        "FDAI_TEAMS_CLIENT_SECRET": "test-client-secret",
    }


def _enable_attachments(values: dict[str, str]) -> None:
    values.update(
        {
            "FDAI_CHANNEL_ATTACHMENTS_ENABLED": "1",
            "FDAI_CHANNEL_ATTACHMENT_INTAKE_ORIGIN": "http://127.0.0.1:8015",
            "FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE": "api://document-ingestion",
            "FDAI_CHANNEL_ATTACHMENT_CLIENT_ID": "channel-edge-attachment-client",
            "FDAI_CHANNEL_ATTACHMENT_TENANT_ID": "tenant-example",
            "FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET": "test-attachment-client-secret",
            "FDAI_CHANNEL_ATTACHMENT_SCRATCH_DIR": "/tmp/fdai-channel-attachments",  # noqa: S108
            "FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED": "1",
            "FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES": "1048576",
            "FDAI_SLACK_FILES_INFO_URL": "https://slack.com/api/files.info",
            "FDAI_SLACK_ATTACHMENT_METADATA_HOSTS_JSON": '["slack.com"]',
            "FDAI_SLACK_ATTACHMENT_DOWNLOAD_HOSTS_JSON": '["files.slack.com"]',
            "FDAI_TEAMS_ATTACHMENT_URL_TEMPLATE": (
                "https://service.example.com/v3/attachments/{attachment_id}/views/original"
            ),
            "FDAI_TEAMS_ATTACHMENT_AUDIENCE": "https://api.botframework.com/.default",
            "FDAI_TEAMS_ATTACHMENT_HOSTS_JSON": '["service.example.com"]',
            "FDAI_TEAMS_ATTACHMENT_AUDIENCES_JSON": ('["https://api.botframework.com/.default"]'),
        }
    )


def test_slack_environment_resolves_closed_principal_scope_without_secret_repr() -> None:
    environment = ChannelEdgeEnvironment.parse(_environment())

    assert environment.enabled_channels == {ChannelKind.SLACK}
    assert environment.execution_venue is ExecutionVenue.LOCAL
    assert environment.attachments_enabled is False
    assert environment.slack is not None and environment.teams is None
    assert environment.slack.principal_by_sender_id == {"sender-example": "principal-example"}
    rendered = repr(environment)
    assert "test-signing-secret" not in rendered
    assert "test-bot-token" not in rendered
    assert "postgresql://" not in rendered


def test_teams_local_environment_requires_secret_and_closed_urls() -> None:
    values = _environment(channels="teams")
    values.pop("FDAI_TEAMS_CLIENT_SECRET")
    with pytest.raises(ChannelEdgeConfigurationError, match="CLIENT_SECRET"):
        ChannelEdgeEnvironment.parse(values)

    values["FDAI_TEAMS_CLIENT_SECRET"] = "test-client-secret"
    values["FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON"] = '["https://user@evil.invalid"]'
    with pytest.raises(ChannelEdgeConfigurationError, match="HTTPS URLs"):
        ChannelEdgeEnvironment.parse(values)

    values["FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON"] = '["https://SERVICE.example.com/"]'
    with pytest.raises(ChannelEdgeConfigurationError, match="normalized service URLs"):
        ChannelEdgeEnvironment.parse(values)


def test_deployed_teams_uses_managed_identity_and_rejects_client_secret() -> None:
    values = _environment(channels="teams")
    values["FDAI_EXECUTION_VENUE"] = "deployed"
    with pytest.raises(ChannelEdgeConfigurationError, match="MUST be unset"):
        ChannelEdgeEnvironment.parse(values)

    values.pop("FDAI_TEAMS_CLIENT_SECRET")
    values["FDAI_CHANNEL_EDGE_MI_CLIENT_ID"] = "managed-identity-example"
    with pytest.raises(ChannelEdgeConfigurationError, match="MUST equal"):
        ChannelEdgeEnvironment.parse(values)
    values["FDAI_TEAMS_APPLICATION_ID"] = "managed-identity-example"
    environment = ChannelEdgeEnvironment.parse(values)
    assert environment.execution_venue is ExecutionVenue.DEPLOYED
    assert environment.teams is not None
    assert environment.teams.managed_identity_client_id == "managed-identity-example"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("FDAI_DATABASE_ROLE", "fdai_core", "fdai_operator"),
        ("FDAI_CHANNEL_EDGE_ENABLED_CHANNELS", "web", "Slack or Teams"),
        (
            "FDAI_SLACK_PRINCIPAL_MAP_JSON",
            '{"sender-example":"unknown-principal"}',
            "configured principal",
        ),
        (
            "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON",
            '{"principal-example":{"scope_ref":"scope://example","roles":["Executor"]}}',
            "unsupported role",
        ),
    ],
)
def test_environment_rejects_wrong_owner_or_open_identity_mapping(
    key: str,
    value: str,
    message: str,
) -> None:
    values = _environment()
    values[key] = value
    with pytest.raises(ChannelEdgeConfigurationError, match=message):
        ChannelEdgeEnvironment.parse(values)


def test_environment_rejects_duplicate_json_keys_and_topics() -> None:
    values = _environment()
    values["FDAI_SLACK_PRINCIPAL_MAP_JSON"] = (
        '{"sender-example":"principal-example","sender-example":"principal-example"}'
    )
    with pytest.raises(ChannelEdgeConfigurationError, match="JSON configuration"):
        ChannelEdgeEnvironment.parse(values)

    values = _environment()
    values["FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"] = values["FDAI_SEMANTIC_TURN_REQUEST_TOPIC"]
    with pytest.raises(ChannelEdgeConfigurationError, match="topics MUST differ"):
        ChannelEdgeEnvironment.parse(values)


def test_attachment_enablement_is_a_strict_startup_flag() -> None:
    values = _environment()
    _enable_attachments(values)
    environment = ChannelEdgeEnvironment.parse(values)
    assert environment.attachments_enabled is True
    assert environment.attachments is not None
    assert environment.attachments.principal_manifest_digest.startswith("sha256:")

    for invalid in ("true", "yes", "2", "-1"):
        values["FDAI_CHANNEL_ATTACHMENTS_ENABLED"] = invalid
        with pytest.raises(ChannelEdgeConfigurationError, match="MUST be 0 or 1"):
            ChannelEdgeEnvironment.parse(values)


def test_attachment_enablement_requires_encrypted_scratch_and_fixed_hosts() -> None:
    values = _environment()
    _enable_attachments(values)
    values.pop("FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED")
    with pytest.raises(ChannelEdgeConfigurationError, match="SCRATCH_ENCRYPTED"):
        ChannelEdgeEnvironment.parse(values)

    _enable_attachments(values)
    values["FDAI_SLACK_FILES_INFO_URL"] = "https://attacker.invalid/api/files.info"
    with pytest.raises(ChannelEdgeConfigurationError, match="fixed HTTPS hosts"):
        ChannelEdgeEnvironment.parse(values)


def test_deployed_attachment_origin_refuses_loopback_http() -> None:
    values = _environment()
    _enable_attachments(values)
    values["FDAI_EXECUTION_VENUE"] = "deployed"
    with pytest.raises(ChannelEdgeConfigurationError, match="fixed HTTPS origin"):
        ChannelEdgeEnvironment.parse(values)
