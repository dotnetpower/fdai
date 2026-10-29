"""Bounded durable aggregation for authenticated Forseti no-op verdicts."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.adapters import AuditChainError, _digest
from fdai.agents._framework.audit_chain_rehydrate import AuditAppendDeferredError
from fdai.shared.providers.state_store import StateStore, StateStorePairAuditWriter

_VERDICT_AGGREGATE_KEY = "pantheon/saga/verdict-aggregate-pending"
_VERDICT_AGGREGATE_SCHEMA = "1.0.0"
_VERDICT_AGGREGATE_LIMIT = 64
_CAS_ATTEMPTS = 8
_CAS_DEADLINE_SECONDS = 2.0


class SagaVerdictAggregator:
    """Stage eligible verdict deliveries and seal them through a paired audit CAS."""

    def __init__(
        self,
        *,
        store: StateStore | None,
        audit_chain: object,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._audit_chain = audit_chain
        self._clock = clock
        self._groups: dict[str, dict[str, Any]] = {}
        self._revision: int | None = None
        self._readable = False

    @property
    def pending_count(self) -> int:
        return len(self._groups)

    @property
    def revision(self) -> int | None:
        return self._revision

    @property
    def readable(self) -> bool:
        return self._readable

    async def refresh(self) -> None:
        self._readable = False
        store = self._store
        if store is None:
            return
        try:
            stored = await store.read_state(_VERDICT_AGGREGATE_KEY)
        except Exception as exc:
            raise AuditAppendDeferredError("verdict aggregate ledger read failed") from exc
        if stored is None and self._supports_pair_write(store):
            initial = {
                "schema_version": _VERDICT_AGGREGATE_SCHEMA,
                "revision": 1,
                "groups": {},
            }
            try:
                created = await store.write_state_if_absent(_VERDICT_AGGREGATE_KEY, initial)
            except Exception as exc:
                raise AuditAppendDeferredError(
                    "verdict aggregate ledger initialization failed"
                ) from exc
            if created:
                stored = initial
            else:
                try:
                    stored = await store.read_state(_VERDICT_AGGREGATE_KEY)
                except Exception as exc:
                    raise AuditAppendDeferredError("verdict aggregate ledger read failed") from exc
        if stored is None:
            self._groups = {}
            self._revision = None
        else:
            self._revision, self._groups = _decode_ledger(stored)
        self._readable = True

    async def stage(self, topic: str, payload: Mapping[str, Any]) -> bool:
        """Persist one eligible delivery; return false when aggregation is unsupported."""
        if not is_aggregate_eligible(topic, payload):
            return False
        store = self._store
        if store is None or not self._supports_pair_write(store):
            return False
        subject_digest, source_digest, group_digest = _aggregate_digests(payload)
        timestamp = self._timestamp()
        try:
            async with asyncio.timeout(_CAS_DEADLINE_SECONDS):
                for attempt in range(_CAS_ATTEMPTS):
                    await self.refresh()
                    revision = self._required_revision()
                    if group_digest not in self._groups:
                        same_subject = [
                            key
                            for key, group in self._groups.items()
                            if group["subject_digest"] == subject_digest
                        ]
                        if same_subject:
                            await self._seal_keys(same_subject, subject_digest=subject_digest)
                            continue
                        if len(self._groups) >= _VERDICT_AGGREGATE_LIMIT:
                            oldest = _ordered_group_keys(self._groups)[:1]
                            await self._seal_keys(oldest)
                            continue
                    next_groups = {key: dict(group) for key, group in self._groups.items()}
                    existing = next_groups.get(group_digest)
                    if existing is None:
                        next_groups[group_digest] = {
                            "subject_digest": subject_digest,
                            "source_digest": source_digest,
                            "count": 1,
                            "first_seen_at": timestamp,
                            "last_seen_at": timestamp,
                        }
                    else:
                        last_seen_at = max(
                            existing["last_seen_at"],
                            timestamp,
                            key=datetime.fromisoformat,
                        )
                        next_groups[group_digest] = {
                            **existing,
                            "count": existing["count"] + 1,
                            "last_seen_at": last_seen_at,
                        }
                    updated = _encode_ledger(revision + 1, next_groups)
                    try:
                        committed = await store.compare_and_set_state(
                            _VERDICT_AGGREGATE_KEY,
                            updated,
                            expected_revision=revision,
                        )
                    except Exception as exc:
                        self._readable = False
                        raise AuditAppendDeferredError(
                            "verdict aggregate staging write failed"
                        ) from exc
                    if committed:
                        self._remember(revision + 1, next_groups)
                        return True
                    await asyncio.sleep(0.005 * (attempt + 1))
        except TimeoutError as exc:
            self._readable = False
            raise AuditAppendDeferredError("verdict aggregate staging deadline exceeded") from exc
        self._readable = False
        raise AuditAppendDeferredError("verdict aggregate staging contention budget exhausted")

    async def seal_subject(self, resource_id: str) -> None:
        if not resource_id:
            return
        subject_digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()
        await self.refresh()
        keys = [
            key for key, group in self._groups.items() if group["subject_digest"] == subject_digest
        ]
        await self._seal_keys(keys, subject_digest=subject_digest)

    async def append_ordered_audit(
        self,
        *,
        principal: str,
        topic: str,
        correlation_id: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Fence a subject's audit append against concurrent aggregate staging."""
        resource_id = payload.get("resource_id")
        store = self._store
        if not isinstance(resource_id, str) or not resource_id:
            return False
        subject_digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()
        if store is None:
            return False
        if not self._supports_pair_write(store):
            await self.refresh()
            if any(group["subject_digest"] == subject_digest for group in self._groups.values()):
                raise AuditAppendDeferredError("verdict aggregate pair writer is unavailable")
            return False
        try:
            async with asyncio.timeout(_CAS_DEADLINE_SECONDS):
                for attempt in range(_CAS_ATTEMPTS):
                    await self.refresh()
                    revision = self._required_revision()
                    pending = [
                        key
                        for key, group in self._groups.items()
                        if group["subject_digest"] == subject_digest
                    ]
                    if pending:
                        await self._seal_keys(pending, subject_digest=subject_digest)
                        continue
                    next_groups = {key: dict(group) for key, group in self._groups.items()}
                    updated = _encode_ledger(revision + 1, next_groups)
                    append_with_state_pair = getattr(
                        self._audit_chain, "append_with_state_pair", None
                    )
                    if not callable(append_with_state_pair):
                        raise AuditAppendDeferredError(
                            "verdict aggregate audit-chain writer is unavailable"
                        )
                    try:
                        entry = await append_with_state_pair(
                            state_key=_VERDICT_AGGREGATE_KEY,
                            state_value=updated,
                            expected_state_revision=revision,
                            principal=principal,
                            topic=topic,
                            correlation_id=correlation_id,
                            payload=dict(payload),
                        )
                    except Exception as exc:
                        self._readable = False
                        raise AuditAppendDeferredError(
                            "ordered subject audit append failed"
                        ) from exc
                    if entry is not None:
                        self._remember(revision + 1, next_groups)
                        return True
                    await asyncio.sleep(0.005 * (attempt + 1))
        except TimeoutError as exc:
            self._readable = False
            raise AuditAppendDeferredError(
                "ordered subject audit append deadline exceeded"
            ) from exc
        self._readable = False
        raise AuditAppendDeferredError("ordered subject audit append contention budget exhausted")

    async def flush_pending(self, *, limit: int = _VERDICT_AGGREGATE_LIMIT) -> None:
        await self.refresh()
        if not self._groups:
            return
        if not self._supports_pair_write(self._store):
            raise AuditAppendDeferredError("verdict aggregate pair writer is unavailable")
        for key in _ordered_group_keys(self._groups)[:limit]:
            await self._seal(key)
        await self.refresh()

    def _supports_pair_write(self, store: StateStore | None) -> bool:
        return (
            store is not None
            and isinstance(store, StateStorePairAuditWriter)
            and callable(getattr(self._audit_chain, "append_with_state_pair", None))
        )

    def _required_revision(self) -> int:
        revision = self._revision
        if revision is None or revision < 1:
            raise AuditAppendDeferredError("verdict aggregate ledger is not initialized")
        return revision

    def _timestamp(self) -> str:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("verdict aggregate clock MUST be timezone-aware")
        return current.astimezone(UTC).isoformat()

    def _remember(self, revision: int, groups: Mapping[str, Mapping[str, Any]]) -> None:
        self._revision = revision
        self._groups = {key: dict(value) for key, value in groups.items()}
        self._readable = True

    async def _seal_keys(
        self,
        keys: list[str],
        *,
        subject_digest: str | None = None,
    ) -> None:
        if not keys:
            return
        if not self._supports_pair_write(self._store):
            await self.refresh()
            if any(key in self._groups for key in keys):
                raise AuditAppendDeferredError("verdict aggregate pair writer is unavailable")
            return
        candidates = set(keys)
        for _ in range(_VERDICT_AGGREGATE_LIMIT):
            await self.refresh()
            if subject_digest is not None:
                pending = [
                    key
                    for key, group in self._groups.items()
                    if group["subject_digest"] == subject_digest
                ]
            else:
                pending = [key for key in candidates if key in self._groups]
            if not pending:
                return
            await self._seal(_ordered_group_keys(self._groups, include=set(pending))[0])
        raise AuditAppendDeferredError("verdict aggregate sealing limit exceeded")

    async def _seal(self, group_digest: str) -> None:
        store = self._store
        if store is None or not self._supports_pair_write(store):
            raise AuditAppendDeferredError("verdict aggregate pair writer is unavailable")
        try:
            async with asyncio.timeout(_CAS_DEADLINE_SECONDS):
                for attempt in range(_CAS_ATTEMPTS):
                    await self.refresh()
                    revision = self._required_revision()
                    group = self._groups.get(group_digest)
                    if group is None:
                        return
                    next_groups = {
                        key: dict(value)
                        for key, value in self._groups.items()
                        if key != group_digest
                    }
                    updated = _encode_ledger(revision + 1, next_groups)
                    payload = {
                        "schema_version": _VERDICT_AGGREGATE_SCHEMA,
                        "aggregate_type": "forseti.no_rule_match",
                        "subject_digest": group["subject_digest"],
                        "source_digest": group["source_digest"],
                        "count": group["count"],
                        "first_seen_at": group["first_seen_at"],
                        "last_seen_at": group["last_seen_at"],
                    }
                    append_with_state_pair = getattr(
                        self._audit_chain, "append_with_state_pair", None
                    )
                    if not callable(append_with_state_pair):
                        raise AuditAppendDeferredError(
                            "verdict aggregate audit-chain writer is unavailable"
                        )
                    try:
                        entry = await append_with_state_pair(
                            state_key=_VERDICT_AGGREGATE_KEY,
                            state_value=updated,
                            expected_state_revision=revision,
                            correlation_id_prefix=f"aggregate:{group_digest}",
                            payload=payload,
                        )
                    except Exception as exc:
                        self._readable = False
                        raise AuditAppendDeferredError(
                            "verdict aggregate sealing write failed"
                        ) from exc
                    if entry is not None:
                        self._remember(revision + 1, next_groups)
                        return
                    await asyncio.sleep(0.005 * (attempt + 1))
        except TimeoutError as exc:
            self._readable = False
            raise AuditAppendDeferredError("verdict aggregate sealing deadline exceeded") from exc
        self._readable = False
        raise AuditAppendDeferredError("verdict aggregate sealing contention budget exhausted")


def is_aggregate_eligible(topic: str, payload: Mapping[str, Any]) -> bool:
    return (
        topic == "object.verdict"
        and payload.get("producer_principal") == "Forseti"
        and payload.get("reason") == "no_rule_match"
        and payload.get("risk_verdict") == "hil"
        and payload.get("action_type") == ""
        and payload.get("resolved_autonomy_ceiling") == "shadow_only"
        and isinstance(payload.get("resource_id"), str)
        and bool(payload.get("resource_id"))
        and isinstance(payload.get("correlation_id"), str)
        and bool(payload.get("correlation_id"))
        and not payload.get("action_id")
    )


def _aggregate_digests(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    resource_id = payload["resource_id"]
    if not isinstance(resource_id, str):
        raise ValueError("verdict aggregate resource_id MUST be a string")
    subject_digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()
    source = {
        key: value
        for key, value in payload.items()
        if key not in {"resource_id", "correlation_id", "idempotency_key"}
    }
    source_digest = _digest(source)
    group_digest = _digest(
        {
            "schema_version": _VERDICT_AGGREGATE_SCHEMA,
            "subject_digest": subject_digest,
            "source_digest": source_digest,
        }
    )
    return subject_digest, source_digest, group_digest


def _encode_ledger(
    revision: int,
    groups: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": _VERDICT_AGGREGATE_SCHEMA,
        "revision": revision,
        "groups": {key: dict(value) for key, value in groups.items()},
    }


def _decode_ledger(
    stored: Mapping[str, Any],
) -> tuple[int, dict[str, dict[str, Any]]]:
    revision = stored.get("revision")
    raw_groups = stored.get("groups")
    if (
        stored.get("schema_version") != _VERDICT_AGGREGATE_SCHEMA
        or type(revision) is not int
        or revision < 1
        or not isinstance(raw_groups, Mapping)
        or len(raw_groups) > _VERDICT_AGGREGATE_LIMIT
    ):
        raise AuditChainError("verdict aggregate ledger is malformed")
    groups: dict[str, dict[str, Any]] = {}
    for group_digest, raw_group in raw_groups.items():
        if not isinstance(group_digest, str) or not isinstance(raw_group, Mapping):
            raise AuditChainError("verdict aggregate group is malformed")
        subject_digest = raw_group.get("subject_digest")
        source_digest = raw_group.get("source_digest")
        count = raw_group.get("count")
        first_seen_at = raw_group.get("first_seen_at")
        last_seen_at = raw_group.get("last_seen_at")
        if (
            not _is_sha256(subject_digest)
            or not _is_sha256(source_digest)
            or _digest(
                {
                    "schema_version": _VERDICT_AGGREGATE_SCHEMA,
                    "subject_digest": subject_digest,
                    "source_digest": source_digest,
                }
            )
            != group_digest
            or type(count) is not int
            or count < 1
            or not isinstance(first_seen_at, str)
            or not isinstance(last_seen_at, str)
            or not _valid_timestamp_range(first_seen_at, last_seen_at)
        ):
            raise AuditChainError("verdict aggregate group is malformed")
        groups[group_digest] = {
            "subject_digest": subject_digest,
            "source_digest": source_digest,
            "count": count,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
        }
    return revision, groups


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _valid_timestamp_range(first_seen_at: str, last_seen_at: str) -> bool:
    try:
        first = datetime.fromisoformat(first_seen_at)
        last = datetime.fromisoformat(last_seen_at)
    except ValueError:
        return False
    return (
        first.tzinfo is not None
        and first.utcoffset() is not None
        and last.tzinfo is not None
        and last.utcoffset() is not None
        and first <= last
    )


def _ordered_group_keys(
    groups: Mapping[str, Mapping[str, Any]],
    *,
    include: set[str] | None = None,
) -> list[str]:
    return sorted(
        (key for key in groups if include is None or key in include),
        key=lambda key: (groups[key]["first_seen_at"], key),
    )
