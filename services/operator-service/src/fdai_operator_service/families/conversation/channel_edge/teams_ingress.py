"""Authenticate and normalize bounded Microsoft Teams activities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fdai_operator_service.families.conversation.channel_edge.models import (
    MAX_ATTACHMENT_COUNT,
    ChannelAttachment,
    ChannelKind,
    InboundChannelTurn,
)
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsAuthenticationError,
    TeamsServiceTokenVerifier,
)

_DEFAULT_MAX_BODY_BYTES = 256_000


@dataclass(frozen=True, slots=True)
class TeamsIngressConfig:
    """Configure closed tenant, endpoint, and canonical principal admission."""

    tenant_id: str
    allowed_service_urls: frozenset[str]
    principal_by_aad_object_id: Mapping[str, str]
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 200:
            raise ValueError("Teams tenant_id MUST be bounded and non-empty")
        normalized_urls = frozenset(
            normalize_teams_service_url(url) for url in self.allowed_service_urls
        )
        if not normalized_urls or normalized_urls != self.allowed_service_urls:
            raise ValueError("Teams allowed_service_urls MUST contain normalized HTTPS origins")
        if not self.principal_by_aad_object_id or any(
            not sender
            or len(sender) > 200
            or not principal
            or len(principal) > 256
            or sender == principal
            for sender, principal in self.principal_by_aad_object_id.items()
        ):
            raise ValueError("Teams principal mapping MUST contain distinct bounded identities")
        if self.max_body_bytes < 1:
            raise ValueError("Teams max_body_bytes MUST be positive")


@dataclass(frozen=True, slots=True)
class AuthenticatedTeamsTurn:
    """Return one normalized turn with server-owned delivery and principal context."""

    turn: InboundChannelTurn
    service_url: str
    principal_id: str
    verification_ref: str


class TeamsIngressError(ValueError):
    """A Teams activity failed before queue admission without retaining content."""

    def __init__(self, message: str, *, code: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class TeamsIngressVerifier:
    """Verify Bot service identity before accepting tenant and human identity."""

    def __init__(self, *, config: TeamsIngressConfig, tokens: TeamsServiceTokenVerifier) -> None:
        self._config = config
        self._tokens = tokens

    async def parse(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> AuthenticatedTeamsTurn:
        """Authenticate one service activity and replace vendor identity."""
        if received_at.tzinfo is None:
            raise ValueError("Teams received_at MUST include a timezone")
        if len(body) > self._config.max_body_bytes:
            raise TeamsIngressError(
                "Teams request body exceeds the configured limit",
                code="body_too_large",
                http_status=413,
            )
        try:
            service_identity = await self._tokens.verify(authorization)
        except TeamsAuthenticationError as exc:
            raise TeamsIngressError(
                "Teams service authentication failed",
                code="invalid_service_identity",
                http_status=401,
            ) from exc
        payload = _json_object(body)
        if payload.get("type") != "message" or payload.get("channelId") != "msteams":
            raise TeamsIngressError(
                "Teams activity type or channel is unsupported",
                code="unsupported_activity",
                http_status=400,
            )
        try:
            activity_service_url = normalize_teams_service_url(_text(payload, "serviceUrl", 512))
            token_service_url = normalize_teams_service_url(service_identity.service_url)
        except ValueError as exc:
            raise TeamsIngressError(
                "Teams service URL is invalid", code="invalid_service_url", http_status=403
            ) from exc
        if (
            activity_service_url != token_service_url
            or activity_service_url not in self._config.allowed_service_urls
        ):
            raise TeamsIngressError(
                "Teams service URL is not authorized",
                code="invalid_service_url",
                http_status=403,
            )
        conversation = _object(payload, "conversation")
        tenant_ids: set[str] = set()
        conversation_tenant = conversation.get("tenantId")
        if conversation_tenant is not None:
            tenant_ids.add(_bounded_text(conversation_tenant, "tenantId", 200))
        channel_data = payload.get("channelData")
        if isinstance(channel_data, Mapping):
            channel_tenant = channel_data.get("tenant")
            if isinstance(channel_tenant, Mapping):
                tenant_ids.add(_text(channel_tenant, "id", 200))
        if tenant_ids != {self._config.tenant_id}:
            raise TeamsIngressError(
                "Teams tenant is not authorized", code="unknown_tenant", http_status=403
            )
        sender = _object(payload, "from")
        aad_object_id = _text(sender, "aadObjectId", 200)
        principal_id = self._config.principal_by_aad_object_id.get(aad_object_id)
        if principal_id is None:
            raise TeamsIngressError(
                "Teams sender is not authorized", code="unknown_sender", http_status=403
            )
        try:
            turn = InboundChannelTurn(
                channel_kind=ChannelKind.TEAMS,
                channel_id=_text(conversation, "id", 200),
                message_id=_text(payload, "id", 200),
                sender_id=aad_object_id,
                text=_optional_text(payload, "text", 16_000),
                thread_id=_text(conversation, "id", 200),
                attachments=_attachments(payload.get("attachments", ())),
            )
        except ValueError as exc:
            raise TeamsIngressError(
                "Teams activity violates the channel contract",
                code="invalid_payload",
                http_status=400,
            ) from exc
        return AuthenticatedTeamsTurn(
            turn=turn,
            service_url=activity_service_url,
            principal_id=principal_id,
            verification_ref=f"teams-service-key:{service_identity.key_id}",
        )


def normalize_teams_service_url(value: str) -> str:
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


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TeamsIngressError(
            "Teams request body is invalid JSON", code="invalid_json", http_status=400
        ) from exc
    if not isinstance(payload, Mapping):
        raise TeamsIngressError(
            "Teams request body MUST be an object", code="invalid_payload", http_status=400
        )
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _object(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        raise TeamsIngressError(f"Teams {key} is invalid", code="invalid_payload", http_status=400)
    return item


def _text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    return _bounded_text(value.get(key), key, maximum)


def _bounded_text(item: object, name: str, maximum: int) -> str:
    if not isinstance(item, str) or not item.strip() or len(item) > maximum:
        raise TeamsIngressError(f"Teams {name} is invalid", code="invalid_payload", http_status=400)
    return item


def _optional_text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key, "")
    if not isinstance(item, str) or len(item) > maximum:
        raise TeamsIngressError(f"Teams {key} is invalid", code="invalid_payload", http_status=400)
    return item


def _attachments(raw: object) -> tuple[ChannelAttachment, ...]:
    if raw in (None, ()):
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_ATTACHMENT_COUNT:
        raise TeamsIngressError(
            "Teams attachment metadata exceeds the channel limit",
            code="invalid_payload",
            http_status=400,
        )
    attachments: list[ChannelAttachment] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TeamsIngressError(
                "Teams attachment metadata is invalid", code="invalid_payload", http_status=400
            )
        content = item.get("content")
        if not isinstance(content, Mapping):
            raise TeamsIngressError(
                "Teams file attachment content is invalid",
                code="invalid_payload",
                http_status=400,
            )
        size = content.get("fileSize")
        if not isinstance(size, int) or isinstance(size, bool):
            raise TeamsIngressError(
                "Teams file attachment size is invalid",
                code="invalid_payload",
                http_status=400,
            )
        try:
            attachments.append(
                ChannelAttachment(
                    source_ref="teams-file:" + _text(content, "uniqueId", 200),
                    name=_text(item, "name", 512),
                    size_bytes=size,
                    media_type_hint=_text(item, "contentType", 256),
                )
            )
        except ValueError as exc:
            raise TeamsIngressError(
                "Teams file metadata violates the channel contract",
                code="invalid_payload",
                http_status=400,
            ) from exc
    return tuple(attachments)


__all__ = [
    "AuthenticatedTeamsTurn",
    "TeamsIngressConfig",
    "TeamsIngressError",
    "TeamsIngressVerifier",
    "normalize_teams_service_url",
]
