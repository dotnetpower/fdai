"""httpx-mocked tests for the Splunk metric adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.splunk.metric import (
    SplunkMetricConfig,
    SplunkMetricProvider,
)
from fdai.shared.providers.metric import MetricProviderError, MetricQuery
from fdai.shared.providers.secret_provider import SecretNotFoundError, SecretProvider

_METRIC = "host.cpu.utilization"
_SEARCH = "| mstats avg(cpu.user) as value by host"
_EXPORT = "/services/search/jobs/export"


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


def _config(**overrides: object) -> SplunkMetricConfig:
    base: dict[str, object] = dict(
        base_url="https://splunk.local:8089",
        searches={_METRIC: _SEARCH},
        token_secret="splunk/token",
    )
    base.update(overrides)
    return SplunkMetricConfig(**base)  # type: ignore[arg-type]


def _provider(
    handler,
    cfg: SplunkMetricConfig | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[SplunkMetricProvider, httpx.AsyncClient, _StaticSecrets]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    concrete_secrets = secrets or _StaticSecrets({"splunk/token": "TKN"})
    provider = SplunkMetricProvider(
        config=cfg or _config(),
        http_client=client,
        secrets=concrete_secrets,
    )
    return provider, client, concrete_secrets  # type: ignore[return-value]


def _jsonl(*objs: dict) -> str:
    return "\n".join(json.dumps(o) for o in objs)


@pytest.mark.asyncio
async def test_export_stream_maps_results_and_labels() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = _jsonl(
            {"result": {"_time": "1700000060", "value": "2.0", "host": "web-a"}},
            {"result": {"_time": "1700000000", "value": "1.0", "host": "web-a"}},
        )
        return httpx.Response(200, text=body)

    provider, client, secrets = _provider(handler)
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
    assert points[0].labels == {"host": "web-a"}
    assert _EXPORT in str(captured[0].url)
    # token read through the secret provider, never in config
    assert secrets.reads == ["splunk/token"]
    assert captured[0].headers["Authorization"] == "Bearer TKN"


@pytest.mark.asyncio
async def test_instant_query_when_no_window() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_jsonl({"result": {"_time": "1700000000", "value": "3.14"}})
        )

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [3.14]


@pytest.mark.asyncio
async def test_iso_time_is_parsed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=_jsonl({"result": {"_time": "2026-07-10T00:00:00+00:00", "value": "9.0"}}),
        )

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert points[0].at == datetime(2026, 7, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_search_prefix_added_for_non_pipe_spl() -> None:
    captured: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(200, text="")

    provider, client, _ = _provider(handler, cfg=_config(searches={_METRIC: "index=metrics cpu"}))
    try:
        _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    # A bare (non-``|``) SPL string is prefixed with ``search``.
    assert b"search+index%3Dmetrics+cpu" in captured[0]


@pytest.mark.asyncio
async def test_unknown_metric_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, text="")

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="no Splunk search"):
            _ = [p async for p in provider.query(MetricQuery(metric_name="nope"))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="HTTP 403"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_secret_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, text="")

    provider, client, _ = _provider(handler, secrets=_StaticSecrets({}))
    try:
        with pytest.raises(SecretNotFoundError):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_control_lines_and_missing_value_skipped() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = _jsonl(
            {"messages": [{"type": "INFO", "text": "search ok"}]},
            {"result": {"_time": "1700000000"}},  # no value -> skipped
            {"result": {"_time": "1700000001", "value": "5.0"}},
        )
        return httpx.Response(200, text=body)

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [5.0]


@pytest.mark.asyncio
async def test_non_finite_value_dropped() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = _jsonl(
            {"result": {"_time": "1700000000", "value": "NaN"}},
            {"result": {"_time": "1700000001", "value": "7.0"}},
        )
        return httpx.Response(200, text=body)

    provider, client, _ = _provider(handler)
    try:
        points = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [7.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_time", ["inf", "-inf", "1e400", "99999999999999999999"])
async def test_out_of_range_time_fails_closed_not_crash(bad_time: str) -> None:
    # A non-finite / out-of-range _time raises OverflowError/OSError inside
    # datetime.fromtimestamp; the adapter must fail closed with a clean
    # MetricProviderError, never let the raw exception crash the batch.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=_jsonl({"result": {"_time": bad_time, "value": "1.0"}})
        )

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="missing/invalid"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_label_filter_in_memory() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = _jsonl(
            {"result": {"_time": "1700000000", "value": "1.0", "host": "web-a"}},
            {"result": {"_time": "1700000001", "value": "2.0", "host": "web-b"}},
        )
        return httpx.Response(200, text=body)

    provider, client, _ = _provider(handler)
    try:
        points = [
            p
            async for p in provider.query(
                MetricQuery(metric_name=_METRIC, labels={"host": "web-b"})
            )
        ]
    finally:
        await client.aclose()

    assert [p.value for p in points] == [2.0]


@pytest.mark.asyncio
async def test_max_points_cap_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = _jsonl(
            *[{"result": {"_time": str(1700000000 + i), "value": str(i)}} for i in range(5)]
        )
        return httpx.Response(200, text=body)

    provider, client, _ = _provider(handler, cfg=_config(max_points=2))
    try:
        with pytest.raises(MetricProviderError, match="max_points"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_malformed_json_line_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{not json}")

    provider, client, _ = _provider(handler)
    try:
        with pytest.raises(MetricProviderError, match="malformed JSON"):
            _ = [p async for p in provider.query(MetricQuery(metric_name=_METRIC))]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_since_after_until_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, text="")

    provider, client, _ = _provider(handler)
    now = datetime(2026, 7, 10, tzinfo=UTC)
    try:
        with pytest.raises(MetricProviderError, match="since > until"):
            _ = [
                p
                async for p in provider.query(
                    MetricQuery(metric_name=_METRIC, since=now, until=now - timedelta(hours=1))
                )
            ]
    finally:
        await client.aclose()


def test_config_rejects_plaintext_url() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(base_url="http://splunk.local:8089")


def test_config_rejects_empty_token_secret() -> None:
    with pytest.raises(ValueError, match="token_secret"):
        _config(token_secret="")
