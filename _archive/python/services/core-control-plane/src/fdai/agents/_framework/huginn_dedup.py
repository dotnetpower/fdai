"""Durable Huginn ingress deduplication with lease-fenced retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.agents._framework.huginn_dedup_codec import (
    _clock_now,
    _decode,
    _encode,
    _json_mapping,
    _parse_time,
    _published_topics,
    _validate_request,
)
from fdai.shared.providers.state_store import StateStore

_LEGACY_STATE_KEY = "pantheon/huginn/ingress-dedup"
_SHARD_PREFIX = _LEGACY_STATE_KEY + "/shard-"
_TERMINAL_PREFIX = _LEGACY_STATE_KEY + "/terminal/"
_MAX_SHARDS = 64
_MAX_CAS_ATTEMPTS = 8
_DEFAULT_LEASE = timedelta(seconds=60)
_MAX_LEASE = timedelta(minutes=5)
_TERMINAL_RETENTION_MULTIPLIER = 4
# The terminal window is pruned every N completions, N scaling with capacity up to this ceiling;
# per-completion pruning scanned the whole prefix for a handful of rows.
_MAX_TERMINAL_PRUNE_INTERVAL = 256


class HuginnClaimInProgressError(RuntimeError):
    """Raised so broker retry retains an ingress claim owned by another replica."""


@dataclass(frozen=True, slots=True)
class HuginnIngressClaim:
    payload: dict[str, Any]
    change_projection: dict[str, Any] | None
    duplicate: bool = False
    published_topics: frozenset[str] = frozenset()


class HuginnDedupJournal:
    """Linearize ingress keys while retaining retryable normalized payloads."""

    def __init__(
        self,
        store: StateStore,
        *,
        capacity: int,
        clock: Callable[[], datetime] | None = None,
        claim_lease: timedelta = _DEFAULT_LEASE,
    ) -> None:
        if capacity < 1:
            raise ValueError("dedup capacity MUST be positive")
        if claim_lease <= timedelta(0) or claim_lease > _MAX_LEASE:
            raise ValueError("dedup claim lease MUST be positive and at most five minutes")
        self._store = store
        self._capacity = capacity
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._claim_lease = claim_lease
        self._owner_token = uuid4().hex
        self._shard_count = min(_MAX_SHARDS, capacity)
        self._terminal_retention = max(capacity + 1, capacity * _TERMINAL_RETENTION_MULTIPLIER)
        self._migration_lock = asyncio.Lock()
        self._migration_complete = False
        self._recovery_shard = 0
        self._compacted_shards: set[int] = set()
        self._prune_interval = max(1, min(_MAX_TERMINAL_PRUNE_INTERVAL, capacity // 64))
        self._completions_since_prune = self._prune_interval

    async def published_keys(self) -> tuple[str, ...]:
        """Return completed keys in oldest-to-newest retention order.

        Durable terminal receipts are retained for four process dedup windows. That
        bounds state-store growth while preserving completed-key duplicate fences for
        the supported redelivery window after a shard entry ages out.
        """
        await self._ensure_migrated()
        rows = await self._store.read_states(
            _TERMINAL_PREFIX,
            limit=self._terminal_retention,
        )
        retained_from_terminal = tuple(
            str(row["idempotency_key"])
            for row in reversed(rows)
            if row.get("status") == "published" and isinstance(row.get("idempotency_key"), str)
        )
        if len(retained_from_terminal) < self._capacity:
            states = await asyncio.gather(
                *(
                    self._store.read_state(self._shard_key(index))
                    for index in range(self._shard_count)
                )
            )
            entries: dict[str, dict[str, Any]] = {}
            for index, state in enumerate(states):
                _, stored_capacity, _, shard_entries = _decode(state)
                self._validate_capacity(stored_capacity, expected=self._shard_capacity(index))
                entries.update(shard_entries)
            published = sorted(
                (int(entry["sequence"]), key)
                for key, entry in entries.items()
                if entry["status"] == "published"
            )
            # Insertion-ordered keys move a terminal key to the end in constant time; a
            # repeated selection or list removal here was quadratic and stalled startup.
            retained = dict.fromkeys(key for _sequence, key in published)
            for key in retained_from_terminal:
                retained.pop(key, None)
                retained[key] = None
            return tuple(retained)[-self._capacity :]
        return retained_from_terminal[-self._capacity :]

    async def pending_inventory_claims(
        self,
    ) -> tuple[tuple[str, str, HuginnIngressClaim], ...]:
        """Page admitted inventory payloads without reconstructing a raw request."""
        await self._ensure_migrated()
        selected: list[tuple[str, str, HuginnIngressClaim]] = []
        for _ in range(self._shard_count):
            index = self._recovery_shard
            self._recovery_shard = (index + 1) % self._shard_count
            state = await self._store.read_state(self._shard_key(index))
            _, capacity, _, entries = _decode(state)
            self._validate_capacity(capacity, expected=self._shard_capacity(index))
            for key, entry in entries.items():
                if entry["status"] != "pending":
                    continue
                claim = _claim_from_entry(entry)
                if claim.payload.get("event_type") not in {
                    "inventory.resource_changed",
                    "inventory.resource_observed",
                }:
                    continue
                selected.append((key, str(entry["request_digest"]), claim))
                if len(selected) == 8:
                    return tuple(selected)
        return tuple(selected)

    async def claim(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        payload: Mapping[str, Any],
        change_projection: Mapping[str, Any] | None,
        legacy_request_digest: str | None = None,
    ) -> HuginnIngressClaim:
        """Claim one key or return its completed duplicate disposition."""
        await self._ensure_migrated()
        # Compact first: an older completed entry becomes its terminal receipt before the check.
        await self._compact_published(self._shard_index(idempotency_key))
        terminal = await self._store.read_state(_terminal_key(idempotency_key))
        if terminal is not None:
            await self._validate_terminal_request(
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                legacy_request_digest=legacy_request_digest,
            )
            return HuginnIngressClaim(payload={}, change_projection=None, duplicate=True)
        shard_index = self._shard_index(idempotency_key)
        state_key = self._shard_key(shard_index)
        capacity = self._shard_capacity(shard_index)
        now = _clock_now(self._clock)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(state_key)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity, expected=capacity)
            existing = entries.get(idempotency_key)
            if existing is not None:
                _validate_request(
                    existing,
                    request_digest=request_digest,
                    legacy_request_digest=legacy_request_digest,
                )
                if existing["request_digest"] != request_digest:
                    await self._advance(
                        state_key=state_key,
                        current=current,
                        revision=revision,
                        capacity=capacity,
                        next_sequence=next_sequence,
                        entries={
                            **entries,
                            idempotency_key: {**existing, "request_digest": request_digest},
                        },
                        audit={
                            "actor": "Huginn",
                            "action_kind": "ingress.request-digest.upgraded",
                            "idempotency_key": idempotency_key,
                        },
                    )
                    continue
                if existing["status"] == "published":
                    return HuginnIngressClaim(payload={}, change_projection=None, duplicate=True)
                if existing["owner_token"] == self._owner_token:
                    return _claim_from_entry(existing)
                lease_expires_at = _parse_time(existing["lease_expires_at"])
                if now < lease_expires_at:
                    raise HuginnClaimInProgressError(
                        f"ingress claim remains active until {lease_expires_at.isoformat()}"
                    )
                replacement = dict(existing)
                replacement["owner_token"] = self._owner_token
                replacement["lease_expires_at"] = (now + self._claim_lease).isoformat()
                next_entries = {**entries, idempotency_key: replacement}
                if await self._advance(
                    state_key=state_key,
                    current=current,
                    revision=revision,
                    capacity=capacity,
                    next_sequence=next_sequence,
                    entries=next_entries,
                    audit={
                        "actor": "Huginn",
                        "action_kind": "ingress.claim.recovered",
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "revision": revision + 1,
                    },
                ):
                    return _claim_from_entry(replacement)
                continue

            next_entries = dict(entries)
            if len(next_entries) >= capacity:
                evictable = min(
                    (
                        (key, int(entry["sequence"]))
                        for key, entry in next_entries.items()
                        if entry["status"] == "published"
                    ),
                    key=lambda item: item[1],
                    default=None,
                )
                if evictable is None:
                    raise RuntimeError("Huginn dedup journal has no completed entry to evict")
                del next_entries[evictable[0]]
            normalized_payload = _json_mapping(payload, field="payload")
            normalized_change = (
                _json_mapping(change_projection, field="change_projection")
                if change_projection is not None
                else None
            )
            entry = {
                "request_digest": request_digest,
                "status": "pending",
                "owner_token": self._owner_token,
                "lease_expires_at": (now + self._claim_lease).isoformat(),
                "sequence": next_sequence,
                "payload": normalized_payload,
                "change_projection": normalized_change,
            }
            next_entries[idempotency_key] = entry
            if await self._advance(
                state_key=state_key,
                current=current,
                revision=revision,
                capacity=capacity,
                next_sequence=next_sequence + 1,
                entries=next_entries,
            ):
                return _claim_from_entry(entry)
        raise RuntimeError("Huginn dedup claim contention exceeded the bounded retry limit")

    async def complete(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        require_published_topics: bool = False,
    ) -> None:
        """Checkpoint successful publication without retaining the payload body.

        The durable terminal receipt is the completed-key fence, so the shard keeps only
        in-flight claims. Rewriting a shard that also held every completed key cost one
        large row write per ingress event.
        """
        await self._ensure_migrated()
        shard_index = self._shard_index(idempotency_key)
        state_key = self._shard_key(shard_index)
        capacity = self._shard_capacity(shard_index)
        await self._compact_published(shard_index)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(state_key)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity, expected=capacity)
            existing = entries.get(idempotency_key)
            if existing is None:
                if await self._store.read_state(_terminal_key(idempotency_key)) is not None:
                    await self._validate_terminal_request(
                        idempotency_key=idempotency_key,
                        request_digest=request_digest,
                        legacy_request_digest=None,
                    )
                    return
                raise RuntimeError("Huginn ingress claim disappeared before completion")
            _validate_request(existing, request_digest=request_digest)
            if existing["status"] == "published":
                break
            if existing["owner_token"] != self._owner_token:
                raise HuginnClaimInProgressError("Huginn ingress claim belongs to another replica")
            published_topics = set(_published_topics(existing))
            required_topics = {"object.event"}
            if existing.get("change_projection") is not None:
                required_topics.add("object.change")
            if require_published_topics and not required_topics.issubset(published_topics):
                raise RuntimeError("Huginn ingress publication legs are incomplete")
            completed = {
                "request_digest": request_digest,
                "status": "published",
                "owner_token": "",
                "lease_expires_at": "",
                "sequence": existing["sequence"],
                "payload": None,
                "change_projection": None,
                "published_topics": sorted(required_topics),
            }
            if await self._advance(
                state_key=state_key,
                current=current,
                revision=revision,
                capacity=capacity,
                next_sequence=next_sequence,
                entries={**entries, idempotency_key: completed},
            ):
                break
        else:
            raise RuntimeError(
                "Huginn dedup completion contention exceeded the bounded retry limit"
            )
        # Fence completion before publishing its receipt; compaction remains restart-safe.
        self._compacted_shards.discard(shard_index)
        await self._compact_published(shard_index)
        await self._prune_terminals()

    async def mark_published(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        topic: str,
    ) -> None:
        """Durably record one downstream publication leg for retry resume."""
        if topic not in {"object.event", "object.change"}:
            raise ValueError("Huginn publication topic is unsupported")
        await self._ensure_migrated()
        shard_index = self._shard_index(idempotency_key)
        state_key = self._shard_key(shard_index)
        capacity = self._shard_capacity(shard_index)
        await self._compact_published(shard_index)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(state_key)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity, expected=capacity)
            existing = entries.get(idempotency_key)
            if existing is None:
                if await self._store.read_state(_terminal_key(idempotency_key)) is not None:
                    return
                raise RuntimeError("Huginn ingress claim disappeared before publication marker")
            _validate_request(existing, request_digest=request_digest)
            if existing["status"] == "published":
                return
            if existing["owner_token"] != self._owner_token:
                raise HuginnClaimInProgressError("Huginn ingress claim belongs to another replica")
            if topic == "object.change" and existing.get("change_projection") is None:
                raise ValueError("Huginn change publication marker has no change payload")
            published_topics = set(_published_topics(existing))
            if topic in published_topics:
                return
            published_topics.add(topic)
            marked = {**existing, "published_topics": sorted(published_topics)}
            if await self._advance(
                state_key=state_key,
                current=current,
                revision=revision,
                capacity=capacity,
                next_sequence=next_sequence,
                entries={**entries, idempotency_key: marked},
            ):
                return
        raise RuntimeError("Huginn publication marker contention exceeded the bounded retry limit")

    async def _prune_terminals(self) -> None:
        self._completions_since_prune += 1
        if self._completions_since_prune < self._prune_interval:
            return
        self._completions_since_prune = 0
        await self._store.delete_states_beyond(
            _TERMINAL_PREFIX,
            retain_newest=self._terminal_retention,
        )

    async def _compact_published(self, index: int) -> None:
        """Move completed entries of an older layout to their terminal receipts, once per shard.

        A receipt is written first, so the completed-key fence never narrows. The shard is
        then rewritten without those entries and stays as small as its in-flight claims.
        """
        if index in self._compacted_shards:
            return
        state_key = self._shard_key(index)
        capacity = self._shard_capacity(index)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(state_key)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity, expected=capacity)
            completed = {k: e for k, e in entries.items() if e["status"] == "published"}
            if not completed:
                self._compacted_shards.add(index)
                return
            for key, entry in completed.items():
                await self._store.write_state_if_absent(
                    _terminal_key(key),
                    {
                        "schema_version": "1.0.0",
                        "revision": 1,
                        "idempotency_key": key,
                        "request_digest": entry["request_digest"],
                        "status": "published",
                    },
                )
            if await self._advance(
                state_key=state_key,
                current=current,
                revision=revision,
                capacity=capacity,
                next_sequence=next_sequence,
                entries={k: e for k, e in entries.items() if k not in completed},
            ):
                self._compacted_shards.add(index)
                return
        raise RuntimeError("Huginn dedup shard compaction exceeded the bounded retry limit")

    async def _validate_terminal_request(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        legacy_request_digest: str | None,
    ) -> None:
        key = _terminal_key(idempotency_key)
        for _ in range(_MAX_CAS_ATTEMPTS):
            terminal = await self._store.read_state(key)
            if terminal is None:
                raise RuntimeError(
                    "Huginn completed ingress record disappeared during verification"
                )
            _validate_request(
                terminal,
                request_digest=request_digest,
                legacy_request_digest=legacy_request_digest,
            )
            if terminal["request_digest"] == request_digest:
                return
            revision = terminal.get("revision")
            if type(revision) is not int or revision < 1:
                raise ValueError("Huginn completed ingress revision MUST be positive")
            if await self._store.compare_and_set_state_with_audit(
                key,
                {**terminal, "revision": revision + 1, "request_digest": request_digest},
                expected_revision=revision,
                audit_entry={
                    "actor": "Huginn",
                    "action_kind": "ingress.request-digest.upgraded",
                    "idempotency_key": idempotency_key,
                },
            ):
                return
        raise RuntimeError("Huginn request digest upgrade exceeded the bounded retry limit")

    async def _advance(
        self,
        *,
        state_key: str,
        current: Mapping[str, Any] | None,
        revision: int,
        capacity: int,
        next_sequence: int,
        entries: Mapping[str, Mapping[str, Any]],
        audit: Mapping[str, Any] | None = None,
    ) -> bool:
        value = _encode(
            revision=revision + 1,
            capacity=capacity,
            next_sequence=next_sequence,
            entries=entries,
        )
        if current is None:
            if audit is None:
                return await self._store.write_state_if_absent(state_key, value)
            return await self._store.write_state_with_audit_if_absent(state_key, value, audit)
        if audit is None:
            return await self._store.compare_and_set_state(
                state_key,
                value,
                expected_revision=revision,
            )
        return await self._store.compare_and_set_state_with_audit(
            state_key,
            value,
            expected_revision=revision,
            audit_entry=audit,
        )

    def _validate_capacity(self, stored_capacity: int | None, *, expected: int) -> None:
        if stored_capacity is not None and stored_capacity != expected:
            raise ValueError("Huginn dedup capacity conflicts with durable state")

    def _shard_index(self, idempotency_key: str) -> int:
        digest = hashlib.sha256(idempotency_key.encode()).digest()
        return int.from_bytes(digest[:2], "big") % self._shard_count

    def _shard_key(self, index: int) -> str:
        return f"{_SHARD_PREFIX}{index:02x}"

    def _shard_capacity(self, index: int) -> int:
        base, remainder = divmod(self._capacity, self._shard_count)
        return base + (1 if index < remainder else 0)

    async def _ensure_migrated(self) -> None:
        if self._migration_complete:
            return
        async with self._migration_lock:
            if self._migration_complete:
                return
            for _ in range(_MAX_CAS_ATTEMPTS):
                current = await self._store.read_state(_LEGACY_STATE_KEY)
                revision, stored_capacity, _next_sequence, entries = _decode(current)
                self._validate_capacity(stored_capacity, expected=self._capacity)
                if not entries:
                    self._migration_complete = True
                    return
                grouped: dict[int, dict[str, dict[str, Any]]] = {}
                for key, entry in entries.items():
                    grouped.setdefault(self._shard_index(key), {})[key] = entry
                for index, legacy_entries in sorted(grouped.items()):
                    await self._merge_legacy_shard(index, legacy_entries)
                if await self._advance(
                    state_key=_LEGACY_STATE_KEY,
                    current=current,
                    revision=revision,
                    capacity=self._capacity,
                    next_sequence=1,
                    entries={},
                    audit={
                        "actor": "Huginn",
                        "action_kind": "ingress.claim.migrated",
                        "revision": revision + 1,
                        "shard_count": self._shard_count,
                    },
                ):
                    self._migration_complete = True
                    return
            raise RuntimeError("Huginn dedup migration contention exceeded the bounded retry limit")

    async def _merge_legacy_shard(
        self,
        index: int,
        legacy_entries: Mapping[str, Mapping[str, Any]],
    ) -> None:
        state_key = self._shard_key(index)
        capacity = self._shard_capacity(index)
        for _ in range(_MAX_CAS_ATTEMPTS):
            current = await self._store.read_state(state_key)
            revision, stored_capacity, next_sequence, entries = _decode(current)
            self._validate_capacity(stored_capacity, expected=capacity)
            merged = dict(entries)
            for key, entry in sorted(
                legacy_entries.items(), key=lambda item: int(item[1]["sequence"])
            ):
                existing = merged.get(key)
                if existing is not None:
                    _validate_request(existing, request_digest=str(entry["request_digest"]))
                    continue
                migrated = dict(entry)
                migrated["sequence"] = next_sequence
                next_sequence += 1
                merged[key] = migrated
            while len(merged) > capacity:
                evictable = min(
                    (
                        (key, entry)
                        for key, entry in merged.items()
                        if entry["status"] == "published"
                    ),
                    key=lambda item: int(item[1]["sequence"]),
                    default=None,
                )
                if evictable is None:
                    raise RuntimeError("Huginn dedup shard has no completed entry to evict")
                del merged[evictable[0]]
            if merged == entries:
                return
            if await self._advance(
                state_key=state_key,
                current=current,
                revision=revision,
                capacity=capacity,
                next_sequence=next_sequence,
                entries=merged,
                audit={
                    "actor": "Huginn",
                    "action_kind": "ingress.claim.shard_migrated",
                    "revision": revision + 1,
                    "shard": index,
                },
            ):
                return
        raise RuntimeError("Huginn dedup shard migration exceeded the bounded retry limit")


def request_digest(raw: Mapping[str, Any], *, include_ingested_at: bool = False) -> str:
    """Hash source content, not the receipt clock that Huginn overwrites.

    Source event clocks and nested payload fields remain identity-bearing.
    The legacy form is used only to prove an exact old request before upgrading
    a retained claim; changed legacy requests still require reviewed recovery.
    """
    try:
        encoded = json.dumps(
            raw
            if include_ingested_at
            else {key: value for key, value in raw.items() if key != "ingested_at"},
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("raw ingress request MUST be canonical JSON") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _terminal_key(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"{_TERMINAL_PREFIX}{digest}"


def _claim_from_entry(entry: Mapping[str, Any]) -> HuginnIngressClaim:
    payload = _json_mapping(entry.get("payload"), field="payload")
    raw_change = entry.get("change_projection")
    change = (
        _json_mapping(raw_change, field="change_projection") if raw_change is not None else None
    )
    return HuginnIngressClaim(
        payload=payload,
        change_projection=change,
        published_topics=frozenset(_published_topics(entry)),
    )


__all__ = [
    "HuginnClaimInProgressError",
    "HuginnDedupJournal",
    "HuginnIngressClaim",
    "request_digest",
]
