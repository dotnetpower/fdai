"""AzureActivityLogFactory - HTTP-level round-trip via httpx.MockTransport (P0-2).

Verifies the Activity-Log delta path the ``AzureResourceGraphInventory.delta``
stream consumes:

- Bearer-token authentication using the injected ``WorkloadIdentity``.
- A resume cursor builds the ``eventTimestamp ge`` filter; an in-flight
  cursor follows the encoded ``nextLink`` and carries the running newest
  timestamp forward.
- Activity Log records map to CSP-neutral ``ResourceRecord`` upserts on the
  SAME neutral id the full-scan produces; the raw ARM id lives on
  ``provider_ref``.
- Non-``Succeeded`` events and events whose ARM type is not in the
  vocabulary are dropped.
- Non-2xx / non-JSON / missing ``value`` responses raise ``ActivityLogError``
  so the delta stream fails closed without a ``final=True`` fence.

No real Azure endpoints are contacted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fdai.delivery.azure.activity_log import (
    ActivityLogError,
    AzureActivityLogFactory,
    AzureActivityLogFactoryConfig,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.workload_identity import WorkloadIdentity

REPO_ROOT = Path(__file__).resolve().parents[5]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"


def _vocab() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _identity() -> WorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token-xyz",  # noqa: S106 - deterministic test literal
    )


def _config(**overrides: Any) -> AzureActivityLogFactoryConfig:
    defaults: dict[str, Any] = dict(
        subscription_scope="00000000-0000-0000-0000-000000000001",
    )
    defaults.update(overrides)
    return AzureActivityLogFactoryConfig(**defaults)


def _arm_type_for(vocab: ResourceTypeRegistry) -> tuple[str, str]:
    """Return one (neutral_id, arm_type) pair that exists in the vocabulary."""
    for entry in vocab:
        if entry.azure_arm_type is not None:
            return entry.id, entry.azure_arm_type
    raise AssertionError("vocabulary has no ARM-mapped type")  # pragma: no cover


def _factory(handler, cfg: AzureActivityLogFactoryConfig | None = None):
    vocab = _vocab()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    factory = AzureActivityLogFactory(
        identity=_identity(),
        resource_types=vocab,
        http_client=client,
        config=cfg or _config(),
    )
    return factory, client, vocab


@pytest.mark.asyncio
async def test_resume_cursor_builds_filter_and_maps_event() -> None:
    vocab = _vocab()
    neutral_id, arm_type = _arm_type_for(vocab)
    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        f"/resourceGroups/rg-a/providers/{arm_type}/thing-a"
    )
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "resourceId": arm_id,
                        "resourceType": {"value": arm_type},
                        "operationName": {"value": f"{arm_type}/write"},
                        "status": {"value": "Succeeded"},
                        "eventTimestamp": "2026-07-10T06:00:00.123Z",
                        "caller": "user@example.com",
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    factory = AzureActivityLogFactory(
        identity=_identity(), resource_types=vocab, http_client=client, config=_config()
    )
    fetch = factory.build_fetch_fn()
    try:
        page = await fetch("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()

    assert page.has_more is False
    assert len(page.resources) == 1
    rec = page.resources[0]
    assert rec.type == neutral_id
    assert rec.provider_ref == arm_id
    assert len(page.links) == 1
    assert page.links[0].link_type == "contains"
    assert page.links[0].to_id == rec.resource_id
    assert page.links[0].to_type == rec.type
    assert page.relationship_reconciliation_after == "2026-07-10T06:00:00.123000+00:00"
    # bearer token attached
    assert captured[0].headers["Authorization"] == "Bearer test-token-xyz"
    assert "eventTimestamp" in str(captured[0].url)
    # last-page resume cursor is the newest event timestamp (no separator)
    assert "\x1f" not in (page.cursor or "")
    assert page.cursor.startswith("2026-07-10T06:00:00")


@pytest.mark.asyncio
async def test_delete_event_is_not_upserted_and_still_advances_cursor() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        f"/resourceGroups/rg-a/providers/{arm_type}/thing-deleted"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "resourceId": arm_id,
                        "resourceType": {"value": arm_type},
                        "operationName": {"value": f"{arm_type}/delete"},
                        "status": {"value": "Succeeded"},
                        "eventTimestamp": "2026-07-10T06:30:00Z",
                    }
                ]
            },
        )

    factory, client, _ = _factory(handler)
    try:
        page = await factory.build_fetch_fn()("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()

    assert page.resources == ()
    assert page.links == ()
    assert page.cursor == "2026-07-10T06:30:00+00:00"
    assert page.relationship_reconciliation_after == "2026-07-10T06:30:00+00:00"


@pytest.mark.asyncio
async def test_equal_timestamp_dedup_is_independent_of_page_order() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        f"/resourceGroups/rg-a/providers/{arm_type}/thing-tied"
    )
    events = [
        {
            "resourceId": arm_id,
            "resourceType": {"value": arm_type},
            "operationName": {"value": f"{arm_type}/write"},
            "status": {"value": "Succeeded"},
            "eventTimestamp": "2026-07-10T06:45:00Z",
            "caller": caller,
        }
        for caller in ("alpha@example.com", "zulu@example.com")
    ]
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        ordered = events if calls == 0 else list(reversed(events))
        calls += 1
        return httpx.Response(200, json={"value": ordered})

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        first = await fetch("2026-07-10T05:00:00+00:00")
        second = await fetch("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()

    assert first.resources == second.resources


@pytest.mark.parametrize("event_timestamp", [None, "not-a-timestamp", "2026-07-10T06:45:00"])
@pytest.mark.asyncio
async def test_supported_event_requires_timezone_aware_timestamp(
    event_timestamp: str | None,
) -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        f"/resourceGroups/rg-a/providers/{arm_type}/thing-invalid-time"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "resourceId": arm_id,
                        "resourceType": {"value": arm_type},
                        "operationName": {"value": f"{arm_type}/write"},
                        "status": {"value": "Succeeded"},
                        "eventTimestamp": event_timestamp,
                    }
                ]
            },
        )

    factory, client, _ = _factory(handler)
    try:
        with pytest.raises(ActivityLogError, match="eventTimestamp"):
            await factory.build_fetch_fn()("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_activity_page_rejects_event_count_over_cap() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{}, {}]})

    factory, client, _ = _factory(handler, cfg=_config(max_events_per_page=1))
    try:
        with pytest.raises(ActivityLogError, match="event count exceeds cap"):
            await factory.build_fetch_fn()("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_activity_page_rejects_non_object_event() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": ["malformed-event"]})

    factory, client, _ = _factory(handler)
    try:
        with pytest.raises(ActivityLogError, match="non-object event"):
            await factory.build_fetch_fn()("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_untracked_activity_event_still_requires_ordering_timestamp() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [{"category": "Administrative"}]})

    factory, client, _ = _factory(handler)
    try:
        with pytest.raises(ActivityLogError, match="eventTimestamp"):
            await factory.build_fetch_fn()("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_nextlink_paging_encodes_running_max() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        f"/resourceGroups/rg-a/providers/{arm_type}/thing-a"
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "resourceId": arm_id,
                        "resourceType": {"value": arm_type},
                        "operationName": {"value": f"{arm_type}/write"},
                        "status": {"value": "Succeeded"},
                        "eventTimestamp": "2026-07-10T06:00:00Z",
                    }
                ],
                "nextLink": "https://management.azure.com/next?token=abc",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    factory = AzureActivityLogFactory(
        identity=_identity(), resource_types=vocab, http_client=client, config=_config()
    )
    fetch = factory.build_fetch_fn()
    try:
        page = await fetch("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()

    assert page.has_more is True
    assert page.cursor is not None
    assert "\x1f" in page.cursor
    running_max, _, url = page.cursor.partition("\x1f")
    assert running_max.startswith("2026-07-10T06:00:00")
    assert url == "https://management.azure.com/next?token=abc"


@pytest.mark.asyncio
async def test_cross_host_nextlink_is_rejected_before_token_delivery() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"value": [], "nextLink": "https://example.com/capture"},
        )

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        first = await fetch("2026-07-10T05:00:00+00:00")
        assert first.cursor is not None
        with pytest.raises(ActivityLogError, match="scheme or host"):
            await fetch(first.cursor)
    finally:
        await client.aclose()

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_failed_status_and_unknown_type_dropped() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "resourceId": f"/subscriptions/x/resourceGroups/rg/providers/{arm_type}/a",
                        "resourceType": {"value": arm_type},
                        "status": {"value": "Failed"},
                        "eventTimestamp": "2026-07-10T06:00:00Z",
                    },
                    {
                        "resourceId": "/subscriptions/x/resourceGroups/rg/providers/"
                        "Microsoft.Nonexistent/widgets/w",
                        "resourceType": {"value": "Microsoft.Nonexistent/widgets"},
                        "status": {"value": "Succeeded"},
                        "eventTimestamp": "2026-07-10T06:00:01Z",
                    },
                ]
            },
        )

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        page = await fetch("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()

    assert page.relationship_reconciliation_after is None

    assert page.resources == ()


@pytest.mark.asyncio
async def test_http_error_raises_activity_log_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="sensitive-resource-reference")

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        with pytest.raises(ActivityLogError, match="HTTP 500") as captured:
            await fetch("2026-07-10T05:00:00+00:00")
        assert "sensitive-resource-reference" not in str(captured.value)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_value_array_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        with pytest.raises(ActivityLogError, match="missing 'value'"):
            await fetch("2026-07-10T05:00:00+00:00")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_empty_resume_cursor_uses_lookback() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    factory, client, _ = _factory(handler, cfg=_config(initial_lookback_seconds=60))
    fetch = factory.build_fetch_fn()
    try:
        page = await fetch("")
    finally:
        await client.aclose()

    assert page.has_more is False
    assert "eventTimestamp" in str(captured[0].url)


def test_config_rejects_plaintext_endpoint() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(arg_endpoint="http://management.azure.com")


@pytest.mark.parametrize(
    "arg_endpoint",
    [
        "https://user@example.com",
        "https://example.com/custom/path",
        "https://example.com?api-version=unsafe",
        "https://example.com#fragment",
    ],
)
def test_config_rejects_non_origin_activity_endpoint(arg_endpoint: str) -> None:
    with pytest.raises(ValueError, match="origin URL"):
        _config(arg_endpoint=arg_endpoint)


def test_config_rejects_empty_subscription() -> None:
    with pytest.raises(ValueError, match="subscription_scope"):
        _config(subscription_scope="")


def test_config_rejects_zero_event_page_cap() -> None:
    with pytest.raises(ValueError, match="max_events_per_page"):
        _config(max_events_per_page=0)


@pytest.mark.parametrize(
    "subscription_scope",
    ["../other?api-version=unsafe", "00000000000000000000000000000001"],
)
def test_config_rejects_noncanonical_subscription_scope(subscription_scope: str) -> None:
    with pytest.raises(ValueError, match="canonical UUID"):
        _config(subscription_scope=subscription_scope)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cursor",
    [
        "2026-07-10' or '1'='1",
        "not-a-timestamp",
        "2026-07-10T05:00:00",
        "'; drop table x --",
    ],
)
async def test_invalid_resume_cursor_fails_closed(bad_cursor: str) -> None:
    # A corrupt / hostile persisted cursor must not be folded into the OData
    # $filter; only a valid RFC 3339 timestamp is accepted.
    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={"value": []})

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        with pytest.raises(ActivityLogError, match="valid RFC 3339"):
            await fetch(bad_cursor)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "cursor",
    [
        "bad-timestamp\x1fhttps://management.azure.com/next?token=abc",
        "2026-07-10T05:00:00Z\x1f",
    ],
)
@pytest.mark.asyncio
async def test_invalid_inflight_cursor_fails_before_http_request(cursor: str) -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"value": []})

    factory, client, _ = _factory(handler)
    try:
        with pytest.raises(ActivityLogError, match="in-flight cursor"):
            await factory.build_fetch_fn()(cursor)
    finally:
        await client.aclose()

    assert called is False


@pytest.mark.asyncio
async def test_valid_resume_cursor_is_canonicalized() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"value": []})

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        await fetch("2026-07-10T05:00:00Z")  # 'Z' form is parsed + canonicalized
    finally:
        await client.aclose()

    # Activity Log rejects an explicit +00:00 offset in this filter and
    # requires the canonical UTC Z form.
    url = str(captured[0].url)
    assert "2026-07-10T05:00:00Z" in url
    assert "05:00:00+00:00" not in url
