"""Validate the standalone Operator channel-edge process environment."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    normalize_teams_service_url,
)
from fdai_service_contracts import OperatorRole, canonical_digest
from fdai_service_contracts.venue import (
    ExecutionVenue,
    ExecutionVenueError,
    resolve_execution_venue,
)

HOST_ENV = "FDAI_CHANNEL_EDGE_HOST"
PORT_ENV = "FDAI_CHANNEL_EDGE_PORT"
ENABLED_CHANNELS_ENV = "FDAI_CHANNEL_EDGE_ENABLED_CHANNELS"
DATABASE_URL_ENV = "FDAI_DATABASE_URL"
DATABASE_ROLE_ENV = "FDAI_DATABASE_ROLE"
KAFKA_BOOTSTRAP_ENV = "FDAI_KAFKA_BOOTSTRAP_SERVERS"
SEMANTIC_REQUEST_TOPIC_ENV = "FDAI_SEMANTIC_TURN_REQUEST_TOPIC"
SEMANTIC_PROJECTION_TOPIC_ENV = "FDAI_SEMANTIC_TURN_PROJECTION_TOPIC"
SEMANTIC_PHYSICAL_TOPIC_ENV = "FDAI_SEMANTIC_TURN_PHYSICAL_TOPIC"
SEMANTIC_CONSUMER_GROUP_ENV = "FDAI_CHANNEL_EDGE_SEMANTIC_CONSUMER_GROUP_ID"
SEMANTIC_CLIENT_ID_ENV = "FDAI_CHANNEL_EDGE_SEMANTIC_CLIENT_ID"
PRINCIPAL_SCOPES_ENV = "FDAI_CHANNEL_EDGE_PRINCIPAL_SCOPES_JSON"
ATTACHMENTS_ENABLED_ENV = "FDAI_CHANNEL_ATTACHMENTS_ENABLED"
ATTACHMENT_INTAKE_ORIGIN_ENV = "FDAI_CHANNEL_ATTACHMENT_INTAKE_ORIGIN"
ATTACHMENT_INTAKE_AUDIENCE_ENV = "FDAI_CHANNEL_ATTACHMENT_INTAKE_AUDIENCE"
ATTACHMENT_CLIENT_ID_ENV = "FDAI_CHANNEL_ATTACHMENT_CLIENT_ID"
ATTACHMENT_TENANT_ID_ENV = "FDAI_CHANNEL_ATTACHMENT_TENANT_ID"
ATTACHMENT_CLIENT_SECRET_ENV = "FDAI_CHANNEL_ATTACHMENT_CLIENT_SECRET"  # noqa: S105
ATTACHMENT_SCRATCH_DIR_ENV = "FDAI_CHANNEL_ATTACHMENT_SCRATCH_DIR"
ATTACHMENT_SCRATCH_ENCRYPTED_ENV = "FDAI_CHANNEL_ATTACHMENT_SCRATCH_ENCRYPTED"
ATTACHMENT_MAX_BYTES_ENV = "FDAI_CHANNEL_ATTACHMENT_MAX_CONTENT_BYTES"
SLACK_FILES_INFO_URL_ENV = "FDAI_SLACK_FILES_INFO_URL"
SLACK_ATTACHMENT_METADATA_HOSTS_ENV = "FDAI_SLACK_ATTACHMENT_METADATA_HOSTS_JSON"
SLACK_ATTACHMENT_DOWNLOAD_HOSTS_ENV = "FDAI_SLACK_ATTACHMENT_DOWNLOAD_HOSTS_JSON"
TEAMS_ATTACHMENT_URL_TEMPLATE_ENV = "FDAI_TEAMS_ATTACHMENT_URL_TEMPLATE"
TEAMS_ATTACHMENT_AUDIENCE_ENV = "FDAI_TEAMS_ATTACHMENT_AUDIENCE"
TEAMS_ATTACHMENT_HOSTS_ENV = "FDAI_TEAMS_ATTACHMENT_HOSTS_JSON"
TEAMS_ATTACHMENT_AUDIENCES_ENV = "FDAI_TEAMS_ATTACHMENT_AUDIENCES_JSON"
SLACK_SIGNING_SECRET_ENV = "FDAI_SLACK_SIGNING_SECRET"  # noqa: S105 - environment key
SLACK_BOT_TOKEN_ENV = "FDAI_SLACK_BOT_TOKEN"  # noqa: S105 - environment key
SLACK_TEAM_ID_ENV = "FDAI_SLACK_TEAM_ID"
SLACK_PRINCIPAL_MAP_ENV = "FDAI_SLACK_PRINCIPAL_MAP_JSON"
TEAMS_APPLICATION_ID_ENV = "FDAI_TEAMS_APPLICATION_ID"
TEAMS_TENANT_ID_ENV = "FDAI_TEAMS_TENANT_ID"
TEAMS_PRINCIPAL_MAP_ENV = "FDAI_TEAMS_PRINCIPAL_MAP_JSON"
TEAMS_SERVICE_URLS_ENV = "FDAI_TEAMS_ALLOWED_SERVICE_URLS_JSON"
TEAMS_JWKS_URL_ENV = "FDAI_TEAMS_JWKS_URL"
TEAMS_CLIENT_SECRET_ENV = "FDAI_TEAMS_CLIENT_SECRET"  # noqa: S105 - environment key
MANAGED_IDENTITY_CLIENT_ID_ENV = "FDAI_CHANNEL_EDGE_MI_CLIENT_ID"

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - ingress terminates external HTTPS.
DEFAULT_PORT = 8014
EXPECTED_DATABASE_ROLE = "fdai_operator"
DEFAULT_SEMANTIC_GROUP = "operator-channel-edge-semantic-v1"
DEFAULT_SEMANTIC_CLIENT_ID = "fdai-operator-channel-edge"


class ChannelEdgeConfigurationError(ValueError):
    """The channel edge cannot establish every enabled trust dependency."""


@dataclass(frozen=True, slots=True)
class PrincipalScopeSettings:
    """Configure server-owned scope and roles for one canonical principal."""

    scope_ref: str
    roles: frozenset[str]
    locale: str = "en"


@dataclass(frozen=True, slots=True)
class SlackEdgeSettings:
    """Configure Slack request trust and fixed outbound credentials."""

    signing_secret: str = field(repr=False)
    bot_token: str = field(repr=False)
    team_id: str
    principal_by_sender_id: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class TeamsEdgeSettings:
    """Configure Teams request trust, endpoints, and outbound identity."""

    application_id: str
    tenant_id: str
    principal_by_aad_object_id: Mapping[str, str]
    allowed_service_urls: frozenset[str]
    jwks_url: str
    client_secret: str | None = field(default=None, repr=False)
    managed_identity_client_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttachmentEdgeSettings:
    """Configure only fixed internal and vendor attachment trust boundaries."""

    intake_origin: str
    intake_audience: str
    client_id: str
    tenant_id: str | None
    client_secret: str | None = field(repr=False)
    scratch_directory: Path
    max_content_bytes: int
    principal_manifest_digest: str
    slack_files_info_url: str | None = None
    slack_metadata_hosts: frozenset[str] = frozenset()
    slack_download_hosts: frozenset[str] = frozenset()
    teams_url_template: str | None = None
    teams_audience: str | None = None
    teams_hosts: frozenset[str] = frozenset()
    teams_audiences: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ChannelEdgeEnvironment:
    """Hold one immutable, fully resolved channel-edge environment snapshot."""

    values: Mapping[str, str] = field(repr=False)
    host: str
    port: int
    execution_venue: ExecutionVenue
    enabled_channels: frozenset[ChannelKind]
    database_url: str = field(repr=False)
    database_role: str
    kafka_bootstrap_servers: str
    semantic_request_topic: str
    semantic_projection_topic: str
    semantic_physical_topic: str | None
    semantic_consumer_group: str
    semantic_client_id: str
    managed_identity_client_id: str | None
    attachments_enabled: bool
    attachments: AttachmentEdgeSettings | None
    principal_scopes: Mapping[str, PrincipalScopeSettings]
    slack: SlackEdgeSettings | None
    teams: TeamsEdgeSettings | None

    @classmethod
    def parse(cls, environ: Mapping[str, str]) -> ChannelEdgeEnvironment:
        """Reject incomplete channels, identities, stores, and semantic transport."""
        values = dict(environ)
        host = values.get(HOST_ENV, DEFAULT_HOST).strip()
        if not host:
            raise ChannelEdgeConfigurationError(f"{HOST_ENV} MUST be non-empty")
        port = _bounded_int(values, PORT_ENV, DEFAULT_PORT, minimum=1, maximum=65_535)
        try:
            execution_venue = resolve_execution_venue(values)
        except ExecutionVenueError as exc:
            raise ChannelEdgeConfigurationError("channel edge execution venue is invalid") from exc
        enabled_channels = _channels(_required(values, ENABLED_CHANNELS_ENV))
        database_url = _required(values, DATABASE_URL_ENV)
        database_role = _required(values, DATABASE_ROLE_ENV)
        if database_role != EXPECTED_DATABASE_ROLE:
            raise ChannelEdgeConfigurationError(
                f"{DATABASE_ROLE_ENV} MUST be {EXPECTED_DATABASE_ROLE}"
            )
        kafka_bootstrap_servers = _required(values, KAFKA_BOOTSTRAP_ENV)
        semantic_request_topic = _required(values, SEMANTIC_REQUEST_TOPIC_ENV)
        semantic_projection_topic = _required(values, SEMANTIC_PROJECTION_TOPIC_ENV)
        if semantic_request_topic == semantic_projection_topic:
            raise ChannelEdgeConfigurationError(
                "semantic request and projection topics MUST differ"
            )
        semantic_physical_topic = values.get(SEMANTIC_PHYSICAL_TOPIC_ENV, "").strip() or None
        attachments_enabled = _binary_flag(values, ATTACHMENTS_ENABLED_ENV)
        principal_scopes = _principal_scopes(_required(values, PRINCIPAL_SCOPES_ENV))
        slack = (
            _slack_settings(values, principal_scopes)
            if ChannelKind.SLACK in enabled_channels
            else None
        )
        teams = (
            _teams_settings(values, principal_scopes, execution_venue=execution_venue)
            if ChannelKind.TEAMS in enabled_channels
            else None
        )
        attachments = (
            _attachment_settings(
                values,
                execution_venue=execution_venue,
                enabled_channels=enabled_channels,
            )
            if attachments_enabled
            else None
        )
        return cls(
            values=MappingProxyType(values),
            host=host,
            port=port,
            execution_venue=execution_venue,
            enabled_channels=enabled_channels,
            database_url=database_url,
            database_role=database_role,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            semantic_request_topic=semantic_request_topic,
            semantic_projection_topic=semantic_projection_topic,
            semantic_physical_topic=semantic_physical_topic,
            semantic_consumer_group=(
                values.get(SEMANTIC_CONSUMER_GROUP_ENV, "").strip() or DEFAULT_SEMANTIC_GROUP
            ),
            semantic_client_id=(
                values.get(SEMANTIC_CLIENT_ID_ENV, "").strip() or DEFAULT_SEMANTIC_CLIENT_ID
            ),
            managed_identity_client_id=(
                values.get(MANAGED_IDENTITY_CLIENT_ID_ENV, "").strip() or None
            ),
            attachments_enabled=attachments_enabled,
            attachments=attachments,
            principal_scopes=MappingProxyType(principal_scopes),
            slack=slack,
            teams=teams,
        )


def _attachment_settings(
    values: Mapping[str, str],
    *,
    execution_venue: ExecutionVenue,
    enabled_channels: frozenset[ChannelKind],
) -> AttachmentEdgeSettings:
    if not _binary_flag(values, ATTACHMENT_SCRATCH_ENCRYPTED_ENV):
        raise ChannelEdgeConfigurationError(
            f"{ATTACHMENT_SCRATCH_ENCRYPTED_ENV} MUST be 1 when attachments are enabled"
        )
    intake_origin = _attachment_origin(
        _required(values, ATTACHMENT_INTAKE_ORIGIN_ENV),
        execution_venue=execution_venue,
    )
    configured_scratch = Path(_required(values, ATTACHMENT_SCRATCH_DIR_ENV))
    if not configured_scratch.is_absolute():
        raise ChannelEdgeConfigurationError(
            f"{ATTACHMENT_SCRATCH_DIR_ENV} MUST be an absolute path"
        )
    scratch_directory = configured_scratch.resolve()
    slack_files_info_url: str | None = None
    slack_metadata_hosts: frozenset[str] = frozenset()
    slack_download_hosts: frozenset[str] = frozenset()
    if ChannelKind.SLACK in enabled_channels:
        slack_metadata_hosts = _host_allowlist(
            _required(values, SLACK_ATTACHMENT_METADATA_HOSTS_ENV),
            SLACK_ATTACHMENT_METADATA_HOSTS_ENV,
        )
        slack_download_hosts = _host_allowlist(
            _required(values, SLACK_ATTACHMENT_DOWNLOAD_HOSTS_ENV),
            SLACK_ATTACHMENT_DOWNLOAD_HOSTS_ENV,
        )
        slack_files_info_url = _fixed_https_url(
            _required(values, SLACK_FILES_INFO_URL_ENV),
            SLACK_FILES_INFO_URL_ENV,
            allowed_hosts=slack_metadata_hosts,
        )
    teams_url_template: str | None = None
    teams_audience: str | None = None
    teams_hosts: frozenset[str] = frozenset()
    teams_audiences: frozenset[str] = frozenset()
    if ChannelKind.TEAMS in enabled_channels:
        teams_hosts = _host_allowlist(
            _required(values, TEAMS_ATTACHMENT_HOSTS_ENV),
            TEAMS_ATTACHMENT_HOSTS_ENV,
        )
        teams_audiences = _text_allowlist(
            _required(values, TEAMS_ATTACHMENT_AUDIENCES_ENV),
            TEAMS_ATTACHMENT_AUDIENCES_ENV,
        )
        teams_audience = _required(values, TEAMS_ATTACHMENT_AUDIENCE_ENV)
        if teams_audience not in teams_audiences:
            raise ChannelEdgeConfigurationError(
                f"{TEAMS_ATTACHMENT_AUDIENCE_ENV} MUST be in the configured audience allowlist"
            )
        teams_url_template = _required(values, TEAMS_ATTACHMENT_URL_TEMPLATE_ENV)
        if teams_url_template.count("{attachment_id}") != 1:
            raise ChannelEdgeConfigurationError(
                f"{TEAMS_ATTACHMENT_URL_TEMPLATE_ENV} MUST contain one attachment_id placeholder"
            )
        _fixed_https_url(
            teams_url_template.replace("{attachment_id}", "probe"),
            TEAMS_ATTACHMENT_URL_TEMPLATE_ENV,
            allowed_hosts=teams_hosts,
        )
    return AttachmentEdgeSettings(
        intake_origin=intake_origin,
        intake_audience=_bounded(
            _required(values, ATTACHMENT_INTAKE_AUDIENCE_ENV),
            ATTACHMENT_INTAKE_AUDIENCE_ENV,
            512,
        ),
        client_id=_attachment_client_id(values, execution_venue=execution_venue),
        tenant_id=(
            _bounded(
                _required(values, ATTACHMENT_TENANT_ID_ENV),
                ATTACHMENT_TENANT_ID_ENV,
                200,
            )
            if execution_venue is ExecutionVenue.LOCAL
            else None
        ),
        client_secret=(
            _required(values, ATTACHMENT_CLIENT_SECRET_ENV)
            if execution_venue is ExecutionVenue.LOCAL
            else None
        ),
        scratch_directory=scratch_directory,
        max_content_bytes=_bounded_int(
            values,
            ATTACHMENT_MAX_BYTES_ENV,
            25 * 1024 * 1024,
            minimum=1,
            maximum=1024 * 1024 * 1024,
        ),
        principal_manifest_digest=_principal_manifest_digest(
            _required(values, PRINCIPAL_SCOPES_ENV)
        ),
        slack_files_info_url=slack_files_info_url,
        slack_metadata_hosts=slack_metadata_hosts,
        slack_download_hosts=slack_download_hosts,
        teams_url_template=teams_url_template,
        teams_audience=teams_audience,
        teams_hosts=teams_hosts,
        teams_audiences=teams_audiences,
    )


def _attachment_client_id(
    values: Mapping[str, str],
    *,
    execution_venue: ExecutionVenue,
) -> str:
    configured = _bounded(
        _required(values, ATTACHMENT_CLIENT_ID_ENV), ATTACHMENT_CLIENT_ID_ENV, 200
    )
    secret = values.get(ATTACHMENT_CLIENT_SECRET_ENV, "").strip()
    tenant = values.get(ATTACHMENT_TENANT_ID_ENV, "").strip()
    if execution_venue is ExecutionVenue.LOCAL:
        if not secret or not tenant:
            raise ChannelEdgeConfigurationError(
                "local attachment identity requires tenant and client secret"
            )
    else:
        if secret or tenant:
            raise ChannelEdgeConfigurationError(
                "deployed attachment identity MUST NOT use tenant or client secret settings"
            )
        managed = values.get(MANAGED_IDENTITY_CLIENT_ID_ENV, "").strip()
        if not managed or configured != managed:
            raise ChannelEdgeConfigurationError(
                f"{ATTACHMENT_CLIENT_ID_ENV} MUST equal "
                f"{MANAGED_IDENTITY_CLIENT_ID_ENV} when deployed"
            )
    return configured


def _slack_settings(
    values: Mapping[str, str],
    scopes: Mapping[str, PrincipalScopeSettings],
) -> SlackEdgeSettings:
    mapping = _principal_mapping(_required(values, SLACK_PRINCIPAL_MAP_ENV), scopes=scopes)
    return SlackEdgeSettings(
        signing_secret=_required(values, SLACK_SIGNING_SECRET_ENV),
        bot_token=_required(values, SLACK_BOT_TOKEN_ENV),
        team_id=_bounded(_required(values, SLACK_TEAM_ID_ENV), SLACK_TEAM_ID_ENV, 200),
        principal_by_sender_id=MappingProxyType(mapping),
    )


def _teams_settings(
    values: Mapping[str, str],
    scopes: Mapping[str, PrincipalScopeSettings],
    *,
    execution_venue: ExecutionVenue,
) -> TeamsEdgeSettings:
    mapping = _principal_mapping(_required(values, TEAMS_PRINCIPAL_MAP_ENV), scopes=scopes)
    service_urls_raw = _json(_required(values, TEAMS_SERVICE_URLS_ENV))
    if not isinstance(service_urls_raw, list) or not service_urls_raw:
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_SERVICE_URLS_ENV} MUST be a non-empty JSON array"
        )
    parsed_service_urls = tuple(
        _https_url(item, TEAMS_SERVICE_URLS_ENV, allow_query=False) for item in service_urls_raw
    )
    try:
        service_urls = frozenset(normalize_teams_service_url(item) for item in parsed_service_urls)
    except ValueError as exc:
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_SERVICE_URLS_ENV} contains an invalid service URL"
        ) from exc
    if service_urls != frozenset(parsed_service_urls):
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_SERVICE_URLS_ENV} MUST contain normalized service URLs"
        )
    if len(service_urls) != len(service_urls_raw):
        raise ChannelEdgeConfigurationError(f"{TEAMS_SERVICE_URLS_ENV} MUST contain unique URLs")
    client_secret = values.get(TEAMS_CLIENT_SECRET_ENV, "").strip() or None
    managed_identity_client_id = values.get(MANAGED_IDENTITY_CLIENT_ID_ENV, "").strip() or None
    if execution_venue is ExecutionVenue.LOCAL and client_secret is None:
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_CLIENT_SECRET_ENV} MUST be set when Teams is enabled locally"
        )
    if execution_venue is ExecutionVenue.DEPLOYED and client_secret is not None:
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_CLIENT_SECRET_ENV} MUST be unset in the deployed venue"
        )
    if execution_venue is ExecutionVenue.DEPLOYED and (
        managed_identity_client_id is None
        or managed_identity_client_id != values.get(TEAMS_APPLICATION_ID_ENV, "").strip()
    ):
        raise ChannelEdgeConfigurationError(
            f"{TEAMS_APPLICATION_ID_ENV} MUST equal {MANAGED_IDENTITY_CLIENT_ID_ENV} when deployed"
        )
    return TeamsEdgeSettings(
        application_id=_bounded(
            _required(values, TEAMS_APPLICATION_ID_ENV), TEAMS_APPLICATION_ID_ENV, 200
        ),
        tenant_id=_bounded(_required(values, TEAMS_TENANT_ID_ENV), TEAMS_TENANT_ID_ENV, 200),
        principal_by_aad_object_id=MappingProxyType(mapping),
        allowed_service_urls=service_urls,
        jwks_url=_https_url(
            _required(values, TEAMS_JWKS_URL_ENV), TEAMS_JWKS_URL_ENV, allow_query=False
        ),
        client_secret=client_secret,
        managed_identity_client_id=managed_identity_client_id,
    )


def _principal_scopes(value: str) -> dict[str, PrincipalScopeSettings]:
    raw = _json(value)
    if not isinstance(raw, dict) or not raw:
        raise ChannelEdgeConfigurationError(
            f"{PRINCIPAL_SCOPES_ENV} MUST be a non-empty JSON object"
        )
    scopes: dict[str, PrincipalScopeSettings] = {}
    for principal_id, item in raw.items():
        if not isinstance(principal_id, str) or not isinstance(item, dict):
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} has invalid entries")
        if set(item) - {"scope_ref", "roles", "locale"}:
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} has unknown fields")
        scope_ref = item.get("scope_ref")
        roles = item.get("roles")
        locale = item.get("locale", "en")
        if not isinstance(scope_ref, str) or not isinstance(locale, str):
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} has invalid text")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) for role in roles)
        ):
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} has invalid roles")
        try:
            authorized = frozenset(OperatorRole(role).value for role in roles)
        except ValueError as exc:
            raise ChannelEdgeConfigurationError(
                f"{PRINCIPAL_SCOPES_ENV} contains an unsupported role"
            ) from exc
        if len(authorized) != len(roles):
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} contains duplicate roles")
        principal_id = _bounded(principal_id, "principal_id", 256)
        scopes[principal_id] = PrincipalScopeSettings(
            scope_ref=_bounded(scope_ref, "scope_ref", 512),
            roles=authorized,
            locale=_bounded(locale, "locale", 32),
        )
    return scopes


def _principal_manifest_digest(value: str) -> str:
    raw = _json(value)
    if not isinstance(raw, dict):
        raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} MUST be an object")
    normalized: dict[str, dict[str, object]] = {}
    for principal_id, item in raw.items():
        if not isinstance(principal_id, str) or not isinstance(item, dict):
            raise ChannelEdgeConfigurationError(f"{PRINCIPAL_SCOPES_ENV} has invalid entries")
        normalized[principal_id] = {
            "scope_ref": item.get("scope_ref"),
            "roles": item.get("roles"),
            "locale": item.get("locale", "en"),
        }
    return canonical_digest(normalized)


def _principal_mapping(
    value: str,
    *,
    scopes: Mapping[str, PrincipalScopeSettings],
) -> dict[str, str]:
    raw = _json(value)
    if not isinstance(raw, dict) or not raw:
        raise ChannelEdgeConfigurationError("channel principal mapping MUST be a non-empty object")
    result: dict[str, str] = {}
    for sender, principal in raw.items():
        if not isinstance(sender, str) or not isinstance(principal, str):
            raise ChannelEdgeConfigurationError("channel principal mapping entries MUST be text")
        bounded_sender = _bounded(sender, "provider sender", 200)
        bounded_principal = _bounded(principal, "canonical principal", 256)
        if bounded_principal not in scopes or bounded_sender == bounded_principal:
            raise ChannelEdgeConfigurationError(
                "channel principal mapping MUST reference a distinct configured principal"
            )
        result[bounded_sender] = bounded_principal
    return result


def _channels(value: str) -> frozenset[ChannelKind]:
    raw = [item.strip() for item in value.split(",") if item.strip()]
    try:
        channels = frozenset(ChannelKind(item) for item in raw)
    except ValueError as exc:
        raise ChannelEdgeConfigurationError(
            f"{ENABLED_CHANNELS_ENV} contains an unsupported channel"
        ) from exc
    if not channels or ChannelKind.WEB in channels or len(channels) != len(raw):
        raise ChannelEdgeConfigurationError(
            f"{ENABLED_CHANNELS_ENV} MUST contain unique Slack or Teams channels"
        )
    return channels


def _json(value: str) -> Any:
    try:
        return json.loads(value, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ChannelEdgeConfigurationError("channel edge JSON configuration is invalid") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _https_url(value: object, name: str, *, allow_query: bool) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise ChannelEdgeConfigurationError(f"{name} MUST contain bounded HTTPS URLs")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or (parts.query and not allow_query)
    ):
        raise ChannelEdgeConfigurationError(f"{name} MUST contain HTTPS URLs without userinfo")
    return value


def _attachment_origin(value: str, *, execution_venue: ExecutionVenue) -> str:
    parts = urlsplit(value)
    local_http = (
        execution_venue is ExecutionVenue.LOCAL
        and parts.scheme == "http"
        and parts.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if (
        not (parts.scheme == "https" or local_http)
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or (parts.scheme == "https" and parts.port not in {None, 443})
    ):
        raise ChannelEdgeConfigurationError(
            f"{ATTACHMENT_INTAKE_ORIGIN_ENV} MUST be a fixed HTTPS origin"
        )
    return value.rstrip("/")


def _fixed_https_url(
    value: str,
    name: str,
    *,
    allowed_hosts: frozenset[str],
) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname not in allowed_hosts
        or parts.port not in {None, 443}
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ChannelEdgeConfigurationError(f"{name} is outside its fixed HTTPS hosts")
    return value


def _host_allowlist(value: str, name: str) -> frozenset[str]:
    raw = _json(value)
    if not isinstance(raw, list) or not raw:
        raise ChannelEdgeConfigurationError(f"{name} MUST be a non-empty JSON array")
    hosts: list[str] = []
    for item in raw:
        if (
            not isinstance(item, str)
            or len(item) > 253
            or item != item.lower()
            or urlsplit("https://" + item).hostname != item
            or any(character in item for character in "/:@?#")
        ):
            raise ChannelEdgeConfigurationError(f"{name} contains an invalid host")
        hosts.append(item)
    if len(hosts) != len(set(hosts)):
        raise ChannelEdgeConfigurationError(f"{name} MUST contain unique hosts")
    return frozenset(hosts)


def _text_allowlist(value: str, name: str) -> frozenset[str]:
    raw = _json(value)
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in raw)
        or len(raw) != len(set(raw))
    ):
        raise ChannelEdgeConfigurationError(
            f"{name} MUST be a non-empty unique bounded JSON string array"
        )
    return frozenset(raw)


def _required(values: Mapping[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ChannelEdgeConfigurationError(f"{key} MUST be non-empty")
    return value


def _bounded(value: str, name: str, maximum: int) -> str:
    if not value.strip() or len(value) > maximum:
        raise ChannelEdgeConfigurationError(f"{name} MUST be bounded and non-empty")
    return value


def _bounded_int(
    values: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ChannelEdgeConfigurationError(f"{key} MUST be an integer") from exc
    if not minimum <= value <= maximum:
        raise ChannelEdgeConfigurationError(f"{key} is outside the allowed range")
    return value


def _binary_flag(values: Mapping[str, str], key: str) -> bool:
    value = values.get(key, "0").strip()
    if value not in {"0", "1"}:
        raise ChannelEdgeConfigurationError(f"{key} MUST be 0 or 1")
    return value == "1"


__all__ = [
    "AttachmentEdgeSettings",
    "ChannelEdgeConfigurationError",
    "ChannelEdgeEnvironment",
    "PrincipalScopeSettings",
    "SlackEdgeSettings",
    "TeamsEdgeSettings",
]
