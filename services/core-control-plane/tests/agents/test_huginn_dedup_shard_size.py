"""Huginn dedup shards keep only in-flight claims; completed keys live in terminal receipts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fdai.agents._framework.huginn_dedup import (
    HuginnClaimInProgressError,
    HuginnDedupJournal,
    _terminal_key,
    request_digest,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 11, 4, tzinfo=UTC)
SHARDS = "pantheon/huginn/ingress-dedup/shard-"


def _raw(key: str) -> dict[str, Any]:
    return {"idempotency_key": key, "event_type": "inventory.resource_observed", "n": key}


async def _ingest(journal: HuginnDedupJournal, key: str) -> None:
    raw = _raw(key)
    digest = request_digest(raw)
    claim = await journal.claim(
        idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
    )
    assert not claim.duplicate
    await journal.mark_published(idempotency_key=key, request_digest=digest, topic="object.event")
    await journal.complete(
        idempotency_key=key, request_digest=digest, require_published_topics=True
    )


async def _shard_bytes(store: InMemoryStateStore) -> int:
    rows = await store.read_states(SHARDS, limit=1_000)
    return sum(len(json.dumps(row)) for row in rows)


async def test_shards_do_not_grow_with_completed_events() -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=1_000, clock=lambda: NOW)

    for index in range(300):
        await _ingest(journal, f"event:{index}")

    assert await _shard_bytes(store) < 20_000
    for index in (0, 150, 299):
        raw = _raw(f"event:{index}")
        again = await journal.claim(
            idempotency_key=f"event:{index}",
            request_digest=request_digest(raw),
            payload=raw,
            change_projection=None,
        )
        assert again.duplicate


async def test_completion_and_publication_markers_are_idempotent_after_completion() -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    await _ingest(journal, "event:1")
    digest = request_digest(_raw("event:1"))

    await journal.complete(idempotency_key="event:1", request_digest=digest)
    await journal.mark_published(
        idempotency_key="event:1", request_digest=digest, topic="object.event"
    )


async def test_completing_an_unknown_claim_still_fails_closed() -> None:
    journal = HuginnDedupJournal(InMemoryStateStore(), capacity=64, clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="disappeared"):
        await journal.complete(
            idempotency_key="event:never", request_digest=request_digest(_raw("event:never"))
        )
    with pytest.raises(RuntimeError, match="disappeared"):
        await journal.mark_published(
            idempotency_key="event:never",
            request_digest=request_digest(_raw("event:never")),
            topic="object.event",
        )


@pytest.mark.parametrize("rejection", ["digest", "owner", "event", "change"])
async def test_rejected_completion_never_records_a_terminal_receipt(rejection: str) -> None:
    store = InMemoryStateStore()
    owner = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    key = "event:rejected"
    raw = _raw(key)
    digest = request_digest(raw)
    await owner.claim(
        idempotency_key=key,
        request_digest=digest,
        payload=raw,
        change_projection={"id": "change:1"} if rejection == "change" else None,
    )
    if rejection != "event":
        await owner.mark_published(idempotency_key=key, request_digest=digest, topic="object.event")
    caller = (
        HuginnDedupJournal(store, capacity=64, clock=lambda: NOW) if rejection == "owner" else owner
    )
    error = {
        "digest": ValueError,
        "owner": HuginnClaimInProgressError,
        "event": RuntimeError,
        "change": RuntimeError,
    }[rejection]
    with pytest.raises(error):
        await caller.complete(
            idempotency_key=key,
            request_digest=(
                request_digest({**raw, "n": "other"}) if rejection == "digest" else digest
            ),
            require_published_topics=True,
        )

    assert await store.read_state(_terminal_key(key)) is None
    if rejection == "event":
        await owner.mark_published(idempotency_key=key, request_digest=digest, topic="object.event")
    if rejection == "change":
        await owner.mark_published(
            idempotency_key=key, request_digest=digest, topic="object.change"
        )
    await owner.complete(idempotency_key=key, request_digest=digest, require_published_topics=True)
    duplicate = await owner.claim(
        idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
    )
    assert duplicate.duplicate


async def test_exhausted_completion_fence_never_records_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    key = "event:contended"
    raw = _raw(key)
    digest = request_digest(raw)
    await journal.claim(
        idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
    )
    await journal.mark_published(idempotency_key=key, request_digest=digest, topic="object.event")
    with monkeypatch.context() as context:
        advance = AsyncMock(return_value=False)
        context.setattr(journal, "_advance", advance)
        with pytest.raises(RuntimeError, match="contention"):
            await journal.complete(
                idempotency_key=key, request_digest=digest, require_published_topics=True
            )
        assert advance.await_count == 8
    assert await store.read_state(_terminal_key(key)) is None
    await journal.complete(
        idempotency_key=key, request_digest=digest, require_published_topics=True
    )


async def test_completed_checkpoint_recovers_after_receipt_write_interruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    key = "event:interrupted"
    raw = _raw(key)
    digest = request_digest(raw)
    await journal.claim(
        idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
    )
    await journal.mark_published(idempotency_key=key, request_digest=digest, topic="object.event")
    with monkeypatch.context() as context:
        context.setattr(
            store, "write_state_if_absent", AsyncMock(side_effect=OSError("interrupted"))
        )
        with pytest.raises(OSError, match="interrupted"):
            await journal.complete(
                idempotency_key=key, request_digest=digest, require_published_topics=True
            )
    assert await store.read_state(_terminal_key(key)) is None
    restarted = HuginnDedupJournal(store, capacity=64, clock=lambda: NOW)
    duplicate = await restarted.claim(
        idempotency_key=key, request_digest=digest, payload=raw, change_projection=None
    )
    assert duplicate.duplicate
    assert await store.read_state(_terminal_key(key)) is not None


async def test_completed_entries_of_the_older_layout_gain_receipts_before_removal() -> None:
    store = InMemoryStateStore()
    journal = HuginnDedupJournal(store, capacity=1, clock=lambda: NOW)
    raw = _raw("event:legacy")
    digest = request_digest(raw)
    shard_key = f"{SHARDS}00"
    await store.write_state(
        shard_key,
        {
            "schema_version": "1.0.0",
            "revision": 1,
            "capacity": 1,
            "next_sequence": 2,
            "entries": {
                "event:legacy": {
                    "request_digest": digest,
                    "status": "published",
                    "owner_token": "",
                    "lease_expires_at": "",
                    "sequence": 1,
                    "payload": None,
                    "change_projection": None,
                }
            },
        },
    )

    claim = await journal.claim(
        idempotency_key="event:legacy", request_digest=digest, payload=raw, change_projection=None
    )

    assert claim.duplicate
    receipt = await store.read_state(_terminal_key("event:legacy"))
    assert receipt is not None and receipt["request_digest"] == digest
    shard = await store.read_state(shard_key)
    assert shard is not None and shard["entries"] == {}
    assert "event:legacy" in await journal.published_keys()
