"""Reclaim Heimdall checkpoint rows that the acknowledged checkpoint can no longer reach.

Heimdall's versioned sensing checkpoint is copy-on-write: every changed node, manifest, and
episode body is a new row and the root only ever points at the newest ones. The superseded rows
are recovery scaffolding, not evidence, and nothing removed them. This module deletes a row only
when all of the following hold:

* the layout is the verified versioned trie layout and the acknowledged root is the one in the
  store, so a writer elsewhere that advanced the checkpoint stops the run;
* the row is not reachable from that root (current version, manifest, and subject rows);
* the row has not been written for the minimum age, which keeps another writer's rows that are
  not yet published safe;
* the checkpoint writer is quiescent, because the run holds the writer's lock for each page.

A row that is deleted by mistake would make recovery fail closed ("repair required") rather than
silently lose a judgment, so the reachability rules mirror the reader exactly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from fdai.agents._framework.heimdall_constants import (
    _EPISODE_PREFIX,
    _PENDING_READINESS_PREFIX,
    _READINESS_PREFIX,
    _STATE_KEY,
)
from fdai.agents._framework.heimdall_sensing_persistence import (
    BUCKET_COUNT,
    MANIFEST_PREFIX,
    VERSION_PREFIX,
    bucket_key,
)
from fdai.shared.providers.state_store import StateStore, StateStoreAgedKeysetReader

MIN_ROW_AGE = timedelta(hours=1)
SCANNED_PREFIXES = (
    VERSION_PREFIX,
    MANIFEST_PREFIX,
    _EPISODE_PREFIX,
    _READINESS_PREFIX,
    _PENDING_READINESS_PREFIX,
)
_PAGE = 256
_PAGES_PER_RUN = 8
_DELETES_PER_RUN = 256
_MAX_STORE_NODES = 200_000


class CheckpointStateReader(Protocol):
    """The only store capability needed to prove which checkpoint rows are reachable."""

    async def read_state(self, key: str) -> Mapping[str, Any] | None: ...


def checkpoint_lock(agent: Any) -> asyncio.Lock:
    """Return the lock that serializes checkpoint writes with reclamation."""
    lock = getattr(agent, "_sensing_checkpoint_lock", None)
    if lock is None:
        lock = agent._sensing_checkpoint_lock = asyncio.Lock()
    return cast(asyncio.Lock, lock)


def reachable_from_memory(agent: Any) -> frozenset[str] | None:
    """Return every row the acknowledged checkpoint needs, or ``None`` when it is not provable."""
    if not (
        getattr(agent, "_sensing_versioned_layout", False)
        and getattr(agent, "_sensing_trie_layout", False)
    ):
        return None
    root = getattr(agent, "_persisted_sensing_records", {}).get(_STATE_KEY)
    commitment = root.get("bucket_digest") if isinstance(root, Mapping) else None
    digests = getattr(agent, "_persisted_sensing_digests", None)
    entries = getattr(agent, "_sensing_bucket_entries", None)
    if (
        root is None
        or root.get("immutable_records") is not True
        or not isinstance(commitment, str)
        or not isinstance(digests, dict)
        or not isinstance(entries, dict)
        or any(bucket_key(slot) not in digests for slot in range(BUCKET_COUNT))
    ):
        return None
    keys = {VERSION_PREFIX + str(digest) for digest in digests.values()}
    keys.add(MANIFEST_PREFIX + commitment)
    keys.update(key for key, entry in entries.items() if entry.get("family") != "metadata")
    return frozenset(keys)


async def reachable_from_store(store: CheckpointStateReader) -> frozenset[str] | None:
    """Traverse the stored root exactly as recovery does; ``None`` when any link is unreadable."""
    root = await store.read_state(_STATE_KEY)
    commitment = root.get("bucket_digest") if root is not None else None
    if root is None or root.get("immutable_records") is not True or not isinstance(commitment, str):
        return None
    manifest = await store.read_state(MANIFEST_PREFIX + commitment)
    digests = manifest.get("bucket_digests") if manifest is not None else None
    if not isinstance(digests, list) or len(digests) != BUCKET_COUNT:
        return None
    reachable = {MANIFEST_PREFIX + commitment}
    pending = [str(digest) for digest in digests]
    while pending:
        digest = pending.pop()
        key = VERSION_PREFIX + digest
        if key in reachable:
            continue
        if len(reachable) > _MAX_STORE_NODES:
            return None
        body = await store.read_state(key)
        if body is None:
            return None
        reachable.add(key)
        node_type = body.get("node_type")
        if node_type == "branch":
            children = body.get("children")
            if not isinstance(children, dict):
                return None
            pending.extend(str(child) for child in children.values())
        elif node_type == "fragment":
            parts = await _fragment_entries(store, body, reachable)
            if parts is None:
                return None
            _add_subjects(parts, reachable)
        elif node_type in (None, "leaf"):
            entries = body.get("entries")
            if not isinstance(entries, dict):
                return None
            _add_subjects(entries, reachable)
        else:
            return None
    return frozenset(reachable)


async def _fragment_entries(
    store: CheckpointStateReader, node: Mapping[str, Any], reachable: set[str]
) -> dict[str, Any] | None:
    count, head = node.get("count"), node.get("head")
    chunks: list[str] = []
    for _ in range(count if isinstance(count, int) and 0 < count <= 4_096 else 0):
        if not isinstance(head, str):
            return None
        key = VERSION_PREFIX + head
        chunk = await store.read_state(key)
        if chunk is None or not isinstance(chunk.get("data"), str):
            return None
        reachable.add(key)
        chunks.append(chunk["data"])
        head = chunk.get("next")
    if head is not None or not chunks:
        return None
    try:
        entries = json.loads("".join(chunks))
    except ValueError:
        return None
    return entries if isinstance(entries, dict) else None


def _add_subjects(entries: Mapping[str, Any], reachable: set[str]) -> None:
    for key, entry in entries.items():
        if not isinstance(entry, Mapping) or entry.get("family") == "metadata":
            continue
        reachable.add(key)
        digest = entry.get("digest")
        if isinstance(digest, str):
            reachable.add(VERSION_PREFIX + digest)


async def collect_unreachable_checkpoint_rows(
    agent: Any, *, now: datetime | None = None, min_age: timedelta = MIN_ROW_AGE
) -> int:
    """Delete one bounded batch of provably unreachable checkpoint rows and return its size."""
    reader = getattr(agent, "_state_store", None)
    if not isinstance(reader, StateStoreAgedKeysetReader):
        return 0
    store = cast(StateStore, reader)
    cutoff = (now or datetime.now(tz=UTC)) - min_age
    cursors: dict[str, str] | None = getattr(agent, "_checkpoint_gc_cursors", None)
    if cursors is None:
        cursors = agent._checkpoint_gc_cursors = {}
    deleted = 0
    for _ in range(_PAGES_PER_RUN):
        index = getattr(agent, "_checkpoint_gc_prefix", 0) % len(SCANNED_PREFIXES)
        prefix = SCANNED_PREFIXES[index]
        keys = await reader.read_state_keys_before(
            prefix, before=cutoff, after=cursors.get(prefix, ""), limit=_PAGE
        )
        if not keys:
            cursors.pop(prefix, None)
            agent._checkpoint_gc_prefix = index + 1
            continue
        async with checkpoint_lock(agent):
            reachable = reachable_from_memory(agent)
            acknowledged = agent._persisted_sensing_records.get(_STATE_KEY)
            if reachable is None or await store.read_state(_STATE_KEY) != acknowledged:
                return deleted
            for key in keys:
                if deleted >= _DELETES_PER_RUN:
                    return deleted
                if key not in reachable and await store.delete_state(key):
                    deleted += 1
                cursors[prefix] = key
    return deleted


__all__ = [
    "CheckpointStateReader",
    "MIN_ROW_AGE",
    "SCANNED_PREFIXES",
    "checkpoint_lock",
    "collect_unreachable_checkpoint_rows",
    "reachable_from_memory",
    "reachable_from_store",
]
