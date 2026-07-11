"""httpx-mocked tests for the Azure Monitor Logs query adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure.log_query import (
    AzureLogAnalyticsQueryConfig,
    AzureLogAnalyticsQueryProvider,
)
from fdai.shared.providers.observation import LogQueryError
from fdai.shared.providers.workload_identity import IdentityToken, WorkloadIdentity


class _StaticIdentity(WorkloadIdentity):
    def __init__(self, token: str = "test-token") -> None:  # noqa: S107 - fake token, not a secret
        self._token = token

    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token=self._token,
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


def _config(**overrides: object) -> AzureLogAnalyticsQueryConfig:
    base: dict[str, object] = dict(workspace_id="00000000-0000-0000-0000-000000000001")
    base.update(overrides)
    return AzureLogAnalyticsQueryConfig(**base)  # type: ignore[arg-type]


def _table(rows: list[list[object]], columns: list[str] | None = None) -> dict[str, object]:
    cols = columns or ["TimeGenerated", "Message"]
    return {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [{"name": c, "type": "string"} for c in cols],
                "rows": rows,
            }
        ]
    }


def _provider(
    handler, cfg: AzureLogAnalyticsQueryConfig | None = None
) -> AzureLogAnalyticsQueryProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AzureLogAnalyticsQueryProvider(
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
        {"workspace_id": ""},
        {"timeout_seconds": 0},
        {"max_rows_cap": 0},
    ],
)
def test_config_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _config(**overrides)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maps_rows_and_sends_timespan_and_auth() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=_table([["2026-07-07T12:00:00Z", "boot"], ["2026-07-07T12:01:00Z", "ready"]]),
        )

    provider = _provider(handler)
    result = await provider.query_log(query="AppEvents | take 2", window="PT1H")

    assert result.rows == (
        {"TimeGenerated": "2026-07-07T12:00:00Z", "Message": "boot"},
        {"TimeGenerated": "2026-07-07T12:01:00Z", "Message": "ready"},
    )
    assert result.truncated is False
    assert result.scanned_records == 2
    assert result.metadata["workspace_id"] == "00000000-0000-0000-0000-000000000001"

    body = json.loads(captured[0].content)
    assert body["query"] == "AppEvents | take 2"
    assert body["timespan"] == "PT1H"
    assert captured[0].headers["Authorization"] == "Bearer test-token"
    assert "/workspaces/00000000-0000-0000-0000-000000000001/query" in str(captured[0].url)


@pytest.mark.asyncio
async def test_empty_result_is_ok() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_table([]))

    provider = _provider(handler)
    result = await provider.query_log(query="X | take 1", window="PT1H")
    assert result.rows == ()
    assert result.truncated is False
    assert result.scanned_records == 0


# ---------------------------------------------------------------------------
# Bounds: max_rows clip + cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_rows_clips_and_flags_truncated() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_table([["t", str(i)] for i in range(5)]))

    provider = _provider(handler)
    result = await provider.query_log(query="X", window="PT1H", max_rows=2)
    assert len(result.rows) == 2
    assert result.truncated is True
    assert result.scanned_records == 5


@pytest.mark.asyncio
async def test_max_rows_cap_overrides_a_larger_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_table([["t", str(i)] for i in range(4)]))

    provider = _provider(handler, _config(max_rows_cap=2))
    result = await provider.query_log(query="X", window="PT1H", max_rows=100)
    assert len(result.rows) == 2
    assert result.truncated is True


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "window"),
    [("", "PT1H"), ("   ", "PT1H"), ("X", ""), ("X", " ")],
)
@pytest.mark.asyncio
async def test_empty_query_or_window_fails_closed(query: str, window: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unreached
        return httpx.Response(200, json=_table([]))

    provider = _provider(handler)
    with pytest.raises(LogQueryError):
        await provider.query_log(query=query, window=window)


# ---------------------------------------------------------------------------
# Fail-closed transport / shape paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_error_status_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="HTTP 403"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_transport_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="request failed"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_non_json_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="non-JSON"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_missing_tables_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "nope"})

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="missing 'tables'"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_malformed_table_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tables": [{"columns": "bad", "rows": []}]})

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="malformed"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_row_not_array_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"tables": [{"columns": [{"name": "c"}], "rows": ["not-a-list"]}]}
        )

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="row is not an array"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_row_column_length_mismatch_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_table([["only-one"]], columns=["a", "b"]))

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="length mismatch"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_unnamed_column_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"tables": [{"columns": [{"type": "string"}], "rows": [["v"]]}]}
        )

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="column metadata malformed"):
        await provider.query_log(query="X", window="PT1H")


@pytest.mark.asyncio
async def test_duplicate_column_names_fail_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tables": [
                    {"columns": [{"name": "a"}, {"name": "a"}], "rows": [["x", "y"]]}
                ]
            },
        )

    provider = _provider(handler)
    with pytest.raises(LogQueryError, match="duplicate column names"):
        await provider.query_log(query="X", window="PT1H")
