"""Tests for the change-feed correlation primitive and GitHub adapter."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from fdai.delivery.github.change_feed import (
    ChangeFeedError,
    GitHubChangeFeed,
    GitHubChangeFeedConfig,
)
from fdai.shared.providers.change_feed import (
    ChangeRecord,
    EmptyChangeFeed,
    correlate_changes,
)

_INCIDENT_AT = datetime(2026, 7, 10, 18, 0, tzinfo=UTC)


def _change(minutes_before: float, *, cid: str, hints: tuple[str, ...] = ()) -> ChangeRecord:
    return ChangeRecord(
        change_id=cid,
        at=_INCIDENT_AT - timedelta(minutes=minutes_before),
        source="github",
        ref=cid,
        summary=f"change {cid}",
        resource_hints=hints,
    )


def test_correlate_drops_changes_after_incident_or_outside_window() -> None:
    changes = [
        _change(-5, cid="after"),  # 5 min AFTER incident -> dropped
        _change(120, cid="old"),  # 2h before, window 1h -> dropped
        _change(10, cid="inwindow"),
    ]
    result = correlate_changes(changes, incident_at=_INCIDENT_AT, window=timedelta(hours=1))
    assert [c.change.change_id for c in result] == ["inwindow"]


def test_correlate_ranks_closer_change_higher() -> None:
    changes = [_change(50, cid="far"), _change(2, cid="near")]
    result = correlate_changes(changes, incident_at=_INCIDENT_AT)
    assert [c.change.change_id for c in result] == ["near", "far"]
    assert result[0].score > result[1].score
    assert result[0].lead_seconds == pytest.approx(120.0)


def test_correlate_resource_overlap_boosts_score() -> None:
    changes = [
        _change(30, cid="no-overlap"),
        _change(30, cid="overlap", hints=("vm-a",)),
    ]
    result = correlate_changes(changes, incident_at=_INCIDENT_AT, incident_resources=("vm-a",))
    top = result[0]
    assert top.change.change_id == "overlap"
    assert top.resource_overlap == ("vm-a",)


def test_correlate_rejects_nonpositive_window() -> None:
    with pytest.raises(ValueError, match="window"):
        correlate_changes([], incident_at=_INCIDENT_AT, window=timedelta(0))


@pytest.mark.asyncio
async def test_empty_change_feed_returns_nothing() -> None:
    feed = EmptyChangeFeed()
    out = await feed.recent(since=_INCIDENT_AT, until=_INCIDENT_AT)
    assert out == ()


def _feed(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> tuple[GitHubChangeFeed, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = GitHubChangeFeed(
        config=GitHubChangeFeedConfig(repository="acme/app", environment="production"),
        http_client=client,
        token_provider=_token,
    )
    return feed, client


async def _token() -> str:
    return "gh-token"  # noqa: S105 - test literal, not a secret


@pytest.mark.asyncio
async def test_github_feed_maps_deployments_in_window() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "sha": "abcdef1234567890",
                    "environment": "production",
                    "created_at": "2026-07-10T17:50:00Z",
                    "description": "release 42",
                    "creator": {"login": "deployer"},
                },
                {
                    "id": 2,
                    "sha": "00ff",
                    "environment": "production",
                    "created_at": "2026-07-09T00:00:00Z",  # outside window
                },
            ],
        )

    feed, client = _feed(handler)
    since = _INCIDENT_AT - timedelta(hours=1)
    try:
        records = await feed.recent(since=since, until=_INCIDENT_AT, resource_hint="app-svc")
    finally:
        await client.aclose()

    assert len(records) == 1
    rec = records[0]
    assert rec.source == "github"
    assert rec.ref == "abcdef123456"  # sha truncated to 12
    assert rec.author == "deployer"
    assert rec.resource_hints == ("app-svc",)
    assert captured[0].headers["Authorization"] == "Bearer gh-token"


@pytest.mark.asyncio
async def test_github_feed_http_error_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="rate limited")

    feed, client = _feed(handler)
    try:
        with pytest.raises(ChangeFeedError, match="HTTP 403"):
            await feed.recent(since=_INCIDENT_AT - timedelta(hours=1), until=_INCIDENT_AT)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_github_feed_warns_when_invalid_timestamp_is_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 7,
                    "sha": "sensitive-provider-value",
                    "environment": "production",
                    "created_at": "not-a-timestamp",
                }
            ],
        )

    feed, client = _feed(handler)
    try:
        with caplog.at_level(logging.WARNING, logger="fdai.delivery.github.change_feed"):
            records = await feed.recent(
                since=_INCIDENT_AT - timedelta(hours=1),
                until=_INCIDENT_AT,
            )
    finally:
        await client.aclose()

    assert records == []
    assert len(caplog.records) == 1
    warning = caplog.records[0]
    assert warning.message == "github_change_feed_record_skipped"
    assert warning.__dict__["provider"] == "github"
    assert warning.__dict__["record_type"] == "deployment"
    assert warning.__dict__["reason"] == "invalid_created_at"
    assert "sensitive-provider-value" not in caplog.text


def test_github_config_validation() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        GitHubChangeFeedConfig(repository="noslash")
    with pytest.raises(ValueError, match="max_records"):
        GitHubChangeFeedConfig(repository="a/b", max_records=0)
