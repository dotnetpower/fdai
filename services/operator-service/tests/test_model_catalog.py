"""Settings discovery is bounded, account-scoped, cached, and read-only."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
from fdai_operator_service.adapters.model_catalog import AzureModelCatalogReader
from fdai_operator_service.postgres_family_store import PostgresFamilyStore
from fdai_operator_service.postgres_iam import PostgresIamAdapters

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_ACCOUNT = (
    f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/"
    "providers/Microsoft.CognitiveServices/accounts/model-example"
)
_MODEL = {"format": "OpenAI", "name": "gpt-example", "version": "1"}


def _response(path: str) -> dict[str, object]:
    if path.endswith("/accounts"):
        rows = [
            {
                "id": _ACCOUNT,
                "location": "exampleregion",
                "properties": {"endpoint": "https://models.example.com/"},
            }
        ]
    elif path.endswith("/models"):
        rows = [
            {
                **_MODEL,
                "lifecycleStatus": "GenerallyAvailable",
                "skus": [
                    {
                        "name": "GlobalStandard",
                        "usageName": "OpenAI.GlobalStandard.gpt-example",
                    }
                ],
            }
        ]
    elif path.endswith("/deployments"):
        rows = [
            {
                "name": "example-deployment",
                "properties": {"model": _MODEL, "provisioningState": "Succeeded"},
            }
        ]
    elif path.endswith("/usages"):
        rows = [
            {
                "name": {"value": "OpenAI.GlobalStandard.gpt-example"},
                "currentValue": 3,
                "limit": 10,
            }
        ]
    else:
        raise AssertionError("Unexpected provider path")
    return {"value": rows}


async def _token() -> str:
    return "synthetic"


def _reader(handler, **kwargs) -> AzureModelCatalogReader:
    return AzureModelCatalogReader(
        subscription_id=_SUBSCRIPTION,
        endpoint="https://models.example.com",
        token_provider=_token,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_catalog_joins_only_observed_models_deployments_and_quota() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response(request.url.path))

    result = await _reader(handler).read()
    assert result["available"] is True
    assert result["region"] == "exampleregion"
    model = result["models"][0]
    assert model["deployments"] == ["example-deployment"]
    assert model["status"] == "deployed"
    assert model["available_tpm"] == 7000
    assert len(requests) == 4
    assert all(r.method == "GET" and r.url.host == "management.azure.com" for r in requests)
    assert _SUBSCRIPTION not in str(result)
    assert "models.example.com" not in str(result)


async def test_cache_is_bounded_and_explicit_refresh_does_not_get_ignored() -> None:
    calls = 0
    now = 0.0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response(request.url.path))

    reader = _reader(handler, clock=lambda: now)
    first = await reader.read()
    first["models"].clear()
    assert (await reader.read())["models"]
    assert calls == 4
    await reader.read(refresh=True)
    assert calls == 8
    now = 61
    await reader.read()
    assert calls == 12


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_provider_failure_is_unavailable_and_never_retried(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    reader = _reader(handler)
    result = await reader.read()
    assert result["available"] is False
    assert result["models"] == []
    assert result["unavailable_reason"] == f"catalog_http_{status}"
    await reader.read()
    assert calls == 1


@pytest.mark.parametrize(
    "bad_link",
    [
        "https://untrusted.example.com/next",
        f"https://management.azure.com{_ACCOUNT}/deployments?api-version=2024-10-01",
        f"https://management.azure.com/subscriptions/{_SUBSCRIPTION}/providers/Microsoft.CognitiveServices/accounts?api-version=2024-10-01",
    ],
)
async def test_pagination_never_sends_credentials_to_another_scope(bad_link: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"value": [], "nextLink": bad_link})

    result = await _reader(handler).read()
    assert result["available"] is False
    assert result["unavailable_reason"] == "catalog_pagination_invalid"
    assert calls == 1


@pytest.mark.parametrize("variant", ["absent", "ambiguous", "foreign"])
async def test_account_binding_requires_exactly_one_account_in_configured_subscription(
    variant: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = _response(request.url.path)
        if variant == "absent":
            data["value"] = []
        elif variant == "ambiguous":
            data["value"] *= 2
        else:
            data["value"][0]["id"] = _ACCOUNT.replace(_SUBSCRIPTION, "foreign")
        return httpx.Response(200, json=data)

    assert (await _reader(handler).read())["available"] is False


async def test_refresh_failure_clears_availability_and_cancellation_propagates() -> None:
    fail = False

    def handler(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(503) if fail else httpx.Response(200, json=_response(request.url.path))
        )

    reader = _reader(handler)
    assert (await reader.read())["available"] is True
    fail = True
    assert (await reader.read(refresh=True))["available"] is False

    async def cancelled_token() -> str:
        raise asyncio.CancelledError

    reader = AzureModelCatalogReader(
        subscription_id=_SUBSCRIPTION,
        endpoint="https://models.example.com",
        token_provider=cancelled_token,
    )
    with pytest.raises(asyncio.CancelledError):
        await reader.read()


async def test_settings_projection_forwards_refresh_without_changing_policy() -> None:
    class Store:
        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            assert family == "iam" and operation == "model-settings"
            return {
                "environment": "dev",
                "web_search": {},
                "model_catalog": {"available": False},
            }

        async def read_state(self, key: str) -> dict[str, object] | None:
            return None

    class Catalog:
        refreshes: list[bool] = []

        async def read(self, *, refresh: bool = False) -> Mapping[str, object]:
            self.refreshes.append(refresh)
            return {"available": True, "models": []}

    catalog = Catalog()
    adapter = PostgresIamAdapters(cast(PostgresFamilyStore, Store()), model_catalog=catalog)
    result = await adapter.projection("example-principal", refresh_model_catalog=True)
    assert result["model_catalog"] == {"available": True, "models": []}
    assert catalog.refreshes == [True]
    assert result["binding_policy"]["execution_authority"] is False


@pytest.mark.parametrize("variant", ["bytes", "rows", "shape", "row", "pages"])
async def test_provider_payloads_cannot_exceed_discovery_bounds(variant: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if variant == "bytes":
            return httpx.Response(200, content=b"x" * 4_194_305)
        if variant == "rows":
            return httpx.Response(200, json={"value": [{}] * 5001})
        if variant == "shape":
            return httpx.Response(200, json=[])
        if variant == "row":
            return httpx.Response(200, json={"value": [None]})
        return httpx.Response(
            200,
            json={
                "value": [],
                "nextLink": str(request.url.copy_set_param("page", str(calls))),
            },
        )

    result = await _reader(handler).read()
    assert result["available"] is False
    assert result["models"] == []
    assert calls == (5 if variant == "pages" else 1)


async def test_refresh_timeout_never_returns_previously_available_data() -> None:
    timeout = False
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if timeout:
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(200, json=_response(request.url.path))

    reader = _reader(handler)
    assert (await reader.read())["available"] is True
    timeout = True
    failed = await reader.read(refresh=True)
    assert failed["available"] is False
    assert failed["models"] == []
    assert (await reader.read()) == failed
    assert calls == 5
