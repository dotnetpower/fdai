"""HMAC-authenticated Teams Outgoing Webhook mention admission."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from fdai_system_knowledge_service.config import TeamsOutgoingWebhookSettings
from fdai_system_knowledge_service.teams_auth import TeamsIngressError
from fdai_system_knowledge_service.teams_ingress import (
    VerifiedKnowledgeTurn,
    decode_teams_activity,
    parse_verified_knowledge_turn,
)


class TeamsOutgoingWebhookVerifier:
    """Admit only HMAC-authenticated mentions from configured standard channels."""

    def __init__(self, *, settings: TeamsOutgoingWebhookSettings) -> None:
        self._settings = settings
        self._signing_key = _signing_key(settings.hmac_secret)

    async def warm(self) -> None:
        """Keep bootstrap readiness independent from optional HMAC activation."""

    async def parse(
        self,
        *,
        body: bytes,
        authorization: str,
        received_at: datetime,
    ) -> VerifiedKnowledgeTurn | None:
        """Verify the raw body before decoding and admitting one direct mention."""

        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("Teams received_at MUST be timezone-aware")
        if self._signing_key is None:
            raise TeamsIngressError(
                "Teams Outgoing Webhook HMAC is not configured",
                code="outgoing_webhook_unconfigured",
                http_status=503,
            )
        provided = _authorization_digest(authorization)
        expected = base64.b64encode(
            hmac.new(self._signing_key, body, hashlib.sha256).digest()
        ).decode("ascii")
        if not hmac.compare_digest(provided, expected):
            raise TeamsIngressError(
                "Teams Outgoing Webhook HMAC verification failed",
                code="invalid_webhook_signature",
                http_status=401,
            )
        payload = decode_teams_activity(body)
        _verify_activity_time(payload, received_at=received_at)
        turn = parse_verified_knowledge_turn(
            payload=payload,
            received_at=received_at,
            settings=self._settings,
            expected_recipient_id=None,
            service_url="",
            verification_ref="teams-outgoing-hmac",
        )
        if turn is None:
            raise TeamsIngressError(
                "Teams Outgoing Webhook activity has no verified mention",
                code="missing_webhook_mention",
                http_status=400,
            )
        return turn


def _signing_key(value: str | None) -> bytes | None:
    if value is None:
        return None
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Teams Outgoing Webhook HMAC secret is invalid Base64") from exc
    if len(key) != 32:
        raise ValueError("Teams Outgoing Webhook HMAC secret must decode to 32 bytes")
    return key


def _authorization_digest(value: str) -> str:
    scheme, separator, digest = value.partition(" ")
    if (
        separator != " "
        or scheme.casefold() != "hmac"
        or not digest
        or " " in digest
        or len(digest) > 128
    ):
        raise TeamsIngressError(
            "Teams Outgoing Webhook authorization header is invalid",
            code="invalid_webhook_signature",
            http_status=401,
        )
    return digest


def _verify_activity_time(payload: Mapping[str, Any], *, received_at: datetime) -> None:
    value = payload.get("timestamp")
    if not isinstance(value, str) or len(value) > 64:
        raise TeamsIngressError(
            "Teams Outgoing Webhook timestamp is invalid",
            code="invalid_webhook_timestamp",
            http_status=401,
        )
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TeamsIngressError(
            "Teams Outgoing Webhook timestamp is invalid",
            code="invalid_webhook_timestamp",
            http_status=401,
        ) from exc
    if (
        timestamp.tzinfo is None
        or timestamp.utcoffset() is None
        or abs(received_at - timestamp) > timedelta(minutes=5)
    ):
        raise TeamsIngressError(
            "Teams Outgoing Webhook timestamp is stale",
            code="stale_webhook_activity",
            http_status=401,
        )


__all__ = ["TeamsOutgoingWebhookVerifier"]
