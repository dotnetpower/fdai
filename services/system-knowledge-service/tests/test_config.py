from __future__ import annotations

import base64
import json

import pytest
from fdai_system_knowledge_service.config import (
    CLAIM_CONTAINER_URL_ENV,
    OUTGOING_HMAC_SECRET_ENV,
    SystemKnowledgeConfigurationError,
    SystemKnowledgeSettings,
    TeamsOutgoingWebhookSettings,
    TeamsTransport,
)


def _environment(*, venue: str) -> dict[str, str]:
    values = {
        "FDAI_EXECUTION_VENUE": venue,
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID": "application-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID": "28:application-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID": "tenant-example",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON": json.dumps(["team-example"]),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON": json.dumps(["channel-example"]),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON": json.dumps(
            ["https://smba.trafficmanager.net/example"]
        ),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON": json.dumps(
            {"aad-example": "principal-example"}
        ),
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL": "https://login.example.com/keys",
    }
    if venue == "local":
        values["FDAI_SYSTEM_KNOWLEDGE_TEAMS_CLIENT_SECRET"] = "local-secret"
    else:
        values["FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION"] = "a" * 40
        values["FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID"] = "application-example"
        values[CLAIM_CONTAINER_URL_ENV] = "https://storage.example.com/system-knowledge-claims"
    return values


def test_deployed_settings_require_managed_identity_blob_claims() -> None:
    settings = SystemKnowledgeSettings.parse(_environment(venue="deployed"))

    assert settings.claim_container_url is not None
    assert settings.managed_identity_client_id == settings.teams.application_id
    assert settings.teams.client_secret is None


def test_deployed_settings_reject_missing_claim_container() -> None:
    values = _environment(venue="deployed")
    del values[CLAIM_CONTAINER_URL_ENV]

    with pytest.raises(SystemKnowledgeConfigurationError, match=CLAIM_CONTAINER_URL_ENV):
        SystemKnowledgeSettings.parse(values)


def test_local_settings_reject_deployed_blob_binding() -> None:
    values = _environment(venue="local")
    values[CLAIM_CONTAINER_URL_ENV] = "https://storage.example.com/system-knowledge-claims"

    with pytest.raises(SystemKnowledgeConfigurationError, match="MUST be unset"):
        SystemKnowledgeSettings.parse(values)


def test_outgoing_webhook_settings_need_no_bot_application() -> None:
    values = _environment(venue="deployed")
    values["FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT"] = "outgoing_webhook"
    values[OUTGOING_HMAC_SECRET_ENV] = base64.b64encode(b"k" * 32).decode()
    for name in (
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL",
    ):
        del values[name]

    settings = SystemKnowledgeSettings.parse(values)

    assert settings.teams_transport is TeamsTransport.OUTGOING_WEBHOOK
    assert isinstance(settings.teams, TeamsOutgoingWebhookSettings)
    assert settings.teams.hmac_secret == values[OUTGOING_HMAC_SECRET_ENV]


def test_outgoing_webhook_bootstrap_allows_missing_hmac() -> None:
    values = _environment(venue="deployed")
    values["FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT"] = "outgoing_webhook"
    for name in (
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON",
        "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL",
    ):
        del values[name]

    settings = SystemKnowledgeSettings.parse(values)

    assert isinstance(settings.teams, TeamsOutgoingWebhookSettings)
    assert settings.teams.hmac_secret is None


def test_outgoing_webhook_rejects_invalid_hmac_secret() -> None:
    values = _environment(venue="deployed")
    values["FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT"] = "outgoing_webhook"
    values[OUTGOING_HMAC_SECRET_ENV] = "not-base64"

    with pytest.raises(
        SystemKnowledgeConfigurationError,
        match="MUST be valid Base64",
    ):
        SystemKnowledgeSettings.parse(values)
