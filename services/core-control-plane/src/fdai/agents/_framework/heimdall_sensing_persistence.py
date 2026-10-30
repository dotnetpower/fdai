"""Exact write reuse and ordered subject recovery for Heimdall sensing state."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from fdai.agents._framework.heimdall_alert_window import MAX_TRACKED_KEYS
from fdai.agents._framework.heimdall_constants import (
    _EPISODE_PREFIX,
    _PENDING_READINESS_PREFIX,
    _READINESS_PREFIX,
    _STATE_KEY,
)

SUBJECT_LAYOUT = "subject-records-v1"
BUCKET_LAYOUT = "subject-buckets-v2"
BUCKET_COUNT = 64
BUCKET_PREFIX = _STATE_KEY + "/buckets/"


def bucket_key(slot: int) -> str:
    return f"{BUCKET_PREFIX}{slot:02d}"


def _bucket_slot(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % BUCKET_COUNT


def _bucket_commitment(digests: list[str]) -> str:
    return hashlib.sha256(json.dumps(digests, separators=(",", ":")).encode()).hexdigest()


def _active_subjects(agent: Any) -> list[tuple[str, str, str]]:
    return [
        *(
            ("episode", _EPISODE_PREFIX, json.dumps(key, ensure_ascii=True, separators=(",", ":")))
            for key in agent._recent_events
        ),
        *(("readiness", _READINESS_PREFIX, resource) for resource in agent._detection_readiness),
        *(
            (
                "pending",
                _PENDING_READINESS_PREFIX,
                json.dumps((resource, pass_id), ensure_ascii=True, separators=(",", ":")),
            )
            for resource, pass_id in agent._detection_readiness_pending
        ),
    ]


def _subject_storage_key(family: str, prefix: str, identity: str) -> str:
    if family == "pending":
        resource, pass_id = _pending_pair(identity)
        identity = resource + "\0" + pass_id
    return subject_key(prefix, identity)


async def persist_bucket_checkpoint(agent: Any) -> None:
    """Update hash-stable buckets only; insertion ranks never shift on eviction."""
    previous = getattr(agent, "_sensing_bucket_entries", {})
    next_ordinal = getattr(agent, "_sensing_next_ordinal", 0)
    entries: dict[str, dict[str, Any]] = {}
    previous_rank: dict[str, int] = {}
    for family, prefix, identity in _active_subjects(agent):
        key = _subject_storage_key(family, prefix, identity)
        old = previous.get(key)
        rank = old["rank"] if old is not None else -1
        if rank <= previous_rank.get(family, -1):
            rank = next_ordinal
            next_ordinal += 1
        previous_rank[family] = rank
        entry = {
            "family": family,
            "identity": identity,
            "rank": rank,
            "digest": agent._persisted_sensing_digests[key],
        }
        if family == "episode":
            episode = tuple(json.loads(identity))
            entry["incident_id"] = agent._incident_episode_ids.get(episode)
            entry["incident_severity"] = agent._incident_episode_severities.get(episode)
        entries[key] = entry
    metadata = {
        "security_recent": list(agent._security_recent),
        "alert_windows": {key: list(value) for key, value in agent._alert_windows.items()},
        "detection_readiness_pass_order": {
            resource: [pass_id, observed.isoformat()]
            for resource, (pass_id, observed) in agent._detection_readiness_pass_order.items()
        },
        "incident_episode_ids": {
            json.dumps(key, ensure_ascii=True, separators=(",", ":")): value
            for key, value in agent._incident_episode_ids.items()
            if key not in agent._recent_events
        },
        "incident_episode_severities": {
            json.dumps(key, ensure_ascii=True, separators=(",", ":")): value
            for key, value in agent._incident_episode_severities.items()
            if key not in agent._recent_events
        },
    }
    for field, values in metadata.items():
        items = {"window": values} if field == "security_recent" and values else values
        for identity, value in items.items() if isinstance(items, dict) else ():
            key = "metadata:" + json.dumps(
                (field, identity), ensure_ascii=True, separators=(",", ":")
            )
            entries[key] = {
                "family": "metadata",
                "field": field,
                "identity": identity,
                "value": value,
            }
    changed = {
        key for key in previous.keys() | entries.keys() if previous.get(key) != entries.get(key)
    }
    dirty_subjects = {
        *(
            subject_key(_EPISODE_PREFIX, json.dumps(key, separators=(",", ":")))
            for key in agent._dirty_episode_keys
        ),
        *(
            subject_key(_READINESS_PREFIX, resource)
            for resource in agent._dirty_readiness_resources
        ),
        *(
            subject_key(_PENDING_READINESS_PREFIX, resource + "\0" + pass_id)
            for resource, pass_id in agent._dirty_pending_readiness
        ),
    }
    slots = {
        _bucket_slot(key) for key in changed | dirty_subjects if key in entries or key in previous
    }
    if not getattr(agent, "_sensing_bucket_layout", False):
        slots.update(range(BUCKET_COUNT))
    for slot in sorted(slots):
        body = {
            "schema_version": "1.0.0",
            "slot": slot,
            "entries": {key: value for key, value in entries.items() if _bucket_slot(key) == slot},
        }
        await write_changed_state(agent, bucket_key(slot), body)
    root = {
        "schema_version": "1.0.0",
        "revision": 1,
        "storage_layout": BUCKET_LAYOUT,
        "bucket_digest": _bucket_commitment(
            [agent._persisted_sensing_digests[bucket_key(slot)] for slot in range(BUCKET_COUNT)]
        ),
        "next_ordinal": next_ordinal,
    }
    await write_changed_state(agent, _STATE_KEY, root)
    agent._sensing_bucket_entries = entries
    agent._sensing_next_ordinal = next_ordinal
    agent._sensing_bucket_layout = True
    agent._sensing_subject_layout = True
    active = {_STATE_KEY, *entries, *(bucket_key(slot) for slot in range(BUCKET_COUNT))}
    agent._persisted_sensing_records = {
        key: value for key, value in agent._persisted_sensing_records.items() if key in active
    }
    agent._persisted_sensing_digests = {
        key: value for key, value in agent._persisted_sensing_digests.items() if key in active
    }


async def read_bucket_records(
    agent: Any, record: Mapping[str, Any]
) -> tuple[
    list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]], dict[str, Any]
]:
    """Verify root, buckets and subject bodies before restoring any sensing projection."""
    digests = record.get("bucket_digests")
    expected_commitment = record.get("bucket_digest")
    next_ordinal = record.get("next_ordinal")
    if (
        not (
            (isinstance(digests, list) and len(digests) == BUCKET_COUNT)
            or isinstance(expected_commitment, str)
        )
        or not isinstance(next_ordinal, int)
        or isinstance(next_ordinal, bool)
        or next_ordinal < 0
    ):
        raise ValueError("Heimdall sensing bucket manifest invalid; repair required")
    entries: dict[str, Any] = {}
    agent._persisted_sensing_digests = {}
    observed_digests: list[str] = []
    for slot in range(BUCKET_COUNT):
        key = bucket_key(slot)
        body = await agent._state_store.read_state(key)
        if body is None or body.get("slot") != slot:
            raise ValueError("Heimdall sensing checkpoint bucket digest mismatch; repair required")
        observed = _subject_digest(body)
        if isinstance(digests, list) and observed != digests[slot]:
            raise ValueError("Heimdall sensing checkpoint bucket digest mismatch; repair required")
        observed_digests.append(observed)
        raw_entries = body.get("entries")
        if not isinstance(raw_entries, dict):
            raise ValueError("Heimdall sensing checkpoint bucket entries invalid; repair required")
        for entry_key, entry in raw_entries.items():
            if (
                _bucket_slot(entry_key) != slot
                or entry_key in entries
                or not isinstance(entry, dict)
            ):
                raise ValueError(
                    "Heimdall sensing checkpoint bucket membership invalid; repair required"
                )
            entries[entry_key] = entry
        agent._persisted_sensing_records[key] = deepcopy(dict(body))
        agent._persisted_sensing_digests[key] = observed
    if (
        expected_commitment is not None
        and _bucket_commitment(observed_digests) != expected_commitment
    ):
        raise ValueError("Heimdall sensing checkpoint bucket digest mismatch; repair required")
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = {
        "episode": [],
        "readiness": [],
        "pending": [],
    }
    metadata: dict[str, Any] = {
        "incident_episode_ids": {},
        "incident_episode_severities": {},
        "detection_readiness_pass_order": {},
        "alert_windows": {},
        "security_recent": [],
    }
    ranks: set[int] = set()
    prefixes = {
        "episode": _EPISODE_PREFIX,
        "readiness": _READINESS_PREFIX,
        "pending": _PENDING_READINESS_PREFIX,
    }
    for key, entry in entries.items():
        family = entry.get("family")
        identity = entry.get("identity")
        if family == "metadata":
            field = entry.get("field")
            if field not in metadata or not isinstance(identity, str):
                raise ValueError("Heimdall sensing checkpoint metadata invalid; repair required")
            if field == "security_recent":
                metadata[field] = entry["value"]
            else:
                metadata[field][identity] = entry["value"]
            continue
        rank = entry.get("rank")
        if (
            family not in prefixes
            or not isinstance(identity, str)
            or not isinstance(rank, int)
            or isinstance(rank, bool)
            or rank < 0
            or rank >= next_ordinal
            or rank in ranks
            or _subject_storage_key(family, prefixes[family], identity) != key
        ):
            raise ValueError(
                "Heimdall sensing checkpoint subject reference invalid; repair required"
            )
        ranks.add(rank)
        row = await agent._state_store.read_state(key)
        if row is None:
            raise ValueError("Heimdall sensing manifest references missing subject state")
        if _subject_digest(row) != entry.get("digest"):
            raise ValueError("Heimdall sensing checkpoint subject digest mismatch; repair required")
        if family == "episode":
            if row.get("episode_key") != identity:
                raise ValueError("Heimdall sensing checkpoint subject identity mismatch")
            for field, attribute in (
                ("incident_episode_ids", "incident_id"),
                ("incident_episode_severities", "incident_severity"),
            ):
                if entry.get(attribute) is not None:
                    metadata[field][identity] = entry[attribute]
        elif family == "readiness" and row.get("resource_id") != identity:
            raise ValueError("Heimdall sensing checkpoint subject identity mismatch")
        elif family == "pending" and (row.get("resource_id"), row.get("pass_id")) != _pending_pair(
            identity
        ):
            raise ValueError("Heimdall sensing checkpoint subject identity mismatch")
        grouped[family].append((rank, row))
        agent._persisted_sensing_records[key] = deepcopy(dict(row))
        agent._persisted_sensing_digests[key] = entry["digest"]
    agent._sensing_bucket_entries = entries
    agent._sensing_next_ordinal = next_ordinal
    agent._sensing_bucket_layout = True
    ordered = [
        list(reversed([row for _, row in sorted(grouped[family])]))
        for family in ("episode", "readiness", "pending")
    ]
    return ordered[0], ordered[1], ordered[2], metadata


def subject_key(prefix: str, identity: str) -> str:
    return prefix + hashlib.sha256(identity.encode("utf-8")).hexdigest()


async def write_changed_state(agent: Any, key: str, value: dict[str, Any]) -> bool:
    """Reuse only an exactly equal, acknowledged durable write, never a failed attempt."""
    cache = getattr(agent, "_persisted_sensing_records", None)
    if cache is None:
        cache = agent._persisted_sensing_records = {}
    if cache.get(key) == value:
        # Another instance can have advanced the shared row since our acknowledgment.
        if await agent._state_store.read_state(key) == value:
            return False
    await agent._state_store.write_state(key, value)
    cache[key] = deepcopy(value)
    if key != _STATE_KEY:
        digests = getattr(agent, "_persisted_sensing_digests", None)
        if digests is None:
            digests = agent._persisted_sensing_digests = {}
        digests[key] = _subject_digest(value)
    return True


async def read_subject_records(
    agent: Any, record: Mapping[str, Any]
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Resolve the exact active membership and insertion order, ignoring orphan rows."""
    groups: list[list[Mapping[str, Any]]] = []
    ordered_keys: list[str] = []
    agent._persisted_sensing_digests = {}
    for field, prefix, identity_field in (
        ("episode_order", _EPISODE_PREFIX, "episode_key"),
        ("readiness_order", _READINESS_PREFIX, "resource_id"),
        ("pending_readiness_order", _PENDING_READINESS_PREFIX, None),
    ):
        identities = record.get(field)
        if (
            not isinstance(identities, list)
            or len(identities) > MAX_TRACKED_KEYS
            or not all(isinstance(item, str) for item in identities)
            or len(set(identities)) != len(identities)
        ):
            raise ValueError(f"Heimdall sensing manifest has invalid {field}")
        rows: list[Mapping[str, Any]] = []
        for identity in identities:
            pending_pair: tuple[str, str] | None = None
            hash_identity = identity
            if identity_field is None:
                # Only the manifest encoding changes; existing subject keys remain stable.
                pending_pair = _pending_pair(identity)
                hash_identity = pending_pair[0] + "\0" + pending_pair[1]
            key = subject_key(prefix, hash_identity)
            row = await agent._state_store.read_state(key)
            if row is None:
                raise ValueError("Heimdall sensing manifest references missing subject state")
            identity_matches = (
                row.get(identity_field) == identity
                if identity_field is not None
                else (row.get("resource_id"), row.get("pass_id")) == pending_pair
            )
            if not identity_matches:
                raise ValueError("Heimdall sensing manifest subject identity mismatch")
            agent._persisted_sensing_records[key] = deepcopy(dict(row))
            agent._persisted_sensing_digests[key] = _subject_digest(row)
            ordered_keys.append(key)
            rows.append(row)
        # Existing recovery consumes newest-first pages in reverse order.
        groups.append(list(reversed(rows)))
    if record.get("subject_digest") != checkpoint_digest(agent, ordered_keys):
        raise ValueError("Heimdall sensing checkpoint subject digest mismatch; repair required")
    return groups[0], groups[1], groups[2]


def checkpoint_digest(agent: Any, ordered_keys: list[str]) -> str:
    """Commit every active subject and its ordering without copying subject bodies."""
    digests = getattr(agent, "_persisted_sensing_digests", None)
    if digests is None:
        digests = agent._persisted_sensing_digests = {}
    try:
        material = [(key, digests[key]) for key in ordered_keys]
    except KeyError as exc:
        raise ValueError(
            "Heimdall sensing checkpoint subject digest missing; repair required"
        ) from exc
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def _subject_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            _canonical_numbers(value),
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _canonical_numbers(value: Any) -> Any:
    # JSONB can spell integral numbers differently; their exact numeric value is unchanged.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {key: _canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_canonical_numbers(item) for item in value]
    return value


def _pending_pair(identity: str) -> tuple[str, str]:
    """Read JSON-safe pairs and the earlier in-memory-only NUL representation."""
    if "\0" in identity:
        resource, pass_id = identity.split("\0", 1)
        return resource, pass_id
    try:
        pair = json.loads(identity)
    except ValueError as exc:
        raise ValueError("Heimdall sensing manifest has invalid pending identity") from exc
    if (
        not isinstance(pair, list)
        or len(pair) != 2
        or not all(isinstance(item, str) for item in pair)
    ):
        raise ValueError("Heimdall sensing manifest has invalid pending identity")
    return pair[0], pair[1]
