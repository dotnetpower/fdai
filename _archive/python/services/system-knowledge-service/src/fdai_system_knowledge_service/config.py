"""Fail-closed environment configuration for the System Knowledge Service."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fdai_service_contracts.venue import (
    ExecutionVenue,
    ExecutionVenueError,
    resolve_execution_venue,
)

HOST_ENV = "FDAI_SYSTEM_KNOWLEDGE_HOST"
PORT_ENV = "FDAI_SYSTEM_KNOWLEDGE_PORT"
CATALOG_PATH_ENV = "FDAI_SYSTEM_KNOWLEDGE_CATALOG_PATH"
SOURCE_REVISION_ENV = "FDAI_SYSTEM_KNOWLEDGE_SOURCE_REVISION"
LEDGER_PATH_ENV = "FDAI_SYSTEM_KNOWLEDGE_LEDGER_PATH"
CLAIM_CONTAINER_URL_ENV = "FDAI_SYSTEM_KNOWLEDGE_CLAIM_CONTAINER_URL"
APPLICATION_ID_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_APPLICATION_ID"
BOT_ID_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_BOT_ID"
TENANT_ID_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TENANT_ID"
TEAM_IDS_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TEAM_IDS_JSON"
CHANNEL_IDS_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CHANNEL_IDS_JSON"
SERVICE_URLS_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_SERVICE_URLS_JSON"
PRINCIPAL_MAP_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_PRINCIPAL_MAP_JSON"
JWKS_URL_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_JWKS_URL"
CLIENT_SECRET_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_CLIENT_SECRET"  # noqa: S105
MANAGED_IDENTITY_CLIENT_ID_ENV = "FDAI_SYSTEM_KNOWLEDGE_MI_CLIENT_ID"
TEAMS_TRANSPORT_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_TRANSPORT"
OUTGOING_HMAC_SECRET_ENV = "FDAI_SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET"  # noqa: S105


class SystemKnowledgeConfigurationError(ValueError):
    """The service cannot establish its release or Teams trust boundary."""


class TeamsTransport(StrEnum):
    """Supported mutually exclusive Teams ingress transports."""

    BOT_FRAMEWORK = "bot_framework"
    OUTGOING_WEBHOOK = "outgoing_webhook"


@dataclass(frozen=True, slots=True)
class TeamsSettings:
    """Exact Teams application, destination, sender, and token configuration."""

    application_id: str
    bot_id: str
    tenant_id: str
    team_ids: frozenset[str]
    channel_ids: frozenset[str]
    allowed_service_urls: frozenset[str]
    principal_by_aad_object_id: Mapping[str, str]
    jwks_url: str
    client_secret: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class TeamsOutgoingWebhookSettings:
    """Exact Outgoing Webhook destination, sender, and HMAC configuration."""

    tenant_id: str
    team_ids: frozenset[str]
    channel_ids: frozenset[str]
    principal_by_aad_object_id: Mapping[str, str]
    hmac_secret: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SystemKnowledgeSettings:
    """One immutable service environment snapshot."""

    execution_venue: ExecutionVenue
    host: str
    port: int
    catalog_path: Path
    expected_source_revision: str | None
    ledger_path: Path
    claim_container_url: str | None
    managed_identity_client_id: str | None
    teams: TeamsSettings | TeamsOutgoingWebhookSettings

    @property
    def teams_transport(self) -> TeamsTransport:
        """Return the selected Teams ingress transport."""

        if isinstance(self.teams, TeamsSettings):
            return TeamsTransport.BOT_FRAMEWORK
        return TeamsTransport.OUTGOING_WEBHOOK

    @classmethod
    def parse(cls, environ: Mapping[str, str]) -> SystemKnowledgeSettings:
        """Validate the complete runtime configuration before opening ingress."""

        values = dict(environ)
        try:
            venue = resolve_execution_venue(values)
        except ExecutionVenueError as exc:
            raise SystemKnowledgeConfigurationError(
                "system knowledge execution venue is invalid"
            ) from exc
        host = values.get(HOST_ENV, "127.0.0.1").strip()
        if not host:
            raise SystemKnowledgeConfigurationError(f"{HOST_ENV} MUST be non-empty")
        port = _port(values.get(PORT_ENV, "8015"))
        default_catalog = files("fdai_system_knowledge_service").joinpath("data", "catalog.json")
        catalog_path = Path(values.get(CATALOG_PATH_ENV, str(default_catalog))).expanduser()
        expected_revision = values.get(SOURCE_REVISION_ENV, "").strip() or None
        if venue is ExecutionVenue.DEPLOYED and expected_revision is None:
            raise SystemKnowledgeConfigurationError(
                f"{SOURCE_REVISION_ENV} MUST be set in the deployed venue"
            )
        ledger_path = Path(
            values.get(LEDGER_PATH_ENV, ".fdai/system-knowledge-ledger.sqlite3")
        ).expanduser()
        claim_container_url_raw = values.get(CLAIM_CONTAINER_URL_ENV, "").strip()
        claim_container_url = (
            _https_url(claim_container_url_raw, CLAIM_CONTAINER_URL_ENV)
            if claim_container_url_raw
            else None
        )
        if venue is ExecutionVenue.LOCAL and claim_container_url is not None:
            raise SystemKnowledgeConfigurationError(
                f"{CLAIM_CONTAINER_URL_ENV} MUST be unset in the local venue"
            )
        if venue is ExecutionVenue.DEPLOYED and claim_container_url is None:
            raise SystemKnowledgeConfigurationError(
                f"{CLAIM_CONTAINER_URL_ENV} MUST be set in the deployed venue"
            )
        transport = _teams_transport(values)
        managed_identity_client_id = values.get(MANAGED_IDENTITY_CLIENT_ID_ENV, "").strip() or None
        if venue is ExecutionVenue.DEPLOYED and managed_identity_client_id is None:
            raise SystemKnowledgeConfigurationError(
                f"{MANAGED_IDENTITY_CLIENT_ID_ENV} MUST be set in the deployed venue"
            )
        tenant_id = _bounded(_required(values, TENANT_ID_ENV), TENANT_ID_ENV, 200)
        team_ids = _id_set(values, TEAM_IDS_ENV)
        channel_ids = _id_set(values, CHANNEL_IDS_ENV)
        principal_map = MappingProxyType(_principal_map(values, PRINCIPAL_MAP_ENV))
        if transport is TeamsTransport.BOT_FRAMEWORK:
            application_id = _required(values, APPLICATION_ID_ENV)
            client_secret = values.get(CLIENT_SECRET_ENV, "").strip() or None
            if venue is ExecutionVenue.LOCAL and client_secret is None:
                raise SystemKnowledgeConfigurationError(
                    f"{CLIENT_SECRET_ENV} MUST be set in the local venue"
                )
            if venue is ExecutionVenue.DEPLOYED and (
                client_secret is not None or managed_identity_client_id != application_id
            ):
                raise SystemKnowledgeConfigurationError(
                    "deployed Teams identity MUST use the application user-assigned identity"
                )
            teams: TeamsSettings | TeamsOutgoingWebhookSettings = TeamsSettings(
                application_id=_bounded(application_id, APPLICATION_ID_ENV, 200),
                bot_id=_bounded(_required(values, BOT_ID_ENV), BOT_ID_ENV, 256),
                tenant_id=tenant_id,
                team_ids=team_ids,
                channel_ids=channel_ids,
                allowed_service_urls=_service_urls(values),
                principal_by_aad_object_id=principal_map,
                jwks_url=_https_url(_required(values, JWKS_URL_ENV), JWKS_URL_ENV),
                client_secret=client_secret,
            )
        else:
            if len(team_ids) != 1:
                raise SystemKnowledgeConfigurationError(
                    f"{TEAM_IDS_ENV} MUST contain exactly one team for outgoing_webhook"
                )
            hmac_secret = _optional_hmac_secret(values)
            teams = TeamsOutgoingWebhookSettings(
                tenant_id=tenant_id,
                team_ids=team_ids,
                channel_ids=channel_ids,
                principal_by_aad_object_id=principal_map,
                hmac_secret=hmac_secret,
            )
        return cls(
            execution_venue=venue,
            host=host,
            port=port,
            catalog_path=catalog_path,
            expected_source_revision=expected_revision,
            ledger_path=ledger_path,
            claim_container_url=claim_container_url,
            managed_identity_client_id=managed_identity_client_id,
            teams=teams,
        )


def normalize_service_url(value: str) -> str:
    """Normalize one Bot service HTTPS origin without query or fragment."""

    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Teams service URL MUST be an HTTPS origin")
    port = f":{parts.port}" if parts.port is not None else ""
    return urlunsplit(("https", parts.hostname.lower() + port, parts.path.rstrip("/"), "", ""))


def _teams_transport(values: Mapping[str, str]) -> TeamsTransport:
    raw = values.get(TEAMS_TRANSPORT_ENV, TeamsTransport.BOT_FRAMEWORK.value).strip()
    try:
        return TeamsTransport(raw)
    except ValueError as exc:
        raise SystemKnowledgeConfigurationError(
            f"{TEAMS_TRANSPORT_ENV} MUST be bot_framework or outgoing_webhook"
        ) from exc


def _optional_hmac_secret(values: Mapping[str, str]) -> str | None:
    value = values.get(OUTGOING_HMAC_SECRET_ENV, "").strip() or None
    if value is None:
        return None
    if len(value) > 256:
        raise SystemKnowledgeConfigurationError(
            f"{OUTGOING_HMAC_SECRET_ENV} exceeds 256 characters"
        )
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemKnowledgeConfigurationError(
            f"{OUTGOING_HMAC_SECRET_ENV} MUST be valid Base64"
        ) from exc
    if len(decoded) != 32:
        raise SystemKnowledgeConfigurationError(
            f"{OUTGOING_HMAC_SECRET_ENV} MUST decode to 32 bytes"
        )
    return value


def _port(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemKnowledgeConfigurationError(f"{PORT_ENV} MUST be an integer") from exc
    if not 1 <= value <= 65535:
        raise SystemKnowledgeConfigurationError(f"{PORT_ENV} MUST be in [1, 65535]")
    return value


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise SystemKnowledgeConfigurationError(f"{name} MUST be set")
    return value


def _bounded(value: str, name: str, maximum: int) -> str:
    if len(value) > maximum:
        raise SystemKnowledgeConfigurationError(f"{name} exceeds {maximum} characters")
    return value


def _json(values: Mapping[str, str], name: str) -> Any:
    try:
        return json.loads(_required(values, name))
    except json.JSONDecodeError as exc:
        raise SystemKnowledgeConfigurationError(f"{name} MUST contain valid JSON") from exc


def _id_set(values: Mapping[str, str], name: str) -> frozenset[str]:
    raw = _json(values, name)
    if (
        not isinstance(raw, list)
        or not raw
        or len(raw) > 100
        or any(not isinstance(item, str) or not item or len(item) > 256 for item in raw)
    ):
        raise SystemKnowledgeConfigurationError(f"{name} MUST be a non-empty bounded string array")
    result = frozenset(raw)
    if len(result) != len(raw):
        raise SystemKnowledgeConfigurationError(f"{name} MUST contain unique values")
    return result


def _principal_map(values: Mapping[str, str], name: str) -> dict[str, str]:
    raw = _json(values, name)
    if (
        not isinstance(raw, dict)
        or not raw
        or len(raw) > 1000
        or any(
            not isinstance(sender, str)
            or not sender
            or len(sender) > 200
            or not isinstance(principal, str)
            or not principal
            or len(principal) > 256
            or sender == principal
            for sender, principal in raw.items()
        )
    ):
        raise SystemKnowledgeConfigurationError(
            f"{name} MUST contain bounded distinct sender and principal identities"
        )
    return dict(raw)


def _service_urls(values: Mapping[str, str]) -> frozenset[str]:
    raw = _json(values, SERVICE_URLS_ENV)
    if not isinstance(raw, list) or not raw or len(raw) > 32:
        raise SystemKnowledgeConfigurationError(
            f"{SERVICE_URLS_ENV} MUST be a non-empty bounded string array"
        )
    try:
        normalized = tuple(normalize_service_url(str(item)) for item in raw)
    except ValueError as exc:
        raise SystemKnowledgeConfigurationError(
            f"{SERVICE_URLS_ENV} contains an invalid URL"
        ) from exc
    if tuple(raw) != normalized or len(set(normalized)) != len(normalized):
        raise SystemKnowledgeConfigurationError(
            f"{SERVICE_URLS_ENV} MUST contain unique normalized URLs"
        )
    return frozenset(normalized)


def _https_url(value: str, name: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise SystemKnowledgeConfigurationError(f"{name} MUST be an HTTPS URL")
    return value


__all__ = [
    "SystemKnowledgeConfigurationError",
    "SystemKnowledgeSettings",
    "TeamsOutgoingWebhookSettings",
    "TeamsSettings",
    "TeamsTransport",
    "normalize_service_url",
]
