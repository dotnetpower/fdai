"""No-network Azure read fencing and identity contract tests."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fdai.delivery.azure.alert_noise_http import AlertReadUnavailable, AzureAlertReader
from fdai.shared.providers.workload_identity import IdentityToken

PATH = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Insights/metricAlerts"
)


class Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken("test-token", datetime.now(UTC) + timedelta(minutes=5), audience)


async def test_reader_uses_only_token_value() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"value": [{"id": "test-resource"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await AzureAlertReader(http=http, identity=Identity()).list(
            PATH, api_version="2018-03-01"
        )
        assert result == ({"id": "test-resource"},)


@pytest.mark.parametrize(
    "link",
    [
        "https://example.com/collect?api-version=2018-03-01",
        "https://management.azure.com/subscriptions/other?api-version=2018-03-01",
        "https://management.azure.com" + PATH + "?api-version=other",
    ],
)
async def test_pagination_cannot_escape_scope(link: str) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"value": [], "nextLink": link})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(AlertReadUnavailable):
            await AzureAlertReader(http=http, identity=Identity()).list(
                PATH, api_version="2018-03-01"
            )
    assert len(calls) == 1


@pytest.mark.parametrize("status", [301, 401, 403, 429, 503])
async def test_provider_failure_has_no_retry_or_body(status: int) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, text="private-provider-body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(AlertReadUnavailable) as failure:
            await AzureAlertReader(http=http, identity=Identity()).list(
                PATH, api_version="2018-03-01"
            )
    assert "private-provider-body" not in str(failure.value)
    assert len(calls) == 1
