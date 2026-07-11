"""httpx-mocked tests for the Azure Resource Graph deployment-history adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.deployment_history import (
    AzureDeploymentHistoryConfig,
    AzureResourceGraphDeploymentHistory,
)
from fdai.shared.providers.observation import DeploymentHistoryError
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity

_KQL = (
    "resourcechanges "
    "| extend ts=todatetime(properties.changeAttributes.timestamp) "
    "| where ts >= ago({window_seconds}s) "
    "| project deployment_ref=tostring(properties.changeAttributes.correlationId), "
    "timestamp=tostring(ts), resource_ref=tostring(properties.targetResourceId), "
    "status=tostring(properties.changeType), author=tostring(properties.changeAttributes.changedBy)"
)


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _config(**overrides: object) -> AzureDeploymentHistoryConfig:
    base: dict[str, object] = dict(
        subscription_scopes=("00000000-0000-0000-0000-000000000001",),
        kql_template=_KQL,
    )
    base.update(overrides)
    return AzureDeploymentHistoryConfig(**base)  # type: ignore[arg-type]


def _row(
    *,
    deployment_ref: str = "corr-1",
    timestamp: str = "2026-07-07T11:59:00Z",
    resource_ref: str = "/subscriptions/s/rg/r/app",
    status: str = "Update",
    author: str = "ci@example.com",
) -> dict[str, object]:
    return {
        "deployment_ref": deployment_ref,
        "timestamp": timestamp,
        "resource_ref": resource_ref,
        "status": status,
        "author": author,
    }


def _provider(
    handler, cfg: AzureDeploymentHistoryConfig | None = None
) -> AzureResourceGraphDeploymentHistory:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AzureResourceGraphDeploymentHistory(
        config=cfg or _config(),
        identity=_StaticIdentity(),
        http_client=client,
    )


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"subscription_scopes": ()},
        {"kql_template": "resourcechanges | project x"},  # no {window_seconds}
        {"page_size": 0},
        {"page_size": 1001},
        {"max_pages": 0},
        {"max_records": 0},
        {"timeout_seconds": 0},
        {"deployment_ref_column": ""},
        {"timestamp_column": ""},
        {"resource_ref_column": ""},
        {"status_column": ""},
        {"author_column": ""},
    ],
)
def test_config_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _config(**overrides)


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("window", "expected_seconds"),
    [
        ("PT1H", 3600),
        ("P1D", 86400),
        ("P7D", 604800),
        ("PT30M", 1800),
        ("PT1H30M", 5400),
        ("P1DT2H", 93600),
        ("P1W", 604800),
        ("PT45S", 45),
    ],
)
@pytest.mark.asyncio
async def test_window_parses_and_substitutes(window: str, expected_seconds: int) -> None:
    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"data": []})

    provider = _provider(handler)
    await provider.query_deployments(window=window)
    assert f"ago({expected_seconds}s)" in captured[0]
    assert "{window_seconds}" not in captured[0]


@pytest.mark.parametrize("window", ["pt1h", "p1d", " PT1H ", "p1dt2h"])
@pytest.mark.asyncio
async def test_window_parsing_is_case_insensitive(window: str) -> None:
    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"data": []})

    provider = _provider(handler)
    await provider.query_deployments(window=window)
    # Lowercase / whitespace-padded durations parse to a numeric ago() bound.
    assert "{window_seconds}" not in captured[0]
    assert "ago(" in captured[0]


@pytest.mark.parametrize("window", ["", "1h", "P", "PT", "24", "PxY", "PT0S", "P0D"])
@pytest.mark.asyncio
async def test_window_rejects_bad_input(window: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unreached
        return httpx.Response(200, json={"data": []})

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError):
        await provider.query_deployments(window=window)


# ---------------------------------------------------------------------------
# Happy path + mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maps_rows_to_deployment_records() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"data": [_row(), _row(deployment_ref="corr-2")]})

    provider = _provider(handler)
    result = await provider.query_deployments(window="PT1H")
    assert result.window == "PT1H"
    assert len(result.records) == 2
    rec = result.records[0]
    assert rec.deployment_ref == "corr-1"
    assert rec.timestamp == "2026-07-07T11:59:00Z"
    assert rec.author == "ci@example.com"
    assert rec.resource_refs == ("/subscriptions/s/rg/r/app",)
    assert rec.status == "Update"


@pytest.mark.asyncio
async def test_optional_author_defaults_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        row = _row()
        del row["author"]
        return httpx.Response(200, json={"data": [row]})

    provider = _provider(handler)
    result = await provider.query_deployments(window="PT1H")
    assert result.records[0].author == ""


# ---------------------------------------------------------------------------
# resource_ref filter (in-memory, injection-safe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_ref_filters_in_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    _row(resource_ref="/rg/app"),
                    _row(deployment_ref="corr-2", resource_ref="/rg/db"),
                ]
            },
        )

    provider = _provider(handler)
    result = await provider.query_deployments(window="PT1H", resource_ref="/rg/db")
    assert len(result.records) == 1
    assert result.records[0].resource_refs == ("/rg/db",)


@pytest.mark.asyncio
async def test_untrusted_resource_ref_is_not_interpolated_into_query() -> None:
    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content)["query"])
        return httpx.Response(200, json={"data": []})

    provider = _provider(handler)
    # A hostile resource_ref must never reach the Kusto query text.
    await provider.query_deployments(window="PT1H", resource_ref="' | union hack //")
    assert "hack" not in captured[0]
    assert "union" not in captured[0]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_follows_skip_token() -> None:
    pages = [
        {"data": [_row(deployment_ref="corr-1")], "$skipToken": "tok-1"},
        {"data": [_row(deployment_ref="corr-2")]},
    ]
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls["n"] == 1:
            assert body["options"]["$skipToken"] == "tok-1"
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    provider = _provider(handler)
    result = await provider.query_deployments(window="PT1H")
    assert {r.deployment_ref for r in result.records} == {"corr-1", "corr-2"}


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_error_status_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError, match="HTTP 403"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_transport_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError, match="request failed"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_non_json_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError, match="non-JSON"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_missing_data_array_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"count": 0})

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError, match="missing 'data'"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_missing_required_column_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        row = _row()
        del row["resource_ref"]
        return httpx.Response(200, json={"data": [row]})

    provider = _provider(handler)
    with pytest.raises(DeploymentHistoryError, match="required column"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_max_records_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [_row(), _row(), _row()]})

    provider = _provider(handler, _config(max_records=2))
    with pytest.raises(DeploymentHistoryError, match="more than 2"):
        await provider.query_deployments(window="PT1H")


@pytest.mark.asyncio
async def test_max_pages_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # Always returns a skip token -> never terminates on its own.
        return httpx.Response(200, json={"data": [_row()], "$skipToken": "loop"})

    provider = _provider(handler, _config(max_pages=2))
    with pytest.raises(DeploymentHistoryError, match="max_pages"):
        await provider.query_deployments(window="PT1H")
