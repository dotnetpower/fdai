"""Bounded Azure subscription identity reader tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.subscription_scope import (
    AzureSubscriptionScopeConfig,
    AzureSubscriptionScopeReader,
)
from fdai.shared.providers.workload_identity import IdentityToken

SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"
OTHER_SUBSCRIPTION_ID = SUBSCRIPTION_ID[:-1] + "1"
NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="test-token",
            expires_at=NOW + timedelta(minutes=5),
            audience=audience,
        )


class _FailingIdentity(_Identity):
    async def get_token(self, audience: str) -> IdentityToken:
        raise RuntimeError("provider detail MUST NOT escape")


class _SlowIdentity(_Identity):
    async def get_token(self, audience: str) -> IdentityToken:
        await asyncio.sleep(1)
        return await super().get_token(audience)


async def _read(
    handler: httpx.MockTransport,
    *,
    identity: _Identity | None = None,
    timeout_seconds: float = 8.0,
) -> tuple[object, _Identity]:
    selected_identity = identity or _Identity()
    async with httpx.AsyncClient(transport=handler) as client:
        result = await AzureSubscriptionScopeReader(
            identity=selected_identity,
            http_client=client,
            config=AzureSubscriptionScopeConfig(
                subscription_id=SUBSCRIPTION_ID,
                timeout_seconds=timeout_seconds,
            ),
            now=lambda: NOW,
        ).read()
    return result, selected_identity


async def test_reader_returns_only_masked_configured_subscription_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": f"/subscriptions/{SUBSCRIPTION_ID}",
                "subscriptionId": SUBSCRIPTION_ID,
                "displayName": "Example subscription",
                "state": "Enabled",
            },
        )

    result, identity = await _read(httpx.MockTransport(handler))

    assert result.complete is True
    assert result.observation is not None
    assert result.observation.display_name == "Example subscription"
    assert result.observation.state == "Enabled"
    assert result.observation.masked_subscription_id == "0000...0000"
    assert result.observation.evidence_digest.startswith("sha256:")
    assert SUBSCRIPTION_ID not in result.observation.masked_subscription_id
    assert identity.audiences == ["https://management.azure.com/.default"]
    assert len(requests) == 1
    assert requests[0].url.path == f"/subscriptions/{SUBSCRIPTION_ID}"
    assert requests[0].url.params["api-version"] == "2022-12-01"
    assert requests[0].headers["Authorization"] == "Bearer test-token"
    assert requests[0].extensions["timeout"]["read"] == 8.0


@pytest.mark.parametrize(
    "status,payload,limitation",
    (
        (503, {}, "source_unavailable"),
        (
            200,
            {
                "id": f"/subscriptions/{OTHER_SUBSCRIPTION_ID}",
                "subscriptionId": OTHER_SUBSCRIPTION_ID,
                "displayName": "Wrong subscription",
                "state": "Enabled",
            },
            "source_response_invalid",
        ),
        (200, {"subscriptionId": SUBSCRIPTION_ID}, "source_response_invalid"),
        (
            200,
            {
                "id": f"/subscriptions/{SUBSCRIPTION_ID}",
                "subscriptionId": SUBSCRIPTION_ID,
                "displayName": "Injected\nname",
                "state": "Enabled",
            },
            "source_response_invalid",
        ),
        (
            200,
            {
                "id": f"/subscriptions/{SUBSCRIPTION_ID}",
                "subscriptionId": SUBSCRIPTION_ID,
                "displayName": "Example subscription",
                "state": "UnknownValue",
            },
            "source_response_invalid",
        ),
    ),
)
async def test_reader_fails_closed_without_generated_identity(
    status: int,
    payload: dict[str, object],
    limitation: str,
) -> None:
    result, _identity = await _read(
        httpx.MockTransport(lambda _request: httpx.Response(status, json=payload))
    )

    assert result.complete is False
    assert result.observation is None
    assert result.limitation == limitation


async def test_reader_reports_transport_failure_as_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    result, _identity = await _read(httpx.MockTransport(handler))

    assert result.complete is False
    assert result.observation is None
    assert result.limitation == "source_unavailable"


async def test_reader_reports_identity_failure_without_provider_detail() -> None:
    result, _identity = await _read(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        identity=_FailingIdentity(),
    )

    assert result.complete is False
    assert result.observation is None
    assert result.limitation == "source_unavailable"


async def test_reader_applies_one_deadline_to_identity_and_arm() -> None:
    result, _identity = await _read(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        identity=_SlowIdentity(),
        timeout_seconds=0.1,
    )

    assert result.complete is False
    assert result.observation is None
    assert result.limitation == "source_unavailable"


def test_config_rejects_untrusted_origin_and_noncanonical_subscription() -> None:
    with pytest.raises(ValueError, match="management origin"):
        AzureSubscriptionScopeConfig(
            subscription_id=SUBSCRIPTION_ID,
            endpoint="https://example.com",
        )
    with pytest.raises(ValueError, match="canonical UUID"):
        AzureSubscriptionScopeConfig(subscription_id="caller-selected")
