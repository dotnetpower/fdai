"""Durable ordered-poison halt markers for the event-bus bridge."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.compatibility import canonical_digest

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
    marker["halt_record_digest"] = halt_record_digest(marker)
    state_key = halt_key(group_id, topic)
    if await store.write_state_if_absent(state_key, marker):
        return
    stored = await store.read_state(state_key)
    if not isinstance(stored, Mapping) or stored.get("status") not in {"halted", "cleared"}:
        raise RuntimeError("ordered poison halt marker is malformed")
    if stored.get("status") == "cleared":
        revision = int(stored.get("revision", 1))
        replacement = {**marker, "revision": revision + 1}
        replacement["halt_record_digest"] = halt_record_digest(replacement)
        await store.compare_and_set_state(
            state_key,
            replacement,
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


async def clear_ordered_halt_with_evidence(
    store: StateStore | None,
    *,
    group_id: str,
    topic: str,
    expected_revision: int,
    expected_halt_digest: str,
    parked_record_evidence: Mapping[str, Any],
    audit_entry: Mapping[str, Any],
) -> bool:
    if store is None:
        return False
    state_key = halt_key(group_id, topic)
    stored = await store.read_state(state_key)
    if stored is None:
        return False
    if stored.get("status") == "cleared":
        return _existing_clear_matches(stored, parked_record_evidence)
    if stored.get("status") != "halted":
        raise RuntimeError("ordered poison halt marker is malformed")
    revision = int(stored.get("revision", 1))
    if revision != expected_revision:
        return False
    if halt_record_digest(stored) != expected_halt_digest:
        return False
    if not _parked_evidence_matches_halt(stored, parked_record_evidence):
        return False
    cleared = {
        **dict(stored),
        "status": "cleared",
        "revision": revision + 1,
        "clear_evidence": dict(parked_record_evidence),
    }
    cleared["clear_record_digest"] = halt_record_digest(cleared)
    return await store.compare_and_set_state_with_audit(
        state_key,
        cleared,
        expected_revision=revision,
        audit_entry=audit_entry,
    )


def halt_record_digest(record: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            key: value
            for key, value in dict(record).items()
            if key not in {"halt_record_digest", "clear_record_digest"}
        }
    )


def halt_key(group_id: str, topic: str) -> str:
    return f"pantheon/bus/ordered-poison-halt/{group_id}/{topic}"


__all__ = [
    "clear_ordered_halt",
    "clear_ordered_halt_with_evidence",
    "halt_record_digest",
    "is_ordered_halted",
    "persist_ordered_halt",
]


def _existing_clear_matches(
    stored: Mapping[str, Any],
    parked_record_evidence: Mapping[str, Any],
) -> bool:
    existing = stored.get("clear_evidence")
    return isinstance(existing, Mapping) and dict(existing) == dict(parked_record_evidence)


def _parked_evidence_matches_halt(
    stored: Mapping[str, Any],
    parked_record_evidence: Mapping[str, Any],
) -> bool:
    if parked_record_evidence.get("parked_record_key") != stored.get("partition_key"):
        return False
    if parked_record_evidence.get("parked_record_offset") != stored.get("offset"):
        return False
    metadata = parked_record_evidence.get("parked_record_metadata")
    if not isinstance(metadata, Mapping):
        return False
    return (
        metadata.get("consumer_group") == stored.get("group_id")
        and metadata.get("topic") == stored.get("topic")
        and metadata.get("offset") == stored.get("offset")
    )
