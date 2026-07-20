"""Bot Framework JWT and same-tenant Teams principal binding tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.delivery.channels.routes import make_teams_activity_route
from fdai.delivery.channels.teams import TeamsBotChannel
from fdai.delivery.channels.teams_auth import (
    BotFrameworkJwtAuthenticator,
    BotServiceIdentity,
    TeamsAuthConfigError,
    TeamsAuthenticationError,
    TeamsPrincipalResolver,
)
from fdai.shared.providers.conversation_channel import (
    ChannelDeliveryOperation,
    ChannelDeliveryReceipt,
    ConversationChannelKind,
    OutboundResponse,
)

_APP_ID = "00000000-0000-0000-0000-000000000001"
_TENANT_ID = "00000000-0000-0000-0000-000000000002"
_OBJECT_ID = "00000000-0000-0000-0000-000000000003"
_ISSUER = "https://api.botframework.com"
_SERVICE_URL = "https://smba.trafficmanager.net/amer/"


class _FakeJwk:
    def __init__(self, key: Any) -> None:
        self.key = key


class _FakeJwksClient:
    def __init__(self, key: Any) -> None:
        self._key = _FakeJwk(key)

    def get_signing_key_from_jwt(self, _token: str) -> _FakeJwk:
        return self._key


class _Publisher:
    async def publish(self, response: OutboundResponse) -> ChannelDeliveryReceipt:
        return ChannelDeliveryReceipt(
            channel_kind=ConversationChannelKind.TEAMS,
            channel_id=response.channel_id,
            operation=ChannelDeliveryOperation.POST,
            message_id="activity-reply-example",
        )


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _authenticator(key: rsa.RSAPrivateKey) -> BotFrameworkJwtAuthenticator:
    return BotFrameworkJwtAuthenticator(
        jwks_client=_FakeJwksClient(key.public_key()),  # type: ignore[arg-type]
        app_id=_APP_ID,
    )


def _token(
    key: rsa.RSAPrivateKey,
    *,
    audience: str = _APP_ID,
    issuer: str = _ISSUER,
    service_url: str = _SERVICE_URL,
    expires: timedelta = timedelta(minutes=10),
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": audience,
            "iss": issuer,
            "exp": now + expires,
            "nbf": now - timedelta(minutes=1),
            "serviceurl": service_url,
        },
        key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def _activity(
    *,
    service_url: str = _SERVICE_URL,
    tenant_id: str = _TENANT_ID,
) -> dict[str, object]:
    return {
        "type": "message",
        "id": "activity-1",
        "channelId": "msteams",
        "serviceUrl": service_url,
        "text": "query_audit",
        "from": {"id": "vendor-user", "aadObjectId": _OBJECT_ID},
        "conversation": {"id": "conversation-1", "tenantId": tenant_id},
    }


def test_genuine_service_jwt_returns_bound_identity(rsa_key: rsa.RSAPrivateKey) -> None:
    identity = _authenticator(rsa_key)._verify(_token(rsa_key))

    assert identity == BotServiceIdentity(service_url=_SERVICE_URL.rstrip("/"))


@pytest.mark.parametrize(
    "token",
    (
        "wrong-audience",
        "wrong-issuer",
        "expired",
    ),
)
def test_invalid_service_jwt_is_rejected(
    rsa_key: rsa.RSAPrivateKey,
    token: str,
) -> None:
    values = {
        "wrong-audience": _token(rsa_key, audience="other-app"),
        "wrong-issuer": _token(rsa_key, issuer="https://example.com"),
        "expired": _token(rsa_key, expires=timedelta(minutes=-5)),
    }

    with pytest.raises(TeamsAuthenticationError):
        _authenticator(rsa_key)._verify(values[token])


def test_route_rejects_service_url_and_principal_mismatch(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    channel = TeamsBotChannel(publisher=_Publisher())
    resolver = TeamsPrincipalResolver(
        tenant_id=_TENANT_ID,
        principal_bindings={_OBJECT_ID: "operator-1"},
    )
    client = TestClient(
        Starlette(
            routes=[
                make_teams_activity_route(
                    channel=channel,
                    authenticate=_authenticator(rsa_key),
                    resolve_principal=resolver,
                )
            ]
        )
    )
    headers = {"Authorization": f"Bearer {_token(rsa_key)}"}

    service_mismatch = client.post(
        "/channels/teams/activities",
        json=_activity(service_url="https://other.example.com/"),
        headers=headers,
    )
    tenant_mismatch = client.post(
        "/channels/teams/activities",
        json=_activity(tenant_id="other-tenant"),
        headers=headers,
    )

    assert service_mismatch.status_code == 401
    assert tenant_mismatch.status_code == 403


async def test_route_keeps_vendor_sender_separate_from_canonical_principal(
    rsa_key: rsa.RSAPrivateKey,
) -> None:
    channel = TeamsBotChannel(publisher=_Publisher())
    resolver = TeamsPrincipalResolver(
        tenant_id=_TENANT_ID,
        principal_bindings={_OBJECT_ID: "operator-1"},
    )
    client = TestClient(
        Starlette(
            routes=[
                make_teams_activity_route(
                    channel=channel,
                    authenticate=_authenticator(rsa_key),
                    resolve_principal=resolver,
                )
            ]
        )
    )

    response = client.post(
        "/channels/teams/activities",
        json=_activity(),
        headers={"Authorization": f"Bearer {_token(rsa_key)}"},
    )
    turn = await anext(channel.receive())

    assert response.status_code == 202
    assert turn.sender_id == _OBJECT_ID
    assert turn.metadata["verified_principal_id"] == "operator-1"
    assert turn.sender_id != turn.metadata["verified_principal_id"]


def test_auth_and_principal_resolver_load_strict_environment() -> None:
    auth = BotFrameworkJwtAuthenticator.from_env({"FDAI_TEAMS_BOT_APP_ID": _APP_ID})
    resolver = TeamsPrincipalResolver.from_env(
        {
            "FDAI_TEAMS_TENANT_ID": _TENANT_ID,
            "FDAI_TEAMS_PRINCIPAL_BINDINGS_JSON": (
                '{"00000000-0000-0000-0000-000000000003":"operator-1"}'
            ),
        }
    )

    assert auth.app_id == _APP_ID
    assert resolver.principal_bindings[_OBJECT_ID] == "operator-1"


def test_principal_resolver_rejects_malformed_or_unbounded_environment() -> None:
    with pytest.raises(TeamsAuthConfigError):
        TeamsPrincipalResolver.from_env(
            {
                "FDAI_TEAMS_TENANT_ID": _TENANT_ID,
                "FDAI_TEAMS_PRINCIPAL_BINDINGS_JSON": "[]",
            }
        )
    oversized = {f"oid-{index}": f"principal-{index}" for index in range(1001)}
    with pytest.raises(TeamsAuthConfigError, match="bounded"):
        TeamsPrincipalResolver.from_env(
            {
                "FDAI_TEAMS_TENANT_ID": _TENANT_ID,
                "FDAI_TEAMS_PRINCIPAL_BINDINGS_JSON": json.dumps(oversized),
            }
        )
