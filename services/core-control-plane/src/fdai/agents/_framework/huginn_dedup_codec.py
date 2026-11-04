"""Pure record codec and validators for the Huginn ingress dedup journal."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any


def _decode(
    record: Mapping[str, Any] | None,
) -> tuple[int, int | None, int, dict[str, dict[str, Any]]]:
    if record is None:
        return 0, None, 1, {}
    revision = record.get("revision")
    capacity = record.get("capacity")
    next_sequence = record.get("next_sequence")
    raw_entries = record.get("entries")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("Huginn dedup revision MUST be positive")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise ValueError("Huginn dedup capacity MUST be positive")
    if isinstance(next_sequence, bool) or not isinstance(next_sequence, int) or next_sequence < 1:
        raise ValueError("Huginn dedup next sequence MUST be positive")
    if not isinstance(raw_entries, Mapping) or len(raw_entries) > capacity:
        raise ValueError("Huginn dedup entries are malformed")
    entries: dict[str, dict[str, Any]] = {}
    sequences: set[int] = set()
    for key, raw_entry in raw_entries.items():
        if not isinstance(key, str) or not key or not isinstance(raw_entry, Mapping):
            raise ValueError("Huginn dedup entry is malformed")
        entry = dict(raw_entry)
        digest = entry.get("request_digest")
        status = entry.get("status")
        sequence = entry.get("sequence")
        if (
            not _is_digest(digest)
            or status not in {"pending", "published"}
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or sequence in sequences
            or sequence >= next_sequence
        ):
            raise ValueError("Huginn dedup entry identity is malformed")
        sequences.add(sequence)
        if status == "pending":
            if (
                not isinstance(entry.get("owner_token"), str)
                or not entry["owner_token"]
                or not isinstance(entry.get("lease_expires_at"), str)
                or not isinstance(entry.get("payload"), Mapping)
                or entry.get("change_projection") is not None
                and not isinstance(entry.get("change_projection"), Mapping)
            ):
                raise ValueError("Huginn pending dedup entry is malformed")
            _parse_time(entry["lease_expires_at"])
            _published_topics(entry)
        elif any(
            (
                entry.get("owner_token") != "",
                entry.get("lease_expires_at") != "",
                entry.get("payload") is not None,
                entry.get("change_projection") is not None,
            )
        ):
            raise ValueError("Huginn published dedup entry retains pending state")
        entries[key] = entry
    return revision, capacity, next_sequence, entries


def _encode(
    *,
    revision: int,
    capacity: int,
    next_sequence: int,
    entries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "capacity": capacity,
        "next_sequence": next_sequence,
        "entries": {key: dict(entry) for key, entry in entries.items()},
    }


def _published_topics(entry: Mapping[str, Any]) -> tuple[str, ...]:
    raw_topics = entry.get("published_topics", ())
    if raw_topics in (None, ()):
        return ()
    if not isinstance(raw_topics, list | tuple):
        raise ValueError("Huginn published topic markers are malformed")
    topics: list[str] = []
    for topic in raw_topics:
        if topic not in {"object.event", "object.change"} or topic in topics:
            raise ValueError("Huginn published topic marker is invalid")
        topics.append(topic)
    return tuple(topics)


def _validate_request(
    entry: Mapping[str, Any],
    *,
    request_digest: str,
    legacy_request_digest: str | None = None,
) -> None:
    retained = entry.get("request_digest")
    if retained != request_digest and (
        legacy_request_digest is None or retained != legacy_request_digest
    ):
        raise ValueError("Huginn idempotency key collides with another raw request")


def _json_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Huginn dedup {field} MUST be an object")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Huginn dedup {field} MUST be canonical JSON") from exc
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"Huginn dedup {field} MUST be an object")
    return decoded


def _clock_now(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Huginn dedup clock MUST be timezone-aware")
    return now.astimezone(UTC)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Huginn dedup lease timestamp is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Huginn dedup lease timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])
