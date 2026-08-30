"""Focused security checks for Operator-owned Teams ingress."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fdai_operator_service.families.conversation.channel_delivery_models import ChannelKind
from fdai_operator_service.families.conversation.channel_edge.teams_auth import (
    TeamsAuthenticationError,
    TeamsServiceTokenVerifier,
    TeamsTokenConfig,
)
from fdai_operator_service.families.conversation.channel_edge.teams_ingress import (
    TeamsIngressConfig,
    TeamsIngressError,
    TeamsIngressVerifier,
)

_NOW = datetime.now(tz=UTC)
_APPLICATION_ID = "bot-application-example"
_TENANT_ID = "tenant-example"
_SERVICE_URL = "https://smba.trafficmanager.net/example"
_KEY_ID = "key-example"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
_PUBLIC_JWK["kid"] = _KEY_ID
_ROTATED_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ROTATED_JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_ROTATED_KEY.public_key()))
_ROTATED_JWK["kid"] = "rotated-key"


class _Jwks:
    def __init__(self, keys: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.keys = keys or [_PUBLIC_JWK]
        self.calls = 0

    async def get_keys(self) -> Sequence[Mapping[str, Any]]:
        self.calls += 1
        return self.keys


def _token(
    *,
    audience: str = _APPLICATION_ID,
    issuer: str = "https://api.botframework.com",
    service_url: str = _SERVICE_URL,
    key_id: str = _KEY_ID,
    expires: datetime | None = None,
) -> str:
    issued_at = datetime.now(tz=UTC)
    return jwt.encode(
        {
            "aud": audience,
            "iss": issuer,
            "exp": expires or (issued_at + timedelta(minutes=5)),
            "nbf": issued_at - timedelta(seconds=5),
            "serviceurl": service_url,
        },
        _PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _activity(
    *,
    service_url: str = _SERVICE_URL,
    sender: str = "aad-user-example",
    tenant: str = _TENANT_ID,
) -> bytes:
    return json.dumps(
        {
            "type": "message",
            "id": "activity-example",
            "channelId": "msteams",
            "serviceUrl": service_url,
            "conversation": {"id": "conversation-example"},
            "from": {"aadObjectId": sender},
            "channelData": {"tenant": {"id": tenant}},
            "text": "Show the current incident state",
        },
        separators=(",", ":"),
    ).encode()


def _ingress(jwks: _Jwks | None = None) -> TeamsIngressVerifier:
    return TeamsIngressVerifier(
        config=TeamsIngressConfig(
            tenant_id=_TENANT_ID,
            allowed_service_urls=frozenset({_SERVICE_URL}),
            principal_by_aad_object_id={"aad-user-example": "principal-example"},
        ),
        tokens=TeamsServiceTokenVerifier(
            config=TeamsTokenConfig(application_id=_APPLICATION_ID),
            jwks=jwks or _Jwks(),
        ),
    )


async def test_teams_ingress_verifies_service_tenant_and_principal() -> None:
    result = await _ingress().parse(
        body=_activity(), authorization="Bearer " + _token(), received_at=_NOW
    )
    assert result.turn.channel_kind is ChannelKind.TEAMS
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
    ids=("wrong-audience", "wrong-issuer", "expired", "unknown-key"),
)
async def test_teams_service_token_verification_fails_closed(token: str) -> None:
    with pytest.raises(TeamsIngressError) as error:
        await _ingress().parse(body=_activity(), authorization="Bearer " + token, received_at=_NOW)
    assert error.value.http_status == 401


async def test_teams_token_algorithm_is_fixed_before_key_use() -> None:
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


async def test_teams_token_refreshes_known_key_after_bounded_ttl() -> None:
    jwks = _Jwks()
    current = [0.0]
    verifier = TeamsServiceTokenVerifier(
        config=TeamsTokenConfig(
            application_id=_APPLICATION_ID,
            jwks_cache_ttl=timedelta(seconds=1),
        ),
        jwks=jwks,
        clock=lambda: current[0],
    )
    await verifier.verify("Bearer " + _token())
    jwks.keys = [_ROTATED_JWK]
    current[0] = 2.0

    with pytest.raises(TeamsAuthenticationError, match="key id is unknown"):
        await verifier.verify("Bearer " + _token())

    assert jwks.calls == 2


@pytest.mark.parametrize(
    "body",
    [
        _activity(service_url="https://evil.invalid"),
        _activity(tenant="another-tenant"),
        _activity(sender="unknown-user"),
    ],
)
async def test_teams_service_url_tenant_and_sender_are_closed(body: bytes) -> None:
    with pytest.raises(TeamsIngressError) as error:
        await _ingress().parse(body=body, authorization="Bearer " + _token(), received_at=_NOW)
    assert error.value.http_status == 403


async def test_teams_file_attachment_discards_content_url() -> None:
    activity = json.loads(_activity())
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


async def test_teams_ingress_rejects_duplicate_json_keys_and_malformed_service_url() -> None:
    duplicate = b'{"type":"message","type":"invoke"}'
    with pytest.raises(TeamsIngressError) as duplicate_error:
        await _ingress().parse(
            body=duplicate,
            authorization="Bearer " + _token(),
            received_at=_NOW,
        )
    assert duplicate_error.value.code == "invalid_json"

    with pytest.raises(TeamsIngressError) as url_error:
        await _ingress().parse(
            body=_activity(service_url="not-a-url"),
            authorization="Bearer " + _token(service_url="not-a-url"),
            received_at=_NOW,
        )
    assert url_error.value.code == "invalid_service_url"
