"""Mention-only Teams activity admission for the system-knowledge service."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fdai_service_contracts.ontology_query import content_digest

from fdai_system_knowledge_service.config import (
    TeamsOutgoingWebhookSettings,
    TeamsSettings,
    normalize_service_url,
)
from fdai_system_knowledge_service.teams_auth import (
    ServiceTokenVerifier,
    TeamsIngressError,
    VerifiedServiceToken,
)

_MAX_BODY_BYTES = 256_000


@dataclass(frozen=True, slots=True)
class VerifiedKnowledgeTurn:
    """One direct bot mention bound to an authorized knowledge principal."""

    conversation_id: str
    message_id: str
    sender_id: str
    principal_id: str
    principal_scope_digest: str
    service_url: str
    query: str
    locale: Literal["en", "ko"]
    verification_ref: str

    @property
    def message_key(self) -> str:
        """Return a provider-stable duplicate key."""

        return content_digest(
            {
                "channel": "msteams",
                "conversation_id": self.conversation_id,
                "message_id": self.message_id,
            }
        )


class TeamsMentionVerifier:
    """Admit only direct mentions in configured standard channels."""

    def __init__(self, *, settings: TeamsSettings, tokens: ServiceTokenVerifier) -> None:
        self._settings = settings
        self._tokens = tokens

    async def warm(self) -> None:
        """Warm the injected service-token trust source."""

        await self._tokens.warm()

    async def parse(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> VerifiedKnowledgeTurn | None:
        """Return a verified question, or `None` for a valid non-mention activity."""

        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("Teams received_at MUST be timezone-aware")
        if len(body) > _MAX_BODY_BYTES:
            raise TeamsIngressError(
                "Teams activity exceeds the configured bound",
                code="body_too_large",
                http_status=413,
            )
        token = await self._tokens.verify(authorization)
        payload = decode_teams_activity(body)
        service_url = _service_url(payload, token, self._settings)
        return parse_verified_knowledge_turn(
            payload=payload,
            received_at=received_at,
            settings=self._settings,
            expected_recipient_id=self._settings.bot_id,
            service_url=service_url,
            verification_ref=f"teams-service-key:{token.key_id}",
        )


def parse_verified_knowledge_turn(
    *,
    payload: Mapping[str, Any],
    received_at: datetime,
    settings: TeamsSettings | TeamsOutgoingWebhookSettings,
    expected_recipient_id: str | None,
    service_url: str,
    verification_ref: str,
) -> VerifiedKnowledgeTurn | None:
    """Parse one authenticated activity and enforce common mention boundaries."""

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("Teams received_at MUST be timezone-aware")
    if payload.get("type") != "message" or payload.get("channelId") != "msteams":
        raise TeamsIngressError(
            "Teams activity type is unsupported",
            code="unsupported_activity",
            http_status=400,
        )
    conversation = _object(payload, "conversation")
    if conversation.get("conversationType") != "channel":
        raise TeamsIngressError(
            "Teams conversation type is unsupported",
            code="unsupported_conversation",
            http_status=400,
        )
    channel_data = _object(payload, "channelData")
    tenant_ids = {_text(_object(channel_data, "tenant"), "id", 200)}
    conversation_tenant = conversation.get("tenantId")
    if conversation_tenant is not None:
        if not isinstance(conversation_tenant, str) or not conversation_tenant:
            raise TeamsIngressError(
                "Teams conversation tenant is invalid",
                code="invalid_payload",
                http_status=400,
            )
        tenant_ids.add(conversation_tenant)
    team_id = _text(_object(channel_data, "team"), "id", 256)
    channel_id = _text(_object(channel_data, "channel"), "id", 256)
    if (
        tenant_ids != {settings.tenant_id}
        or team_id not in settings.team_ids
        or channel_id not in settings.channel_ids
    ):
        raise TeamsIngressError(
            "Teams destination is not authorized",
            code="unknown_destination",
            http_status=403,
        )
    recipient_id = _text(_object(payload, "recipient"), "id", 256)
    if expected_recipient_id is not None and recipient_id != expected_recipient_id:
        raise TeamsIngressError(
            "Teams recipient is not the configured bot",
            code="unknown_recipient",
            http_status=403,
        )
    sender_id = _text(_object(payload, "from"), "aadObjectId", 200)
    principal_id = settings.principal_by_aad_object_id.get(sender_id)
    if principal_id is None:
        raise TeamsIngressError(
            "Teams sender is not authorized",
            code="unknown_sender",
            http_status=403,
        )
    mention_texts = _bot_mentions(payload.get("entities"), recipient_id)
    if not mention_texts:
        return None
    query = _optional_text(payload, "text", 16_000)
    for mention_text in mention_texts:
        query = query.replace(mention_text, " ")
    return VerifiedKnowledgeTurn(
        conversation_id=_text(conversation, "id", 512),
        message_id=_text(payload, "id", 256),
        sender_id=sender_id,
        principal_id=principal_id,
        principal_scope_digest=content_digest(
            {"principal_id": principal_id, "purpose": "system-knowledge"}
        ),
        service_url=service_url,
        query=" ".join(query.split()),
        locale=(
            "ko" if _optional_text(payload, "locale", 32).casefold().startswith("ko") else "en"
        ),
        verification_ref=verification_ref,
    )


def decode_teams_activity(body: bytes) -> Mapping[str, Any]:
    """Decode one bounded Teams activity after transport authentication."""

    if len(body) > _MAX_BODY_BYTES:
        raise TeamsIngressError(
            "Teams activity exceeds the configured bound",
            code="body_too_large",
            http_status=413,
        )
    return _json_object(body)


def _service_url(
    payload: Mapping[str, Any],
    token: VerifiedServiceToken,
    settings: TeamsSettings,
) -> str:
    try:
        activity_url = normalize_service_url(_text(payload, "serviceUrl", 512))
        token_url = normalize_service_url(token.service_url)
    except ValueError as exc:
        raise TeamsIngressError(
            "Teams service URL is invalid",
            code="invalid_service_url",
            http_status=403,
        ) from exc
    if activity_url != token_url or activity_url not in settings.allowed_service_urls:
        raise TeamsIngressError(
            "Teams service URL is not authorized",
            code="invalid_service_url",
            http_status=403,
        )
    return activity_url


def _bot_mentions(value: object, recipient_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 32:
        raise TeamsIngressError(
            "Teams mention entities are invalid",
            code="invalid_payload",
            http_status=400,
        )
    mentions: list[str] = []
    for entity in value:
        if not isinstance(entity, Mapping) or entity.get("type") != "mention":
            continue
        mentioned = entity.get("mentioned")
        if not isinstance(mentioned, Mapping) or mentioned.get("id") != recipient_id:
            continue
        text = entity.get("text")
        if not isinstance(text, str) or not text or len(text) > 512:
            raise TeamsIngressError(
                "Teams bot mention text is invalid",
                code="invalid_payload",
                http_status=400,
            )
        mentions.append(text)
    return tuple(dict.fromkeys(mentions))


def _json_object(body: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TeamsIngressError(
            "Teams payload is invalid JSON",
            code="invalid_json",
            http_status=400,
        ) from exc
    if not isinstance(value, Mapping):
        raise TeamsIngressError(
            "Teams payload MUST be an object",
            code="invalid_payload",
            http_status=400,
        )
    return value


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
        raise TeamsIngressError(
            f"Teams {key} is invalid",
            code="invalid_payload",
            http_status=400,
        )
    return item


def _text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > maximum:
        raise TeamsIngressError(
            f"Teams {key} is invalid",
            code="invalid_payload",
            http_status=400,
        )
    return item


def _optional_text(value: Mapping[str, Any], key: str, maximum: int) -> str:
    item = value.get(key, "")
    if not isinstance(item, str) or len(item) > maximum:
        raise TeamsIngressError(
            f"Teams {key} is invalid",
            code="invalid_payload",
            http_status=400,
        )
    return item


__all__ = [
    "TeamsMentionVerifier",
    "VerifiedKnowledgeTurn",
    "decode_teams_activity",
    "parse_verified_knowledge_turn",
]
