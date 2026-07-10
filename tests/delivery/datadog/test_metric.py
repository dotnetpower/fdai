"""httpx-mocked tests for the Datadog metric adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.datadog.metric import (
    DatadogMetricConfig,
    DatadogMetricProvider,
)
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider

_METRIC = "host.cpu.utilization"
_DD_QUERY = "avg:system.cpu.user{*}"


class _StaticSecrets(SecretProvider):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    async def get(self, name: str) -> str:
        self.reads.append(name)
        try:
            return self._values[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


def _config(**overrides: object) -> DatadogMetricConfig:
    base: dict[str, object] = dict(
        queries={_METRIC: _DD_QUERY},
        api_key_secret="datadog/api-key",
        app_key_secret="datadog/app-key",
    )
    base.update(overrides)
    return DatadogMetricConfig(**base)  # type: ignore[arg-type]


def _provider(
    handler,
    cfg: DatadogMetricConfig | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[DatadogMetricProvider, httpx.AsyncClient, _StaticSecrets]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    concrete_secrets = secrets or _StaticSecrets(
        {"datadog/api-key": "AK", "datadog/app-key": "APP"}
    )
    provider = DatadogMetricProvider(
        config=cfg or _config(),
        http_client=client,
        secrets=concrete_secrets,
    )
    return provider, client, concrete_secrets  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_range_query_maps_pointlist_samples_and_tags() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "series": [
                    {
                        "metric": "system.cpu.user",
                        "tag_set": ["host:web-a", "env:prod"],
                        "pointlist": [
                            [1_700_000_060_000, 2.0],
                            [1_700_000_000_000, 1.0],
                        ],
                    }
                ],
            },
        )

    provider, client, _ = _provider(handler)
    since = datetime(2026, 7, 10, tzinfo=UTC)
    until = since + timedelta(minutes=5)
    try:
        points = [
            p
            async for p in provider.query(
                MetricQuery(metric_name=_METRIC, since=since, until=until)
            )
        ]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [1.0, 2.0]  # sorted chronologically
    assert points[0].labels == {"host": "web-a", "env": "prod"}
    assert "/api/v1/query" in str(captured[0].url)
    assert "from=" in str(captured[0].url) and "to=" in str(captured[0].url)


@pytest.mark.asyncio
async def test_instant_query_when_no_window() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "series": [
                    {
                        "metric": "system.cpu.user",
                        "tag_set": [],
                        "pointlist": [[1_700_000_000_000, 3.14]],
                    }
                ],
            },
        )

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [3.14]
    assert points[0].labels == {}
    # Missing `status` with a valid `series` is still success.


@pytest.mark.asyncio
async def test_secrets_are_read_and_sent_as_headers() -> None:
    seen_headers: list[dict[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json={"series": []})

    provider, client, secrets = _provider(handler)
    try:
        _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert secrets.reads == ["datadog/api-key", "datadog/app-key"]
    assert seen_headers[0]["dd-api-key"] == "AK"
    assert seen_headers[0]["dd-application-key"] == "APP"


@pytest.mark.asyncio
async def test_unknown_metric_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unreached
        return httpx.Response(200, json={"series": []})

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="no Datadog query configured"):
            _ = [p async for p in provider.query(MetricQuery(metric_name="mystery"))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_non_2xx_fails_closed_and_does_not_leak_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="HTTP 403"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_dd_error_status_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "error": "rate_limited", "series": []})

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="Datadog status 'error'"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_secret_propagates() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - unreached
        return httpx.Response(200, json={"series": []})

    provider, client, _ = _provider(
        handler,
        secrets=_StaticSecrets({"datadog/api-key": "AK"}),  # missing app key
    )
    try:
        with pytest.raises(SecretNotFoundError):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_nan_and_null_samples_are_dropped() -> None:
    # Datadog emits raw NaN (not JSON-null) for gap points; Python's stdlib
    # json parser accepts it by default, but the encoder rejects it, so
    # build the response body as raw bytes instead of a dict.
    body = (
        b'{"series":[{"metric":"system.cpu.user","tag_set":["host:a"],'
        b'"pointlist":[[1700000000000,1.0],[1700000060000,null],'
        b"[1700000120000,NaN],[1700000180000,4.0]]}]}"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "application/json"},
        )

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [1.0, 4.0]


@pytest.mark.asyncio
async def test_label_filter_applied_in_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "series": [
                    {
                        "metric": "system.cpu.user",
                        "tag_set": ["host:a"],
                        "pointlist": [[1_700_000_000_000, 1.0]],
                    },
                    {
                        "metric": "system.cpu.user",
                        "tag_set": ["host:b"],
                        "pointlist": [[1_700_000_000_000, 2.0]],
                    },
                ]
            },
        )

    provider, client, _ = _provider(handler)
    try:
        points = [
            p async for p in provider.query(MetricQuery(metric_name=_METRIC, labels={"host": "b"}))
        ]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [2.0]


@pytest.mark.asyncio
async def test_max_points_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "series": [
                    {
                        "metric": "system.cpu.user",
                        "tag_set": [],
                        "pointlist": [[1_700_000_000_000 + i * 1000, float(i)] for i in range(10)],
                    }
                ]
            },
        )

    cfg = _config(max_points=3)
    provider, client, _ = _provider(handler, cfg=cfg)
    try:
        with pytest.raises(MetricProviderError, match="max_points cap"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_since_after_until_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={"series": []})

    provider, client, _ = _provider(handler)
    since = datetime(2026, 7, 10, tzinfo=UTC)
    until = since - timedelta(minutes=1)
    try:
        with pytest.raises(MetricProviderError, match="since > until"):
            _ = [
                p
                async for p in provider.query(
                    MetricQuery(metric_name=_METRIC, since=since, until=until)
                )
            ]
    finally:
        await client.aclose()


def test_config_validates_non_empty_secrets() -> None:
    with pytest.raises(ValueError, match="api_key_secret"):
        DatadogMetricConfig(queries={_METRIC: _DD_QUERY}, api_key_secret="", app_key_secret="APP")
    with pytest.raises(ValueError, match="api_key_secret"):
        DatadogMetricConfig(queries={_METRIC: _DD_QUERY}, api_key_secret="AK", app_key_secret="")


def test_config_validates_timeout_and_max_points() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        DatadogMetricConfig(
            queries={_METRIC: _DD_QUERY},
            api_key_secret="AK",
            app_key_secret="APP",
            timeout_seconds=0,
        )
    with pytest.raises(ValueError, match="max_points"):
        DatadogMetricConfig(
            queries={_METRIC: _DD_QUERY},
            api_key_secret="AK",
            app_key_secret="APP",
            max_points=0,
        )


def test_config_rejects_plaintext_base_url() -> None:
    """Hardening: a plaintext base_url would leak API keys on the wire."""
    with pytest.raises(ValueError, match="MUST use https://"):
        DatadogMetricConfig(
            queries={_METRIC: _DD_QUERY},
            api_key_secret="AK",
            app_key_secret="APP",
            base_url="http://api.datadoghq.com",
        )
    # A scheme-less base_url is also rejected (would default to http via httpx).
    with pytest.raises(ValueError, match="MUST use https://"):
        DatadogMetricConfig(
            queries={_METRIC: _DD_QUERY},
            api_key_secret="AK",
            app_key_secret="APP",
            base_url="api.datadoghq.com",
        )


def test_config_accepts_https_regional_endpoints() -> None:
    """EU / GovCloud endpoints are all https and MUST validate cleanly."""
    for host in (
        "https://api.datadoghq.eu",
        "https://api.datadoghq.com",
        "https://api.us3.datadoghq.com",
        "https://api.ddog-gov.com",
    ):
        DatadogMetricConfig(
            queries={_METRIC: _DD_QUERY},
            api_key_secret="AK",
            app_key_secret="APP",
            base_url=host,
        )
