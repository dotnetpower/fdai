"""AzureResourceChangeFeed - ARG ``resourcechanges`` accelerator (P0-2 style).

Verifies the bounded, oldest-first ``resourcechanges`` polling path
``forward_arg_resource_changes`` and ``inventory_sync_cli`` consume:

- The Kusto query text orders ``changeTime asc, id asc`` and folds the
  durable cursor into an inclusive-at-the-tie-breaker predicate.
- Create/Update rows are hydrated (bounded batch, ``Resources`` table) and
  emit a full upsert (``properties_complete=True``,
  ``observation_kind="full"``) mapped through the reviewed vocabulary.
- Delete rows are never hydrated and emit an unconfirmed tombstone
  (``tombstone_confirmed=False``, ``observation_kind="tombstone"``).
- The next cursor advances to the maximum ``(changeTime, id)`` seen across
  every validated row in the page, even rows dropped for an unmapped ARM
  type - so a skipped row is never reprocessed.
- Any HTTP/parse failure in either the ``resourcechanges`` query or the
  hydration query raises before a cursor is computed, so
  ``forward_arg_resource_changes`` never persists a stale/partial cursor.
- A hydration id genuinely absent from the ``Resources`` response (a
  benign race, not a fetch failure) is a silent skip, not a raise.

No real Azure endpoints are contacted.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fdai.delivery.azure.arg_projection import to_neutral_id
from fdai.delivery.azure.arg_resource_changes import (
    ArgResourceChangeError,
    AzureResourceChangeFeed,
    AzureResourceChangeFeedConfig,
    forward_arg_resource_changes,
)
from fdai.rule_catalog.schema.resource_type import (
    ResourceTypeRegistry,
    load_resource_type_registry_from_mapping,
)
from fdai.shared.providers.testing.event_bus import InMemoryEventBus
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.workload_identity import WorkloadIdentity

REPO_ROOT = Path(__file__).resolve().parents[5]
VOCABULARY_FILE = REPO_ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
_SCOPE = "00000000-0000-0000-0000-000000000001"


def _vocab() -> ResourceTypeRegistry:
    with VOCABULARY_FILE.open("r", encoding="utf-8") as fh:
        return load_resource_type_registry_from_mapping(yaml.safe_load(fh))


def _identity() -> WorkloadIdentity:
    return StaticWorkloadIdentity(
        audience="https://management.azure.com/.default",
        token="test-token-xyz",  # noqa: S106 - deterministic test literal
    )


def _config(**overrides: Any) -> AzureResourceChangeFeedConfig:
    defaults: dict[str, Any] = dict(subscription_scope=_SCOPE)
    defaults.update(overrides)
    return AzureResourceChangeFeedConfig(**defaults)


def _arm_type_for(vocab: ResourceTypeRegistry) -> tuple[str, str]:
    """Return one (neutral_id, arm_type) pair that exists in the vocabulary."""
    for entry in vocab:
        if entry.azure_arm_type is not None:
            return entry.id, entry.azure_arm_type
    raise AssertionError("vocabulary has no ARM-mapped type")  # pragma: no cover


def _arm_id(arm_type: str, name: str) -> str:
    return f"/subscriptions/{_SCOPE}/resourceGroups/rg-a/providers/{arm_type}/{name}"


def _change_row(
    *,
    change_id: str,
    change_time: str,
    change_type: str,
    arm_id: str,
    arm_type: str | None = None,
    changes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": change_id,
        "changeTime": change_time,
        "changeType": change_type,
        "targetResourceId": arm_id,
        "targetResourceType": arm_type,
        "changes": changes,
    }


def _hydration_row(*, arm_id: str, arm_type: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": arm_id,
        "type": arm_type,
        "name": arm_id.rsplit("/", 1)[-1],
        "location": "eastus",
        "kind": None,
        "sku": None,
        "identity": None,
        "tags": {"env": "prod"},
        "properties": {"provisioningState": "Succeeded"},
        "resourceGroup": "rg-a",
        "subscriptionId": _SCOPE,
    }
    row.update(extra)
    return row


def _router(
    *,
    on_changes: Callable[[httpx.Request], Any],
    on_hydration: Callable[[httpx.Request], Any] | None = None,
) -> Callable[[httpx.Request], Any]:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        query = payload.get("query", "")
        if isinstance(query, str) and query.strip().startswith("resourcechanges"):
            result = on_changes(request)
        else:
            assert on_hydration is not None, "unexpected hydration request"
            result = on_hydration(request)
        if inspect.isawaitable(result):
            return await result
        return result

    return handler


def _changes_response(rows: list[Mapping[str, Any]], **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {"data": rows}
    body.update(extra)
    return httpx.Response(200, json=body)


def _factory(
    handler: Callable[[httpx.Request], Any],
    *,
    cfg: AzureResourceChangeFeedConfig | None = None,
    vocab: ResourceTypeRegistry | None = None,
) -> tuple[AzureResourceChangeFeed, httpx.AsyncClient, ResourceTypeRegistry]:
    vocabulary = vocab if vocab is not None else _vocab()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    feed = AzureResourceChangeFeed(
        identity=_identity(),
        resource_types=vocabulary,
        http_client=client,
        config=cfg or _config(),
    )
    return feed, client, vocabulary


# ---------------------------------------------------------------------------
# Query construction (oldest-first ordering)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_orders_oldest_first_and_bounds_by_id_tiebreak() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _changes_response([])

    feed, client, _ = _factory(handler)
    try:
        await feed.poll("2026-07-10T05:00:00+00:00\x1fchange-9")
    finally:
        await client.aclose()

    body = captured[0].content.decode("utf-8")
    assert "order by changeTime asc, id asc" in body
    assert "strcmp(tostring(id), 'change-9') > 0" in body
    assert "changeType = tostring(properties.changeType)" in body
    assert "targetResourceId = tostring(properties.targetResourceId)" in body
    assert "targetResourceType = tostring(properties.targetResourceType)" in body
    assert "changes = properties.changes" in body
    assert (
        "project id, changeTime, changeType, targetResourceId, targetResourceType, changes" in body
    )


@pytest.mark.asyncio
async def test_empty_cursor_uses_lookback_window() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _changes_response([])

    feed, client, _ = _factory(handler, cfg=_config(initial_lookback_seconds=60))
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert result.events == ()
    assert result.next_cursor == ""
    assert "changeTime > datetime(" in captured[0].content.decode("utf-8")


# ---------------------------------------------------------------------------
# Update hydration -> full upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_row_hydrates_to_full_upsert() -> None:
    vocab = _vocab()
    neutral_id, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-a")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type=arm_type,
                    changes={
                        "properties.powerState.code": {
                            "newValue": "Running",
                            "previousValue": "Stopped",
                        }
                    },
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _hydration_row(
                    arm_id=arm_id,
                    arm_type=arm_type,
                    properties={"powerState": {"code": "Stopped"}},
                )
            ]
        )

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "inventory.resource_changed"
    assert event.resource_ref == to_neutral_id(arm_id)
    change = event.payload["inventory_change"]
    assert change["kind"] == "upsert"
    assert change["observation_kind"] == "full"
    assert change["properties_complete"] is True
    assert change["tombstone_confirmed"] is False
    assert change["property_mask"] == sorted(change["resource"]["props"])
    assert change["resource"]["type"] == neutral_id
    assert change["resource"]["provider_ref"] == arm_id
    assert change["resource"]["props"]["status"] == "Running"
    assert change["resource"]["props"]["properties"]["powerState"]["code"] == "Running"
    assert change["scope_ref"] == _SCOPE
    assert change["links_complete"] is False
    assert result.next_cursor == "2026-07-10T06:00:00+00:00\x1fc1"


@pytest.mark.asyncio
async def test_create_row_also_hydrates_as_upsert() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-created")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Create",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return _changes_response([_hydration_row(arm_id=arm_id, arm_type=arm_type)])

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert len(result.events) == 1
    assert result.events[0].payload["inventory_change"]["kind"] == "upsert"


# ---------------------------------------------------------------------------
# Delete tombstone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_row_emits_unconfirmed_tombstone_without_hydration() -> None:
    vocab = _vocab()
    neutral_id, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-deleted")
    hydration_called = False

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:30:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        nonlocal hydration_called
        hydration_called = True
        return _changes_response([])  # pragma: no cover - MUST NOT be reached

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert hydration_called is False
    assert len(result.events) == 1
    change = result.events[0].payload["inventory_change"]
    assert change["kind"] == "delete"
    assert change["observation_kind"] == "tombstone"
    assert change["properties_complete"] is False
    assert change["property_mask"] == []
    assert change["tombstone_confirmed"] is False
    assert change["resource"]["type"] == neutral_id
    assert change["resource"]["props"] == {}


# ---------------------------------------------------------------------------
# Cursor boundary duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeating_the_prior_boundary_row_fails_closed_instead_of_reemitting() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-tied")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes), vocab=vocab)
    try:
        first = await feed.poll("")
        assert first.next_cursor == "2026-07-10T06:00:00+00:00\x1fc1"
        # A server that (incorrectly) repeats the exact boundary row on the
        # next poll must not be silently re-emitted as a "new" change; the
        # feed fails closed instead of advancing on a non-advancing page.
        with pytest.raises(ArgResourceChangeError, match="did not advance"):
            await feed.poll(first.next_cursor)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_multiple_changes_to_one_resource_dedupe_to_the_latest() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-dup")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=arm_type,
                ),
                _change_row(
                    change_id="c2",
                    change_time="2026-07-10T06:00:01Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type=arm_type,
                ),
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return _changes_response([_hydration_row(arm_id=arm_id, arm_type=arm_type)])

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    # The later Update (c2) wins over the earlier Delete (c1) - exactly one
    # event for the resource, and it is the upsert.
    assert len(result.events) == 1
    assert result.events[0].payload["inventory_change"]["kind"] == "upsert"
    assert result.next_cursor == "2026-07-10T06:00:01+00:00\x1fc2"


# ---------------------------------------------------------------------------
# Partial page / hydration failure -> no cursor advance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncated_page_without_continuation_token_raises() -> None:
    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=_arm_id("Microsoft.Compute/virtualMachines", "a"),
                )
            ],
            resultTruncated=True,
        )

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        with pytest.raises(ArgResourceChangeError, match="truncated"):
            await feed.poll("")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_hydration_http_failure_raises_before_cursor_is_computed() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-a")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        with pytest.raises(ArgResourceChangeError, match="HTTP 500"):
            await feed.poll("")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_resourcechanges_http_failure_raises() -> None:
    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        with pytest.raises(ArgResourceChangeError, match="HTTP 500"):
            await feed.poll("")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_hydration_race_loss_is_a_benign_skip_not_a_failure() -> None:
    """A resource legitimately gone by hydration time is dropped, not raised."""
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-vanished")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return _changes_response([])  # resource is gone; benign, not an error

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration), vocab=vocab
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert result.events == ()
    # The cursor still advances - the row WAS validated, just not emitted.
    assert result.next_cursor == "2026-07-10T06:00:00+00:00\x1fc1"


# ---------------------------------------------------------------------------
# Unknown types skipped gracefully, cursor still advances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_delete_type_is_dropped_but_cursor_advances() -> None:
    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=_arm_id("Microsoft.Nonexistent/widgets", "w"),
                    arm_type="Microsoft.Nonexistent/widgets",
                )
            ]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert result.events == ()
    assert result.next_cursor == "2026-07-10T06:00:00+00:00\x1fc1"


@pytest.mark.asyncio
async def test_unknown_hydrated_type_is_dropped_but_cursor_advances() -> None:
    arm_id = _arm_id("Microsoft.Nonexistent/widgets", "w")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type="Microsoft.Nonexistent/widgets",
                )
            ]
        )

    async def on_hydration(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [_hydration_row(arm_id=arm_id, arm_type="Microsoft.Nonexistent/widgets")]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes, on_hydration=on_hydration))
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert result.events == ()
    assert result.next_cursor == "2026-07-10T06:00:00+00:00\x1fc1"


@pytest.mark.asyncio
async def test_delete_falls_back_to_arm_id_type_when_target_type_is_absent() -> None:
    vocab = _vocab()
    neutral_id, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-no-target-type")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=None,
                )
            ]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes), vocab=vocab)
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert len(result.events) == 1
    assert result.events[0].payload["inventory_change"]["resource"]["type"] == neutral_id


# ---------------------------------------------------------------------------
# Malformed rows fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("changeTime", None),
        ("changeTime", "not-a-timestamp"),
        ("changeType", "Rename"),
        ("targetResourceId", "not-an-arm-id"),
        ("changes", []),
    ],
)
@pytest.mark.asyncio
async def test_malformed_change_row_raises(field: str, value: Any) -> None:
    row = _change_row(
        change_id="c1",
        change_time="2026-07-10T06:00:00Z",
        change_type="Delete",
        arm_id=_arm_id("Microsoft.Compute/virtualMachines", "a"),
    )
    row[field] = value

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response([row])

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        with pytest.raises(ArgResourceChangeError):
            await feed.poll("")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_missing_data_array_raises() -> None:
    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        with pytest.raises(ArgResourceChangeError, match="data"):
            await feed.poll("")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Cursor parsing bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cursor",
    [
        "not-a-timestamp",
        "2026-07-10T05:00:00+00:00",  # missing separator + id
        "2026-07-10T05:00:00+00:00\x1f",  # empty id
        "not-a-timestamp\x1fc1",
    ],
)
async def test_malformed_cursor_fails_before_any_request(bad_cursor: str) -> None:
    called = False

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return _changes_response([])

    feed, client, _ = _factory(_router(on_changes=on_changes))
    try:
        with pytest.raises(ArgResourceChangeError, match="malformed"):
            await feed.poll(bad_cursor)
    finally:
        await client.aclose()

    assert called is False


@pytest.mark.asyncio
async def test_cursor_id_with_illegal_quote_character_is_rejected() -> None:
    feed, client, _ = _factory(_router(on_changes=lambda _r: _changes_response([])))
    try:
        with pytest.raises(ArgResourceChangeError, match="illegal character"):
            await feed.poll("2026-07-10T05:00:00+00:00\x1fc1' or '1'='1")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Config bounds
# ---------------------------------------------------------------------------


def test_config_rejects_plaintext_endpoint() -> None:
    with pytest.raises(ValueError, match="https://"):
        _config(arg_endpoint="http://management.azure.com")


def test_config_rejects_empty_subscription() -> None:
    with pytest.raises(ValueError, match="canonical UUID"):
        _config(subscription_scope="")


def test_config_rejects_hydration_batch_over_the_cap() -> None:
    with pytest.raises(ValueError, match="max_hydration_batch"):
        _config(max_hydration_batch=101)


def test_config_rejects_zero_hydration_batch() -> None:
    with pytest.raises(ValueError, match="max_hydration_batch"):
        _config(max_hydration_batch=0)


def test_config_accepts_the_hydration_batch_cap_boundary() -> None:
    assert _config(max_hydration_batch=100).max_hydration_batch == 100


def test_config_rejects_zero_page_size() -> None:
    with pytest.raises(ValueError, match="page_size"):
        _config(page_size=0)


def test_config_rejects_zero_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        _config(timeout_seconds=0)


@pytest.mark.asyncio
async def test_hydration_batches_are_bounded_to_the_configured_cap() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_ids = [_arm_id(arm_type, f"thing-{i}") for i in range(5)]
    hydration_batches: list[int] = []

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id=f"c{i}",
                    change_time=f"2026-07-10T06:00:0{i}Z",
                    change_type="Update",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
                for i, arm_id in enumerate(arm_ids)
            ]
        )

    async def on_hydration(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content.decode("utf-8"))["query"]
        # Count how many quoted ids are in this batch's query text.
        hydration_batches.append(query.count("/subscriptions/"))
        rows = [_hydration_row(arm_id=arm_id, arm_type=arm_type) for arm_id in arm_ids]
        return _changes_response(rows)

    feed, client, _ = _factory(
        _router(on_changes=on_changes, on_hydration=on_hydration),
        cfg=_config(max_hydration_batch=2),
        vocab=vocab,
    )
    try:
        result = await feed.poll("")
    finally:
        await client.aclose()

    assert len(result.events) == 5
    # 5 ids at batch size 2 -> 3 hydration requests (2, 2, 1).
    assert hydration_batches == [2, 2, 1]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_key_and_event_id_are_stable_across_polls() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-a")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes), vocab=vocab)
    try:
        first = await feed.poll("")
        second = await feed.poll("")
    finally:
        await client.aclose()

    assert first.events[0].event_id == second.events[0].event_id
    assert first.events[0].idempotency_key == second.events[0].idempotency_key


# ---------------------------------------------------------------------------
# Orchestration: forward_arg_resource_changes (cursor persistence, publish)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forward_publishes_and_persists_cursor_on_success() -> None:
    vocab = _vocab()
    _, arm_type = _arm_type_for(vocab)
    arm_id = _arm_id(arm_type, "thing-a")

    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return _changes_response(
            [
                _change_row(
                    change_id="c1",
                    change_time="2026-07-10T06:00:00Z",
                    change_type="Delete",
                    arm_id=arm_id,
                    arm_type=arm_type,
                )
            ]
        )

    feed, client, _ = _factory(_router(on_changes=on_changes), vocab=vocab)
    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()
    try:
        published = await forward_arg_resource_changes(
            feed=feed,
            state_store=state_store,
            event_bus=event_bus,
            topic="inventory.events",
            scope=_SCOPE,
        )
    finally:
        await client.aclose()

    assert published == 1
    assert len(event_bus._records["inventory.events"]) == 1
    saved = await state_store.read_state(f"arg_resource_change_cursor:{_SCOPE}")
    assert saved is not None
    assert saved["cursor"] == "2026-07-10T06:00:00+00:00\x1fc1"


@pytest.mark.asyncio
async def test_forward_does_not_persist_cursor_when_the_poll_fails() -> None:
    async def on_changes(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    feed, client, _ = _factory(_router(on_changes=on_changes))
    state_store = InMemoryStateStore()
    event_bus = InMemoryEventBus()
    try:
        with pytest.raises(ArgResourceChangeError):
            await forward_arg_resource_changes(
                feed=feed,
                state_store=state_store,
                event_bus=event_bus,
                topic="inventory.events",
                scope=_SCOPE,
            )
    finally:
        await client.aclose()

    saved = await state_store.read_state(f"arg_resource_change_cursor:{_SCOPE}")
    assert saved is None
    assert event_bus._records == {}


@pytest.mark.asyncio
async def test_forward_resumes_from_the_persisted_cursor() -> None:
    seen_cursors: list[str] = []

    async def on_changes(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content.decode("utf-8"))["query"]
        seen_cursors.append(query)
        return _changes_response([])

    feed, client, _ = _factory(_router(on_changes=on_changes))
    state_store = InMemoryStateStore()
    await state_store.write_state(
        f"arg_resource_change_cursor:{_SCOPE}",
        {"cursor": "2026-07-10T06:00:00+00:00\x1fc1"},
    )
    event_bus = InMemoryEventBus()
    try:
        await forward_arg_resource_changes(
            feed=feed,
            state_store=state_store,
            event_bus=event_bus,
            topic="inventory.events",
            scope=_SCOPE,
        )
    finally:
        await client.aclose()

    assert "strcmp(tostring(id), 'c1') > 0" in seen_cursors[0]


@pytest.mark.asyncio
async def test_forward_rejects_non_positive_deadline() -> None:
    feed, client, _ = _factory(_router(on_changes=lambda _r: _changes_response([])))
    try:
        with pytest.raises(ValueError, match="deadline_seconds"):
            await forward_arg_resource_changes(
                feed=feed,
                state_store=InMemoryStateStore(),
                event_bus=InMemoryEventBus(),
                topic="inventory.events",
                scope=_SCOPE,
                deadline_seconds=0,
            )
    finally:
        await client.aclose()
