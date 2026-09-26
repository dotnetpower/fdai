"""No-network durable outbound approval admission, restart, and ambiguity."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.core.hil_resume.integrity import action_payload_hash
from fdai.delivery.chatops.slack_adapter import (
    HIL_BINDING_FIELD,
    SLACK_POST_URL,
    SlackHilAdapter,
    SlackHilAdapterConfig,
)
from fdai.delivery.chatops.slack_request_outbox import DurableSlackApprovalChannel
from fdai.shared.providers.hil_channel import (
    HilApprovalReceipt,
    HilApprovalRequest,
    HilChannelError,
    HilDecision,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_CHANNEL = "CEXAMPLE1"
_AT = datetime(2026, 9, 26, tzinfo=UTC)


def _request(dispatch_id: str | None = None) -> HilApprovalRequest:
    return HilApprovalRequest(
        approval_id="approval-1",
        correlation_id="correlation-1",
        action_id="action-1",
        action_type="example.action",
        rule_ids=(),
        target_resource_ref="example-resource",
        blast_radius_summary="one resource",
        action_hash="hash-1",
        metadata={
            HIL_BINDING_FIELD: "a",
            **({"approval_dispatch_id": dispatch_id} if dispatch_id else {}),
        },
    )


async def _park(store: InMemoryStateStore, *, expiry: datetime | None = None) -> None:
    request = _request()
    action = {
        "action_id": request.action_id,
        "target_resource_ref": request.target_resource_ref,
        "citing_rules": [],
    }
    await store.write_state(
        f"hil_park:{request.approval_id}",
        {
            "status": "pending",
            "approval_id": request.approval_id,
            "correlation_id": request.correlation_id,
            "idempotency_key": request.metadata[HIL_BINDING_FIELD],
            "request_fingerprint": request.action_hash,
            "action_hash": action_payload_hash(action),
            "action_type": request.action_type,
            "action": action,
            "approval_context": {
                "expires_at": (expiry or _AT + timedelta(minutes=30)).isoformat(),
                "ttl_seconds": 1800,
            },
        },
    )


def _channel(
    client: httpx.AsyncClient,
    store: InMemoryStateStore,
    clock: list[datetime],
) -> DurableSlackApprovalChannel:
    adapter = SlackHilAdapter(
        config=SlackHilAdapterConfig(
            api_url=SLACK_POST_URL,
            channel_id=_CHANNEL,
            bot_token="fixture",
        ),
        http_client=client,
    )
    return DurableSlackApprovalChannel(adapter=adapter, store=store, clock=lambda: clock[0])


async def _record(store: InMemoryStateStore) -> dict[str, Any]:
    records, total = await store.read_state_page("hil-slack-request:", limit=10)
    assert total == 1
    return dict(records[0])


async def test_reserved_request_survives_restart_and_acceptance_is_replayed() -> None:
    store = InMemoryStateStore()
    await _park(store)
    clock = [_AT]
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request)
        return httpx.Response(200, json={"ok": True, "channel": _CHANNEL, "ts": "123.456"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        before_restart = _channel(client, store, clock)
        await before_restart.reserve(_request())
        assert posts == []
        assert (await _record(store))["status"] == "queued"
        after_restart = _channel(client, store, clock)
        assert await after_restart.reconcile_once() is True
        record = await _record(store)
        assert record["status"] == "accepted"
        assert record["payload_digest"] == hashlib.sha256(posts[0].content).hexdigest()
        receipt = await _channel(client, store, clock).send(_request())
        assert receipt.channel_ref == f"slack:{_CHANNEL}/123.456"
        assert (await after_restart.poll(receipt)).decision is HilDecision.PENDING
    assert len(posts) == 1
    assert await store.verify_chain()


async def test_lost_ack_is_unknown_across_restart_without_reposting() -> None:
    store = InMemoryStateStore()
    await _park(store)
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        raise httpx.ReadTimeout("synthetic interruption", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HilChannelError, match="unknown"):
            await _channel(client, store, [_AT]).send(_request())
        assert (await _record(store))["status"] == "unknown"
        with pytest.raises(HilChannelError, match="held"):
            await _channel(client, store, [_AT]).send(_request())
        assert await _channel(client, store, [_AT]).reconcile_once() is False
    assert posts == 1


async def test_mismatched_provider_receipt_is_unknown_not_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    await _park(store)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("provider I/O is not needed"))
    ) as client:
        channel = _channel(client, store, [_AT])
        monkeypatch.setattr(
            channel._adapter,
            "send",
            AsyncMock(
                return_value=HilApprovalReceipt(
                    approval_id="another-approval",
                    channel_ref=f"slack:{_CHANNEL}/123.456",
                    sent_at=_AT,
                )
            ),
        )
        with pytest.raises(HilChannelError, match="does not bind"):
            await channel.send(_request())
    assert (await _record(store))["status"] == "unknown"


async def test_expired_park_and_conflicting_payload_never_post() -> None:
    store = InMemoryStateStore()
    await _park(store, expiry=_AT - timedelta(seconds=1))

    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("a stale or conflicting request cannot post")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = _channel(client, store, [_AT])
        with pytest.raises(HilChannelError, match="expired"):
            await channel.send(_request())
        await _park(store)
        await channel.reserve(_request())
        with pytest.raises(HilChannelError):
            await channel.send(replace(_request(), action_hash="other"))
        await _park(store, expiry=_AT - timedelta(seconds=1))
        assert await channel.reconcile_once() is True
        assert (await _record(store))["status"] == "held"


async def test_park_action_tampering_blocks_admission_before_http() -> None:
    store = InMemoryStateStore()
    await _park(store)
    parked = await store.read_state("hil_park:approval-1")
    assert parked is not None
    await store.write_state(
        "hil_park:approval-1",
        {**parked, "action": {**parked["action"], "target_resource_ref": "another-target"}},
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("tampered park cannot post"))
    ) as client:
        with pytest.raises(HilChannelError, match="binding changed"):
            await _channel(client, store, [_AT]).send(_request())
    assert await store.read_state_page("hil-slack-request:", limit=10) == ((), 0)


async def test_existing_dispatch_rejects_new_payload_even_if_park_drifted() -> None:
    store = InMemoryStateStore()
    await _park(store)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("conflicting payload cannot post"))
    ) as client:
        channel = _channel(client, store, [_AT])
        await channel.reserve(_request())
        parked = await store.read_state("hil_park:approval-1")
        assert parked is not None
        await store.write_state("hil_park:approval-1", {**parked, "correlation_id": "other"})
        with pytest.raises(HilChannelError, match="conflicts with its durable record"):
            await channel.send(replace(_request(), correlation_id="other"))
    assert (await _record(store))["status"] == "queued"


async def test_stale_claim_becomes_unknown_and_reminders_are_distinct() -> None:
    store = InMemoryStateStore()
    await _park(store)
    clock = [_AT]
    posts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(200, json={"ok": True, "channel": _CHANNEL, "ts": f"123.{posts}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = _channel(client, store, clock)
        await channel.reserve(_request())
        key = channel._key("approval-1", "initial")
        record = await store.read_state(key)
        assert record is not None
        await store.compare_and_set_state_with_audit(
            key,
            {**record, "status": "inflight", "revision": 1, "claim_until": _AT.isoformat()},
            expected_revision=0,
            audit_entry={"actor": "test", "action_kind": "test.claim", "mode": "shadow"},
        )
        assert await channel.reconcile_once() is True
        assert (await _record(store))["status"] == "unknown"
        assert posts == 0
        first = await channel.send(_request("approval-1:1"))
        second = await channel.send(_request("approval-1:2"))
        assert first.channel_ref != second.channel_ref
        assert posts == 2


async def test_post_acceptance_persistence_failure_never_returns_receipt() -> None:
    class FailingAcceptanceStore(InMemoryStateStore):
        async def compare_and_set_state_with_audit(
            self,
            key: str,
            value: Mapping[str, Any],
            *,
            expected_revision: int,
            audit_entry: Mapping[str, Any],
        ) -> bool:
            if value.get("status") == "accepted":
                raise RuntimeError("simulated persistence interruption")
            return await super().compare_and_set_state_with_audit(
                key, value, expected_revision=expected_revision, audit_entry=audit_entry
            )

    store = FailingAcceptanceStore()
    await _park(store)
    clock = [_AT]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"ok": True, "channel": _CHANNEL, "ts": "1.2"})
        )
    ) as client:
        with pytest.raises(RuntimeError, match="persistence interruption"):
            await _channel(client, store, clock).send(_request())
        assert (await _record(store))["status"] == "inflight"
        clock[0] += timedelta(seconds=31)
        assert await _channel(client, store, clock).reconcile_once() is True
        assert (await _record(store))["status"] == "unknown"


async def test_two_workers_claim_one_dispatch_and_reordered_replay_is_held() -> None:
    store = InMemoryStateStore()
    await _park(store)
    posts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal posts
        posts += 1
        return httpx.Response(200, json={"ok": True, "channel": _CHANNEL, "ts": "1.2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first, second = await asyncio.gather(
            _channel(client, store, [_AT]).send(_request()),
            _channel(client, store, [_AT]).send(_request()),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in (first, second)) >= 1
        assert (await _record(store))["status"] == "accepted"
        assert posts == 1
        with pytest.raises(HilChannelError, match="binding|conflicts|expired"):
            await _channel(client, store, [_AT]).send(replace(_request(), correlation_id="other"))
