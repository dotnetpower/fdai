from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import MappingProxyType

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_system_knowledge_service.config import (
    TeamsOutgoingWebhookSettings,
    TeamsSettings,
)
from fdai_system_knowledge_service.teams import (
    ChannelAccessToken,
    PyJwtServiceTokenVerifier,
    TeamsIngressError,
    TeamsMentionVerifier,
    TeamsOutgoingWebhookVerifier,
    TeamsPublisher,
    VerifiedServiceToken,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)
SERVICE_URL = "https://smba.trafficmanager.net/example"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
PUBLIC_JWK["kid"] = "key-example"


class _Verifier:
    def __init__(self) -> None:
        self.warmed = False

    async def warm(self) -> None:
        self.warmed = True

    async def verify(self, authorization: str) -> VerifiedServiceToken:
        assert authorization == "Bearer service-token"
        return VerifiedServiceToken(service_url=SERVICE_URL, key_id="key-example")


class _TokenProvider:
    def __init__(self) -> None:
        self.closed = False

    async def get_token(self, audience: str) -> ChannelAccessToken:
        return ChannelAccessToken(token="outbound-token", audience=audience)

    async def aclose(self) -> None:
        self.closed = True


class _Jwks:
    async def get_keys(self) -> tuple[dict[str, object], ...]:
        return (PUBLIC_JWK,)


def _settings() -> TeamsSettings:
    return TeamsSettings(
        application_id="application-example",
        bot_id="28:bot-example",
        tenant_id="tenant-example",
        team_ids=frozenset({"team-example"}),
        channel_ids=frozenset({"channel-example"}),
        allowed_service_urls=frozenset({SERVICE_URL}),
        principal_by_aad_object_id=MappingProxyType(
            {"aad-user-example": "knowledge-reader-example"}
        ),
        jwks_url="https://login.example.com/keys",
        client_secret="local-secret",
    )


def _outgoing_settings(*, configured: bool = True) -> TeamsOutgoingWebhookSettings:
    return TeamsOutgoingWebhookSettings(
        tenant_id="tenant-example",
        team_ids=frozenset({"team-example"}),
        channel_ids=frozenset({"channel-example"}),
        principal_by_aad_object_id=MappingProxyType(
            {"aad-user-example": "knowledge-reader-example"}
        ),
        hmac_secret=base64.b64encode(b"k" * 32).decode() if configured else None,
    )


def _hmac_header(body: bytes) -> str:
    digest = base64.b64encode(hmac.new(b"k" * 32, body, hashlib.sha256).digest()).decode()
    return f"HMAC {digest}"


def _activity(
    *,
    entities: object | None = None,
    team_id: str = "team-example",
    conversation_tenant: str | None = None,
) -> bytes:
    payload = {
        "type": "message",
        "id": "message-example",
        "timestamp": NOW.isoformat(),
        "channelId": "msteams",
        "serviceUrl": SERVICE_URL,
        "locale": "ko-KR",
        "conversation": {
            "id": "conversation-example",
            "conversationType": "channel",
            **({"tenantId": conversation_tenant} if conversation_tenant is not None else {}),
        },
        "recipient": {"id": "28:bot-example"},
        "from": {"aadObjectId": "aad-user-example"},
        "channelData": {
            "tenant": {"id": "tenant-example"},
            "team": {"id": team_id},
            "channel": {"id": "channel-example"},
        },
        "text": "<at>FDAI Knowledge</at> 설계와 구현 상태를 설명해줘",
        "entities": entities
        if entities is not None
        else [
            {
                "type": "mention",
                "text": "<at>FDAI Knowledge</at>",
                "mentioned": {"id": "28:bot-example", "name": "FDAI Knowledge"},
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


async def test_mention_verifier_uses_entity_identity_and_removes_only_bot_mention() -> None:
    verifier = _Verifier()
    ingress = TeamsMentionVerifier(settings=_settings(), tokens=verifier)
    await ingress.warm()

    turn = await ingress.parse(
        body=_activity(),
        authorization="Bearer service-token",
        received_at=NOW,
    )

    assert turn is not None
    assert verifier.warmed is True
    assert turn.query == "설계와 구현 상태를 설명해줘"
    assert turn.locale == "ko"
    assert turn.principal_id == "knowledge-reader-example"
    assert turn.verification_ref == "teams-service-key:key-example"


async def test_service_token_verifier_checks_signature_audience_and_service_url() -> None:
    issued_at = datetime.now(UTC)
    token = jwt.encode(
        {
            "aud": "application-example",
            "iss": "https://api.botframework.com",
            "exp": issued_at.timestamp() + 300,
            "nbf": issued_at.timestamp() - 5,
            "serviceurl": SERVICE_URL,
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "key-example"},
    )
    verifier = PyJwtServiceTokenVerifier(
        application_id="application-example",
        jwks=_Jwks(),
    )

    result = await verifier.verify(f"Bearer {token}")

    assert result.service_url == SERVICE_URL
    assert result.key_id == "key-example"


async def test_service_token_verifier_rejects_wrong_audience() -> None:
    issued_at = datetime.now(UTC)
    token = jwt.encode(
        {
            "aud": "other-application",
            "iss": "https://api.botframework.com",
            "exp": issued_at.timestamp() + 300,
            "nbf": issued_at.timestamp() - 5,
            "serviceurl": SERVICE_URL,
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "key-example"},
    )
    verifier = PyJwtServiceTokenVerifier(
        application_id="application-example",
        jwks=_Jwks(),
    )

    with pytest.raises(TeamsIngressError) as error:
        await verifier.verify(f"Bearer {token}")

    assert error.value.http_status == 401


async def test_text_markup_without_verified_mention_entity_is_ignored() -> None:
    turn = await TeamsMentionVerifier(settings=_settings(), tokens=_Verifier()).parse(
        body=_activity(entities=[]),
        authorization="Bearer service-token",
        received_at=NOW,
    )

    assert turn is None


async def test_outgoing_webhook_verifies_raw_body_before_parsing_mention() -> None:
    body = _activity()
    ingress = TeamsOutgoingWebhookVerifier(settings=_outgoing_settings())

    turn = await ingress.parse(
        body=body,
        authorization=_hmac_header(body),
        received_at=NOW,
    )

    assert turn is not None
    assert turn.query == "설계와 구현 상태를 설명해줘"
    assert turn.verification_ref == "teams-outgoing-hmac"


async def test_outgoing_webhook_rejects_tampered_or_unconfigured_requests() -> None:
    body = _activity()
    ingress = TeamsOutgoingWebhookVerifier(settings=_outgoing_settings())

    with pytest.raises(TeamsIngressError) as tampered:
        await ingress.parse(
            body=body + b" ",
            authorization=_hmac_header(body),
            received_at=NOW,
        )
    with pytest.raises(TeamsIngressError) as unconfigured:
        await TeamsOutgoingWebhookVerifier(settings=_outgoing_settings(configured=False)).parse(
            body=body,
            authorization=_hmac_header(body),
            received_at=NOW,
        )

    assert tampered.value.http_status == 401
    assert tampered.value.code == "invalid_webhook_signature"
    assert unconfigured.value.http_status == 503
    assert unconfigured.value.code == "outgoing_webhook_unconfigured"


async def test_outgoing_webhook_rejects_stale_signed_activity() -> None:
    payload = json.loads(_activity())
    payload["timestamp"] = "2026-09-09T23:00:00+00:00"
    body = json.dumps(payload, separators=(",", ":")).encode()

    with pytest.raises(TeamsIngressError) as stale:
        await TeamsOutgoingWebhookVerifier(settings=_outgoing_settings()).parse(
            body=body,
            authorization=_hmac_header(body),
            received_at=NOW,
        )

    assert stale.value.http_status == 401
    assert stale.value.code == "stale_webhook_activity"


async def test_unknown_team_fails_before_query() -> None:
    with pytest.raises(TeamsIngressError) as error:
        await TeamsMentionVerifier(settings=_settings(), tokens=_Verifier()).parse(
            body=_activity(team_id="other-team"),
            authorization="Bearer service-token",
            received_at=NOW,
        )

    assert error.value.http_status == 403
    assert error.value.code == "unknown_destination"


async def test_conflicting_conversation_tenant_fails_before_query() -> None:
    with pytest.raises(TeamsIngressError) as error:
        await TeamsMentionVerifier(settings=_settings(), tokens=_Verifier()).parse(
            body=_activity(conversation_tenant="other-tenant"),
            authorization="Bearer service-token",
            received_at=NOW,
        )

    assert error.value.http_status == 403
    assert error.value.code == "unknown_destination"


async def test_publisher_posts_same_conversation_reply_with_bounded_token() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "reply-example"})

    tokens = _TokenProvider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsPublisher(http_client=client, tokens=tokens)
        activity_id = await publisher.send(
            conversation_id="conversation/example",
            service_url=SERVICE_URL,
            payload={"type": "message", "replyToId": "message-example", "text": "answer"},
        )
        await publisher.aclose()

    assert activity_id == "reply-example"
    assert captured["url"] == (
        "https://smba.trafficmanager.net/example/v3/conversations/conversation%2Fexample/activities"
    )
    assert captured["authorization"] == "Bearer outbound-token"
    assert captured["payload"] == {
        "type": "message",
        "replyToId": "message-example",
        "text": "answer",
    }
    assert tokens.closed is True
