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
