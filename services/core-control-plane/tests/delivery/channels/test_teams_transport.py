"""Teams A3 service identity, endpoint, queue, and acknowledgement boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai.delivery.channels.teams_auth import (
    TeamsAuthenticationError,
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai.delivery.channels.teams_ingress import (
    TeamsIngressConfig,
    TeamsIngressError,
    TeamsIngressVerifier,
)
from fdai.delivery.channels.teams_transport import (
    TeamsConversationAdapter,
    TeamsEndpointRegistry,
    TeamsResponsePublisher,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryError,
    ConversationChannelKind,
    OutboundResponse,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

_NOW = datetime.now(tz=UTC)
_APPLICATION_ID = "bot-application-example"
_TENANT_ID = "tenant-example"
_SERVICE_URL = "https://smba.trafficmanager.net/example"
_KEY_ID = "key-example"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
_PUBLIC_JWK["kid"] = _KEY_ID


class _Jwks:
    def __init__(self, keys: list[dict[str, Any]] | None = None) -> None:
        self.keys = keys or [_PUBLIC_JWK]
        self.calls = 0

    async def get_keys(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.keys


def _token(
    *,
    audience: str = _APPLICATION_ID,
    issuer: str = "https://api.botframework.com",
    service_url: str = _SERVICE_URL,
    key_id: str = _KEY_ID,
    algorithm: str = "RS256",
    expires: datetime | None = None,
) -> str:
    return jwt.encode(
        {
            "aud": audience,
            "iss": issuer,
            "exp": expires or (_NOW + timedelta(minutes=5)),
            "nbf": _NOW - timedelta(seconds=5),
            "serviceurl": service_url,
        },
        _PRIVATE_KEY,
        algorithm=algorithm,
        headers={"kid": key_id},
    )


def _activity(
    *,
    service_url: str = _SERVICE_URL,
    sender: str = "aad-user-example",
    conversation_id: str = "conversation-example",
) -> bytes:
    return json.dumps(
        {
            "type": "message",
            "id": "activity-example",
            "channelId": "msteams",
            "serviceUrl": service_url,
            "conversation": {"id": conversation_id},
            "from": {"aadObjectId": sender},
            "channelData": {"tenant": {"id": _TENANT_ID}},
            "text": "Show the current incident state",
        },
        separators=(",", ":"),
    ).encode()


def _ingress(jwks: _Jwks | None = None) -> TeamsIngressVerifier:
    tokens = TeamsServiceTokenVerifier(
        config=TeamsTokenConfig(application_id=_APPLICATION_ID),
        jwks=jwks or _Jwks(),
    )
    return TeamsIngressVerifier(
        config=TeamsIngressConfig(
            tenant_id=_TENANT_ID,
            allowed_service_urls=frozenset({_SERVICE_URL}),
            principal_by_aad_object_id={"aad-user-example": "principal-example"},
        ),
        tokens=tokens,
    )


async def test_ingress_verifies_service_tenant_and_principal_before_turn() -> None:
    result = await _ingress().parse(
        body=_activity(),
        authorization="Bearer " + _token(),
        received_at=_NOW,
    )

    assert result.turn.channel_kind is ConversationChannelKind.TEAMS
    assert result.turn.sender_id == "aad-user-example"
    assert result.principal_id == "principal-example"
    assert result.service_url == _SERVICE_URL
    assert result.verification_ref == "teams-service-key:key-example"


@pytest.mark.parametrize(
    "token",
    [
        _token(audience="another-application"),
        _token(issuer="https://issuer.invalid"),
        _token(expires=_NOW - timedelta(minutes=10)),
        _token(key_id="unknown-key"),
    ],
)
async def test_service_token_verification_fails_closed(token: str) -> None:
    with pytest.raises(TeamsIngressError) as raised:
        await _ingress().parse(
            body=_activity(),
            authorization="Bearer " + token,
            received_at=_NOW,
        )

    assert raised.value.http_status == 401


async def test_token_algorithm_is_fixed_before_key_use() -> None:
    verifier = TeamsServiceTokenVerifier(
        config=TeamsTokenConfig(application_id=_APPLICATION_ID), jwks=_Jwks()
    )
    token = jwt.encode(
        {
            "aud": _APPLICATION_ID,
            "iss": "https://api.botframework.com",
            "exp": _NOW + timedelta(minutes=5),
            "nbf": _NOW - timedelta(seconds=5),
            "serviceurl": _SERVICE_URL,
        },
        "test-secret-with-at-least-thirty-two-bytes",  # noqa: S106
        algorithm="HS256",
        headers={"kid": _KEY_ID},
    )

    with pytest.raises(TeamsAuthenticationError, match="algorithm"):
        await verifier.verify("Bearer " + token)


async def test_service_url_must_match_token_activity_and_allowlist() -> None:
    with pytest.raises(TeamsIngressError, match="service URL") as raised:
        await _ingress().parse(
            body=_activity(service_url="https://evil.invalid"),
            authorization="Bearer " + _token(),
            received_at=_NOW,
        )

    assert raised.value.http_status == 403


async def test_tenant_and_sender_are_closed_mappings() -> None:
    activity = json.loads(_activity())
    activity["channelData"]["tenant"]["id"] = "another-tenant"
    with pytest.raises(TeamsIngressError) as tenant_error:
        await _ingress().parse(
            body=json.dumps(activity).encode(),
            authorization="Bearer " + _token(),
            received_at=_NOW,
        )
    assert tenant_error.value.http_status == 403

    with pytest.raises(TeamsIngressError) as sender_error:
        await _ingress().parse(
            body=_activity(sender="unknown-user"),
            authorization="Bearer " + _token(),
            received_at=_NOW,
        )
    assert sender_error.value.http_status == 403


async def test_file_attachment_discards_content_url() -> None:
    activity = json.loads(_activity())
    activity["text"] = "Inspect this file"
    activity["attachments"] = [
        {
            "contentType": "application/octet-stream",
            "name": "evidence.bin",
            "contentUrl": "https://evil.invalid/file",
            "content": {"uniqueId": "file-example", "fileSize": 8},
        }
    ]

    result = await _ingress().parse(
        body=json.dumps(activity).encode(),
        authorization="Bearer " + _token(),
        received_at=_NOW,
    )

    assert result.turn.attachments[0].source_ref == "teams-file:file-example"
    assert "evil" not in repr(result.turn.attachments)


def _publisher(
    client: httpx.AsyncClient,
    endpoints: TeamsEndpointRegistry,
) -> TeamsResponsePublisher:
    identity = StaticWorkloadIdentity(
        audience="https://api.botframework.com/.default",
        token="test-bot-token",  # noqa: S106
    )
    return TeamsResponsePublisher(
        http_client=client,
        identity=identity,
        endpoints=endpoints,
    )


def _response(*, edit_message_id: str | None = None) -> OutboundResponse:
    return OutboundResponse(
        channel_kind=ConversationChannelKind.TEAMS,
        channel_id="conversation-example",
        in_reply_to="activity-example",
        thread_id="conversation-example",
        status="verified",
        text="The incident is stable.",
        data={"execution_authority": False, "authority": "server_read_model"},
        evidence_refs=("evidence:incident-example",),
        edit_message_id=edit_message_id,
    )


async def test_adapter_registers_only_authenticated_endpoint_and_applies_queue_bound() -> None:
    endpoints = TeamsEndpointRegistry()
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        publisher = _publisher(client, endpoints)
        adapter = TeamsConversationAdapter(
            ingress=_ingress(),
            publisher=publisher,
            endpoints=endpoints,
            queue_capacity=1,
        )
        principal, verification = await adapter.accept(
            body=_activity(), authorization="Bearer " + _token(), received_at=_NOW
        )
        assert principal == "principal-example"
        assert verification.startswith("teams-service-key:")
        assert endpoints.resolve("conversation-example") == _SERVICE_URL
        with pytest.raises(TeamsIngressError, match="queue is full"):
            await adapter.accept(
                body=_activity(conversation_id="rejected-conversation"),
                authorization="Bearer " + _token(),
                received_at=_NOW,
            )
        assert endpoints.resolve("rejected-conversation") is None
        consumer = adapter.receive()
        assert (await anext(consumer)).message_id == "activity-example"
        await adapter.close()
        with pytest.raises(StopAsyncIteration):
            await anext(consumer)


async def test_publisher_uses_registry_endpoint_and_strict_acknowledgement() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "activity-response"})

    endpoints = TeamsEndpointRegistry()
    endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await _publisher(client, endpoints).send(_response())

    assert str(seen[0].url) == (_SERVICE_URL + "/v3/conversations/conversation-example/activities")
    assert seen[0].method == "POST"
    assert receipt.message_id == "activity-response"


async def test_publisher_uses_fixed_update_path_and_rejects_missing_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "activity-response"})

    endpoints = TeamsEndpointRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        publisher = _publisher(client, endpoints)
        with pytest.raises(ChannelDeliveryError, match="no authenticated"):
            await publisher.send(_response())
        endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
        await publisher.send(_response(edit_message_id="activity-original"))

    assert seen[0].method == "PUT"
    assert str(seen[0].url).endswith("/activities/activity-original")


@pytest.mark.parametrize(
    ("provider_response", "ambiguous"),
    [
        (httpx.Response(400, json={"error": "bad activity"}), False),
        (httpx.Response(302, headers={"location": "https://evil.invalid"}), False),
        (httpx.Response(201, content=b"not-json"), True),
        (httpx.Response(201, json={}), True),
    ],
)
async def test_publisher_classifies_acknowledgements(
    provider_response: httpx.Response,
    ambiguous: bool,
) -> None:
    endpoints = TeamsEndpointRegistry()
    endpoints.bind(conversation_id="conversation-example", service_url=_SERVICE_URL)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: provider_response)
    ) as client:
        with pytest.raises(ChannelDeliveryError) as raised:
            await _publisher(client, endpoints).send(_response())

    assert raised.value.acknowledgement_ambiguous is ambiguous
