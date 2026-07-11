"""httpx-mocked tests for the Azure DevOps change feed (P1-5 PR-B)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.azure_devops.change_feed import (
    AzureDevOpsChangeFeed,
    AzureDevOpsChangeFeedConfig,
)
from fdai.shared.providers.change_feed import ChangeFeed, ChangeFeedError

_SINCE = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)
_UNTIL = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)


def _config(**overrides: object) -> AzureDevOpsChangeFeedConfig:
    base: dict[str, object] = dict(organization="acme", project="platform")
    base.update(overrides)
    return AzureDevOpsChangeFeedConfig(**base)  # type: ignore[arg-type]


async def _token() -> str:
    return "PAT123"


def _feed(handler, cfg: AzureDevOpsChangeFeedConfig | None = None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = AzureDevOpsChangeFeed(
        config=cfg or _config(), http_client=client, token_provider=_token
    )
    return feed, client


def _build(build_id: int, minutes_before_until: int) -> dict:
    at = _UNTIL - timedelta(minutes=minutes_before_until)
    return {
        "id": build_id,
        "buildNumber": f"2026.{build_id}",
        "sourceVersion": f"{'a' * 12}{build_id}",
        "sourceBranch": "refs/heads/main",
        "finishTime": at.isoformat(),
        "requestedFor": {"displayName": "Dev One"},
    }


def test_feed_satisfies_protocol() -> None:
    feed, _ = _feed(lambda r: httpx.Response(200, json={"value": []}))
    assert isinstance(feed, ChangeFeed)


@pytest.mark.asyncio
async def test_happy_path_maps_builds_in_window() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": [_build(1, 30), _build(2, 60)]})

    feed, client = _feed(handler)
    try:
        records = await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()

    assert [r.change_id for r in records] == ["ado-build-1", "ado-build-2"]
    assert records[0].source == "azure-devops"
    assert records[0].metadata["branch"] == "refs/heads/main"
    # PAT sent as HTTP Basic with empty username
    expected = base64.b64encode(b":PAT123").decode("ascii")
    assert captured[0].headers["Authorization"] == f"Basic {expected}"
    assert "minTime=" in str(captured[0].url)
    assert "maxTime=" in str(captured[0].url)


@pytest.mark.asyncio
async def test_bearer_auth_scheme() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    feed, client = _feed(handler, cfg=_config(auth_scheme="bearer"))
    try:
        await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()

    assert captured[0].headers["Authorization"] == "Bearer PAT123"


@pytest.mark.asyncio
async def test_pagination_stitches_pages_via_continuation_token() -> None:
    pages = [
        (
            {"value": [_build(1, 10)]},
            {"x-ms-continuationtoken": "TOKEN2"},
        ),
        (
            {"value": [_build(2, 20)]},
            {},  # no continuation -> last page
        ),
    ]
    seen_tokens: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("continuationToken")
        seen_tokens.append(token)
        idx = 0 if token is None else 1
        body, headers = pages[idx]
        return httpx.Response(200, json=body, headers=headers)

    feed, client = _feed(handler)
    try:
        records = await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()

    assert [r.change_id for r in records] == ["ado-build-1", "ado-build-2"]
    assert seen_tokens == [None, "TOKEN2"]


@pytest.mark.asyncio
async def test_pagination_cap_fails_closed() -> None:
    # Every page returns a continuation token -> never terminates within cap.
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"value": [_build(1, 5)]},
            headers={"x-ms-continuationtoken": "MORE"},
        )

    feed, client = _feed(handler, cfg=_config(max_pages=3))
    try:
        with pytest.raises(ChangeFeedError, match="pagination cap"):
            await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_in_window_filtering_across_page_boundary() -> None:
    # page 1 has an out-of-window build; page 2 has an in-window one.
    out_of_window = dict(_build(1, 0))
    out_of_window["finishTime"] = (_UNTIL + timedelta(hours=2)).isoformat()
    pages = [
        ({"value": [out_of_window]}, {"x-ms-continuationtoken": "T2"}),
        ({"value": [_build(2, 30)]}, {}),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("continuationToken")
        idx = 0 if token is None else 1
        body, headers = pages[idx]
        return httpx.Response(200, json=body, headers=headers)

    feed, client = _feed(handler)
    try:
        records = await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()

    assert [r.change_id for r in records] == ["ado-build-2"]


@pytest.mark.asyncio
async def test_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    feed, client = _feed(handler)
    try:
        with pytest.raises(ChangeFeedError, match="HTTP 401"):
            await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_malformed_payload_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    feed, client = _feed(handler)
    try:
        with pytest.raises(ChangeFeedError, match="missing 'value'"):
            await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_max_records_stops_early() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"value": [_build(i, i + 1) for i in range(1, 6)]},
            headers={"x-ms-continuationtoken": "MORE"},
        )

    feed, client = _feed(handler, cfg=_config(max_records=2))
    try:
        records = await feed.recent(since=_SINCE, until=_UNTIL)
    finally:
        await client.aclose()

    assert len(records) == 2


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="organization"):
        _config(organization="")
    with pytest.raises(ValueError, match="auth_scheme"):
        _config(auth_scheme="oauth")
    with pytest.raises(ValueError, match="https://"):
        _config(api_base="http://dev.azure.com")
