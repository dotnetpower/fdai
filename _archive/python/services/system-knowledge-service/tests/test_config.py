from __future__ import annotations

import base64
import json

import pytest
from fdai_system_knowledge_service.config import (
    CLAIM_CONTAINER_URL_ENV,
    CLIENT_SECRET_ENV,
    HOST_ENV,
    JWKS_URL_ENV,
    MANAGED_IDENTITY_CLIENT_ID_ENV,
    OUTGOING_HMAC_SECRET_ENV,
    PORT_ENV,
    PRINCIPAL_MAP_ENV,
    SERVICE_URLS_ENV,
    SOURCE_REVISION_ENV,
    TEAM_IDS_ENV,
    TEAMS_TRANSPORT_ENV,
    TENANT_ID_ENV,
    SystemKnowledgeConfigurationError,
    SystemKnowledgeSettings,
    TeamsOutgoingWebhookSettings,
    TeamsTransport,
    normalize_service_url,
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


def test_config_validation_rejects_invalid_fields_and_normalizes_urls() -> None:
    settings = SystemKnowledgeSettings.parse(_environment(venue="local"))
    assert settings.teams_transport is TeamsTransport.BOT_FRAMEWORK
    assert (
        normalize_service_url("https://Example.COM:8443/path/") == "https://example.com:8443/path"
    )

    for bad_url in (
        "http://example.com",
        "https://example.com?query=1",
        "https://user:pass@example.com",
        "https://example.com#frag",
    ):
        with pytest.raises(ValueError, match="HTTPS origin"):
            normalize_service_url(bad_url)

    bad_venue = _environment(venue="local")
    bad_venue["FDAI_EXECUTION_VENUE"] = "invalid-venue"
    with pytest.raises(SystemKnowledgeConfigurationError, match="execution venue is invalid"):
        SystemKnowledgeSettings.parse(bad_venue)

    blank_host = _environment(venue="local")
    blank_host[HOST_ENV] = "   "
    with pytest.raises(SystemKnowledgeConfigurationError, match=HOST_ENV):
        SystemKnowledgeSettings.parse(blank_host)

    for bad_port in ("not-int", "0", "70000"):
        env = _environment(venue="local")
        env[PORT_ENV] = bad_port
        with pytest.raises(SystemKnowledgeConfigurationError, match=PORT_ENV):
            SystemKnowledgeSettings.parse(env)

    no_rev = _environment(venue="deployed")
    del no_rev[SOURCE_REVISION_ENV]
    with pytest.raises(SystemKnowledgeConfigurationError, match=SOURCE_REVISION_ENV):
        SystemKnowledgeSettings.parse(no_rev)

    no_mi = _environment(venue="deployed")
    del no_mi[MANAGED_IDENTITY_CLIENT_ID_ENV]
    with pytest.raises(SystemKnowledgeConfigurationError, match=MANAGED_IDENTITY_CLIENT_ID_ENV):
        SystemKnowledgeSettings.parse(no_mi)

    no_secret = _environment(venue="local")
    del no_secret[CLIENT_SECRET_ENV]
    with pytest.raises(SystemKnowledgeConfigurationError, match=CLIENT_SECRET_ENV):
        SystemKnowledgeSettings.parse(no_secret)

    mismatched_mi = _environment(venue="deployed")
    mismatched_mi[MANAGED_IDENTITY_CLIENT_ID_ENV] = "other-mi"
    with pytest.raises(SystemKnowledgeConfigurationError, match="user-assigned identity"):
        SystemKnowledgeSettings.parse(mismatched_mi)

    bad_transport = _environment(venue="local")
    bad_transport[TEAMS_TRANSPORT_ENV] = "unknown"
    with pytest.raises(SystemKnowledgeConfigurationError, match=TEAMS_TRANSPORT_ENV):
        SystemKnowledgeSettings.parse(bad_transport)

    multi_team_webhook = _environment(venue="local")
    multi_team_webhook[TEAMS_TRANSPORT_ENV] = "outgoing_webhook"
    multi_team_webhook[TEAM_IDS_ENV] = json.dumps(["team-1", "team-2"])
    with pytest.raises(SystemKnowledgeConfigurationError, match="exactly one team"):
        SystemKnowledgeSettings.parse(multi_team_webhook)

    for secret in ("x" * 257, base64.b64encode(b"short").decode()):
        env = _environment(venue="local")
        env[TEAMS_TRANSPORT_ENV] = "outgoing_webhook"
        env[OUTGOING_HMAC_SECRET_ENV] = secret
        with pytest.raises(SystemKnowledgeConfigurationError, match=OUTGOING_HMAC_SECRET_ENV):
            SystemKnowledgeSettings.parse(env)

    missing_tenant = _environment(venue="local")
    del missing_tenant[TENANT_ID_ENV]
    with pytest.raises(SystemKnowledgeConfigurationError, match=TENANT_ID_ENV):
        SystemKnowledgeSettings.parse(missing_tenant)

    long_tenant = _environment(venue="local")
    long_tenant[TENANT_ID_ENV] = "t" * 201
    with pytest.raises(SystemKnowledgeConfigurationError, match="exceeds 200"):
        SystemKnowledgeSettings.parse(long_tenant)

    for bad_teams in ("{bad-json", "[]", '["dup", "dup"]'):
        env = _environment(venue="local")
        env[TEAM_IDS_ENV] = bad_teams
        with pytest.raises(SystemKnowledgeConfigurationError, match=TEAM_IDS_ENV):
            SystemKnowledgeSettings.parse(env)

    bad_principals = _environment(venue="local")
    bad_principals[PRINCIPAL_MAP_ENV] = json.dumps({"same-id": "same-id"})
    with pytest.raises(SystemKnowledgeConfigurationError, match=PRINCIPAL_MAP_ENV):
        SystemKnowledgeSettings.parse(bad_principals)

    for bad_urls in (
        "[]",
        json.dumps(["http://insecure.example.com"]),
        json.dumps(["https://smba.trafficmanager.net/example/"]),
    ):
        env = _environment(venue="local")
        env[SERVICE_URLS_ENV] = bad_urls
        with pytest.raises(SystemKnowledgeConfigurationError, match=SERVICE_URLS_ENV):
            SystemKnowledgeSettings.parse(env)

    bad_jwks = _environment(venue="local")
    bad_jwks[JWKS_URL_ENV] = "http://login.example.com/keys"
    with pytest.raises(SystemKnowledgeConfigurationError, match=JWKS_URL_ENV):
        SystemKnowledgeSettings.parse(bad_jwks)
