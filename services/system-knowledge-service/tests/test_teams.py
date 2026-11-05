from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import MappingProxyType, SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_system_knowledge_service.config import (
    TeamsOutgoingWebhookSettings,
    TeamsSettings,
)
from fdai_system_knowledge_service.teams import (
    AzureChannelTokenProvider,
    ChannelAccessToken,
    PyJwtServiceTokenVerifier,
    RemoteJwksProvider,
    TeamsIngressError,
    TeamsMentionVerifier,
    TeamsOutgoingWebhookVerifier,
    TeamsPublisher,
    TeamsPublishError,
    VerifiedServiceToken,
)
from fdai_system_knowledge_service.teams_ingress import (
    decode_teams_activity,
    parse_verified_knowledge_turn,
)
from fdai_system_knowledge_service.teams_outgoing_webhook import _signing_key

NOW = datetime(2026, 9, 9, tzinfo=UTC)
ISSUED_AT = datetime(2025, 1, 1, tzinfo=UTC)
EXPIRES_AT = datetime(2099, 1, 1, tzinfo=UTC)
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
    token = jwt.encode(
        {
            "aud": "application-example",
            "iss": "https://api.botframework.com",
            "exp": EXPIRES_AT.timestamp(),
            "nbf": ISSUED_AT.timestamp(),
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
    await verifier.warm()

    result = await verifier.verify(f"Bearer {token}")

    cached = await verifier.verify(f"Bearer {token}")
    assert result.service_url == SERVICE_URL
    assert result.key_id == "key-example"
    assert cached == result


async def test_service_token_verifier_rejects_wrong_audience() -> None:
    token = jwt.encode(
        {
            "aud": "other-application",
            "iss": "https://api.botframework.com",
            "exp": EXPIRES_AT.timestamp(),
            "nbf": ISSUED_AT.timestamp(),
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


async def test_remote_jwks_provider_and_jwt_verifier_error_guards() -> None:
    responses: list[httpx.Response] = [
        httpx.Response(200, json={"keys": [PUBLIC_JWK]}),
        httpx.Response(200, content=b"x" * 2001),
        httpx.Response(200, content=b"{bad"),
        httpx.Response(200, json={"keys": []}),
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RemoteJwksProvider(
            url="https://login.example.com/keys",
            http_client=client,
            max_bytes=2000,
        )
        keys = await provider.get_keys()
        assert len(keys) == 1
        with pytest.raises(RuntimeError, match="exceeds the configured bound"):
            await provider.get_keys()
        with pytest.raises(RuntimeError, match="invalid JSON"):
            await provider.get_keys()
        with pytest.raises(RuntimeError, match="invalid keys"):
            await provider.get_keys()

    verifier = PyJwtServiceTokenVerifier(application_id="application-example", jwks=_Jwks())
    for bad_auth in ("Basic token", "Bearer not-a-jwt"):
        with pytest.raises(TeamsIngressError):
            await verifier.verify(bad_auth)

    no_kid_token = jwt.encode(
        {
            "aud": "application-example",
            "iss": "https://api.botframework.com",
            "exp": EXPIRES_AT.timestamp(),
            "nbf": ISSUED_AT.timestamp(),
            "serviceurl": SERVICE_URL,
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )
    with pytest.raises(TeamsIngressError, match="algorithm or key id"):
        await verifier.verify(f"Bearer {no_kid_token}")

    unknown_kid_token = jwt.encode(
        {
            "aud": "application-example",
            "iss": "https://api.botframework.com",
            "exp": EXPIRES_AT.timestamp(),
            "nbf": ISSUED_AT.timestamp(),
            "serviceurl": SERVICE_URL,
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "unknown-kid"},
    )
    with pytest.raises(TeamsIngressError, match="key id is unknown"):
        await verifier.verify(f"Bearer {unknown_kid_token}")

    empty_service_url_token = jwt.encode(
        {
            "aud": "application-example",
            "iss": "https://api.botframework.com",
            "exp": EXPIRES_AT.timestamp(),
            "nbf": ISSUED_AT.timestamp(),
            "serviceurl": "",
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "key-example"},
    )
    with pytest.raises(TeamsIngressError, match="service URL is invalid"):
        await verifier.verify(f"Bearer {empty_service_url_token}")

    class _BadJwk:
        async def get_keys(self) -> tuple[dict[str, object], ...]:
            return ({"kty": "invalid"},)

    with pytest.raises(RuntimeError, match="invalid key"):
        await PyJwtServiceTokenVerifier(application_id="app", jwks=_BadJwk()).warm()

    class _DupKidJwk:
        async def get_keys(self) -> tuple[dict[str, object], ...]:
            return (PUBLIC_JWK, PUBLIC_JWK)

    with pytest.raises(RuntimeError, match="key ids are invalid"):
        await PyJwtServiceTokenVerifier(application_id="app", jwks=_DupKidJwk()).warm()


async def test_ingress_and_outgoing_webhook_validation_branches() -> None:
    class _AnyAuthVerifier(_Verifier):
        async def verify(self, authorization: str) -> VerifiedServiceToken:
            del authorization
            return VerifiedServiceToken(service_url=SERVICE_URL, key_id="key-example")

    ingress = TeamsMentionVerifier(settings=_settings(), tokens=_AnyAuthVerifier())

    with pytest.raises(ValueError, match="timezone-aware"):
        await ingress.parse(body=b"{}", authorization="******", received_at=datetime(2026, 9, 9))
    with pytest.raises(TeamsIngressError) as too_large:
        await ingress.parse(body=b"x" * 256_001, authorization="******", received_at=NOW)
    assert too_large.value.code == "body_too_large"
    with pytest.raises(TeamsIngressError, match="exceeds the configured bound"):
        decode_teams_activity(b"x" * 256_001)
    with pytest.raises(TeamsIngressError, match="invalid JSON"):
        decode_teams_activity(b'{"a":1,"a":2}')
    with pytest.raises(TeamsIngressError, match="MUST be an object"):
        decode_teams_activity(b"[]")
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_verified_knowledge_turn(
            payload={},
            received_at=datetime(2026, 9, 9),
            settings=_settings(),
            expected_recipient_id="28:bot-example",
            service_url=SERVICE_URL,
            verification_ref="ref",
        )

    base = json.loads(_activity())
    no_entities = dict(base)
    no_entities.pop("entities")
    assert (
        await ingress.parse(
            body=json.dumps(no_entities).encode(),
            authorization="******",
            received_at=NOW,
        )
        is None
    )

    mixed_entities = dict(base)
    mixed_entities["entities"] = [
        {"type": "clientInfo"},
        {"type": "mention", "mentioned": {"id": "other-id"}, "text": "<at>Other</at>"},
        {
            "type": "mention",
            "text": "<at>FDAI Knowledge</at>",
            "mentioned": {"id": "28:bot-example"},
        },
    ]
    assert (
        await ingress.parse(
            body=json.dumps(mixed_entities).encode(),
            authorization="******",
            received_at=NOW,
        )
        is not None
    )

    mutations = [
        ({**base, "type": "typing"}, "unsupported_activity"),
        (
            {**base, "conversation": {**base["conversation"], "conversationType": "personal"}},
            "unsupported_conversation",
        ),
        (
            {**base, "conversation": {**base["conversation"], "tenantId": ""}},
            "invalid_payload",
        ),
        ({**base, "recipient": {"id": "other-bot"}}, "unknown_recipient"),
        ({**base, "from": {"aadObjectId": "unknown-aad"}}, "unknown_sender"),
        ({**base, "serviceUrl": "http://insecure"}, "invalid_service_url"),
        ({**base, "serviceUrl": "https://other.example.com"}, "invalid_service_url"),
        ({**base, "entities": "not-a-list"}, "invalid_payload"),
        (
            {
                **base,
                "entities": [
                    {
                        "type": "mention",
                        "text": "",
                        "mentioned": {"id": "28:bot-example"},
                    }
                ],
            },
            "invalid_payload",
        ),
        ({**base, "conversation": "not-an-object"}, "invalid_payload"),
        ({**base, "id": ""}, "invalid_payload"),
        ({**base, "text": 123}, "invalid_payload"),
    ]
    for mutated, expected_code in mutations:
        with pytest.raises(TeamsIngressError) as err:
            await ingress.parse(
                body=json.dumps(mutated).encode(),
                authorization="******",
                received_at=NOW,
            )
        assert err.value.code == expected_code

    with pytest.raises(ValueError, match="invalid Base64"):
        _signing_key("not-base64")
    with pytest.raises(ValueError, match="32 bytes"):
        _signing_key(base64.b64encode(b"short").decode())

    wh_verifier = TeamsOutgoingWebhookVerifier(settings=_outgoing_settings())
    await wh_verifier.warm()
    with pytest.raises(ValueError, match="timezone-aware"):
        await wh_verifier.parse(
            body=b"{}",
            authorization="HMAC x",
            received_at=datetime(2026, 9, 9),
        )
    with pytest.raises(TeamsIngressError, match="authorization header is invalid"):
        await wh_verifier.parse(body=b"{}", authorization="Bearer x", received_at=NOW)

    for bad_ts in (123, "not-iso-timestamp"):
        ts_payload = {**base, "timestamp": bad_ts}
        ts_body = json.dumps(ts_payload, separators=(",", ":")).encode()
        with pytest.raises(TeamsIngressError) as ts_err:
            await wh_verifier.parse(
                body=ts_body,
                authorization=_hmac_header(ts_body),
                received_at=NOW,
            )
        assert ts_err.value.code == "invalid_webhook_timestamp"

    no_mention_body = _activity(entities=[])
    with pytest.raises(TeamsIngressError) as no_mention_err:
        await wh_verifier.parse(
            body=no_mention_body,
            authorization=_hmac_header(no_mention_body),
            received_at=NOW,
        )
    assert no_mention_err.value.code == "missing_webhook_mention"


async def test_azure_channel_token_provider_and_publisher_error_branches() -> None:
    closed = False

    class _Cred:
        def __init__(self, token_value: str) -> None:
            self._token = token_value

        async def get_token(self, _audience: str) -> SimpleNamespace:
            return SimpleNamespace(token=self._token)

        async def close(self) -> None:
            nonlocal closed
            closed = True

    provider = AzureChannelTokenProvider(_Cred("tok-1"))
    tok = await provider.get_token("aud-1")
    assert tok == ChannelAccessToken(token="tok-1", audience="aud-1")
    await provider.aclose()
    assert closed is True

    with pytest.raises(RuntimeError, match="empty token"):
        await AzureChannelTokenProvider(_Cred("")).get_token("aud-1")

    class _WrongAudienceTokens(_TokenProvider):
        async def get_token(self, _audience: str) -> ChannelAccessToken:
            return ChannelAccessToken(token="tok", audience="wrong-audience")

    async with httpx.AsyncClient() as client:
        with pytest.raises(TeamsPublishError) as aud_err:
            await TeamsPublisher(http_client=client, tokens=_WrongAudienceTokens()).send(
                conversation_id="conv",
                service_url=SERVICE_URL,
                payload={"type": "message"},
            )
        assert aud_err.value.code == "identity_audience_mismatch"
        assert aud_err.value.ambiguous is False

    outcomes: list[httpx.Response | Exception] = [
        httpx.Response(500, json={"error": "fail"}),
        httpx.ConnectError("network down"),
        httpx.Response(200, content=b"x" * 8193),
        httpx.Response(200, content=b'{"id":"1","id":"2"}'),
        httpx.Response(200, content=b"[]"),
        httpx.Response(200, json={"id": ""}),
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        item = outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    expected_codes = [
        ("provider_rejected", False),
        ("transport_error", True),
        ("acknowledgement_too_large", True),
        ("invalid_acknowledgement", True),
        ("invalid_acknowledgement", True),
        ("invalid_acknowledgement", True),
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = TeamsPublisher(http_client=client, tokens=_TokenProvider())
        for expected_code, expected_ambiguous in expected_codes:
            with pytest.raises(TeamsPublishError) as pub_err:
                await publisher.send(
                    conversation_id="conv",
                    service_url=SERVICE_URL,
                    payload={"type": "message"},
                )
            assert pub_err.value.code == expected_code
            assert pub_err.value.ambiguous is expected_ambiguous
