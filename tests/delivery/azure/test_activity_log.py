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

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    # bearer token attached
    assert captured[0].headers["Authorization"] == "Bearer test-token-xyz"
    assert "eventTimestamp" in str(captured[0].url)
    # last-page resume cursor is the newest event timestamp (no separator)
    assert "\x1f" not in (page.cursor or "")
    assert page.cursor.startswith("2026-07-10T06:00:00")


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

    assert page.resources == ()


@pytest.mark.asyncio
async def test_http_error_raises_activity_log_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    factory, client, _ = _factory(handler)
    fetch = factory.build_fetch_fn()
    try:
        with pytest.raises(ActivityLogError, match="HTTP 500"):
            await fetch("2026-07-10T05:00:00+00:00")
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


def test_config_rejects_empty_subscription() -> None:
    with pytest.raises(ValueError, match="subscription_scope"):
        _config(subscription_scope="")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cursor",
    ["2026-07-10' or '1'='1", "not-a-timestamp", "'; drop table x --"],
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
