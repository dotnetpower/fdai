"""Durable ordered-poison halt markers for the event-bus bridge."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.providers.state_store import StateStore


async def is_ordered_halted(store: StateStore | None, *, group_id: str, topic: str) -> bool:
    if store is None:
        return False
    stored = await store.read_state(halt_key(group_id, topic))
    if stored is None or stored.get("status") == "cleared":
        return False
    if stored.get("status") != "halted":
        raise RuntimeError("ordered poison halt marker is malformed")
    return True


async def persist_ordered_halt(
    store: StateStore | None,
    *,
    consumer_id: str,
    group_id: str,
    topic: str,
    offset: int,
    key: str,
) -> None:
    if store is None:
        return
    marker = {
        "schema_version": "1.0.0",
        "revision": 1,
        "status": "halted",
        "consumer_id": consumer_id,
        "group_id": group_id,
        "topic": topic,
        "partition_key": key,
        "offset": offset,
    }
    state_key = halt_key(group_id, topic)
    if await store.write_state_if_absent(state_key, marker):
        return
    stored = await store.read_state(state_key)
    if not isinstance(stored, Mapping) or stored.get("status") not in {"halted", "cleared"}:
        raise RuntimeError("ordered poison halt marker is malformed")
    if stored.get("status") == "cleared":
        revision = int(stored.get("revision", 1))
        await store.compare_and_set_state(
            state_key,
            {**marker, "revision": revision + 1},
            expected_revision=revision,
        )


async def clear_ordered_halt(store: StateStore | None, *, group_id: str, topic: str) -> bool:
    if store is None:
        return False
    state_key = halt_key(group_id, topic)
    for _attempt in range(16):
        stored = await store.read_state(state_key)
        if stored is None:
            return False
        if stored.get("status") == "cleared":
            return True
        if stored.get("status") != "halted":
            raise RuntimeError("ordered poison halt marker is malformed")
        revision = int(stored.get("revision", 1))
        advanced = await store.compare_and_set_state(
            state_key,
            {**dict(stored), "status": "cleared", "revision": revision + 1},
            expected_revision=revision,
        )
        if advanced:
            return True
    raise RuntimeError("ordered poison halt clear CAS retry limit exceeded")


def halt_key(group_id: str, topic: str) -> str:
    return f"pantheon/bus/ordered-poison-halt/{group_id}/{topic}"


__all__ = ["clear_ordered_halt", "is_ordered_halted", "persist_ordered_halt"]
