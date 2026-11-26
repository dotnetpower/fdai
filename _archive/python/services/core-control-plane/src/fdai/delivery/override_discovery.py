"""Bind the current ``governance.override_resolved`` audit source to rule discovery.

This adapter implements :class:`OverrideAuditReader` over the durable :class:`StateStore`
(including :class:`PostgresStateStore` and :class:`InMemoryStateStore`) and composes
:class:`OverrideDiscoverySignalSource` with upstream or operational discovery sources.

Safety invariants:

- Exact window: only ``governance.override_resolved`` records with timezone-aware
  ``recorded_at`` inside ``[window_start, window_end]`` are admitted.
- Independent source admission: every admitted record MUST carry an authorized T0
  producer identity (default ``actor="fdai.core.control_loop"`` and
  ``producer_principal="Mimir"``) and non-empty ``event_id`` and ``idempotency_key``.
  Records produced by ``Norns`` or any unauthorized principal fail closed so the
  discovery learner can never self-admit its own output as override evidence.
- Completeness: bounded reads inspect ``limit + 1`` matching window records so truncation
  is reported explicitly via ``complete=False`` rather than silently omitted.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from fdai.core.operational_learning.discovery_contracts import (
    DiscoveryObservationBatch,
    DiscoverySignal,
    DiscoverySignalSource,
)
from fdai.core.operational_learning.override_signals import (
    OverrideAuditPage,
    OverrideAuditReader,
    OverrideDiscoverySignalSource,
    OverrideSignalThresholds,
)
from fdai.delivery.persistence.postgres_audit_fields import json_object
from fdai.shared.providers.state_store import StateStore

OVERRIDE_RESOLVED_ACTION_KIND = "governance.override_resolved"
DEFAULT_ALLOWED_ACTORS = frozenset({"fdai.core.control_loop"})
DEFAULT_ALLOWED_PRODUCER_PRINCIPALS = frozenset({"Mimir"})
_FORBIDDEN_SELF_PRODUCERS = frozenset({"norns"})
_MAX_AUDIT_READ_LIMIT = 512


def _require_aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} MUST be timezone-aware")
    return value.astimezone(UTC)


def _parse_recorded_at(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("override-resolution audit record is missing recorded_at")
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("override-resolution audit time MUST be timezone-aware")
    return parsed.astimezone(UTC)


class StateStoreOverrideAuditReader(OverrideAuditReader):
    """Read ``governance.override_resolved`` audit records with window and source admission."""

    def __init__(
        self,
        store: StateStore,
        *,
        allowed_actors: Iterable[str] = DEFAULT_ALLOWED_ACTORS,
        allowed_producer_principals: Iterable[str] = DEFAULT_ALLOWED_PRODUCER_PRINCIPALS,
    ) -> None:
        actors = frozenset(item.strip() for item in allowed_actors if item.strip())
        principals = frozenset(item.strip() for item in allowed_producer_principals if item.strip())
        if not actors or not principals:
            raise ValueError(
                "override source admission requires non-empty actor and principal sets"
            )
        if any(item.casefold() in _FORBIDDEN_SELF_PRODUCERS for item in actors | principals):
            raise ValueError("Norns MUST NOT be admitted as an override audit producer")
        self._store = store
        self._allowed_actors = actors
        self._allowed_principals = principals

    @property
    def allowed_actors(self) -> frozenset[str]:
        return self._allowed_actors

    @property
    def allowed_producer_principals(self) -> frozenset[str]:
        return self._allowed_principals

    async def list_override_resolutions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> OverrideAuditPage:
        start_utc = _require_aware_utc(window_start, "window_start")
        end_utc = _require_aware_utc(window_end, "window_end")
        if (
            end_utc < start_utc
            or isinstance(limit, bool)
            or not 1 <= limit <= _MAX_AUDIT_READ_LIMIT
        ):
            raise ValueError("override audit window and limit MUST be valid")

        raw_entries, underlying_truncated = await self._load_candidate_entries(
            window_start=start_utc,
            window_end=end_utc,
            limit=limit,
        )
        admitted: list[Mapping[str, object]] = []
        for entry in raw_entries:
            if entry.get("action_kind") != OVERRIDE_RESOLVED_ACTION_KIND:
                continue
            recorded_at = _parse_recorded_at(entry.get("recorded_at"))
            if not (start_utc <= recorded_at <= end_utc):
                continue
            self._validate_independent_source_admission(entry)
            admitted.append(dict(entry))

        exceeded_limit = len(admitted) > limit
        complete = (not underlying_truncated) and (not exceeded_limit)
        return OverrideAuditPage(
            records=tuple(admitted[:limit]),
            complete=complete,
        )

    def _validate_independent_source_admission(self, entry: Mapping[str, Any]) -> None:
        actor = entry.get("actor")
        producer = entry.get("producer_principal")
        event_id = entry.get("event_id")
        idempotency_key = entry.get("idempotency_key")
        if not isinstance(actor, str) or actor.strip() not in self._allowed_actors:
            raise ValueError("override-resolution audit record failed independent actor admission")
        if not isinstance(producer, str) or producer.strip() not in self._allowed_principals:
            raise ValueError(
                "override-resolution audit record failed independent producer admission"
            )
        if (
            not isinstance(event_id, str)
            or not event_id.strip()
            or not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
        ):
            raise ValueError(
                "override-resolution audit record is missing event_id or idempotency_key"
            )

    async def _load_candidate_entries(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> tuple[tuple[Mapping[str, Any], ...], bool]:
        connection_factory = getattr(self._store, "_connection", None)
        timeout_setter = getattr(self._store, "_set_statement_timeout", None)
        if callable(connection_factory) and callable(timeout_setter):
            async with connection_factory() as conn:
                async with conn.transaction():
                    await timeout_setter(conn)
                    cursor = await conn.execute(
                        "SELECT entry FROM audit_log "
                        "WHERE entry->>'action_kind' = %s "
                        "AND (entry->>'recorded_at')::timestamptz >= %s "
                        "AND (entry->>'recorded_at')::timestamptz <= %s "
                        "ORDER BY seq ASC LIMIT %s",
                        (
                            OVERRIDE_RESOLVED_ACTION_KIND,
                            window_start,
                            window_end,
                            limit + 1,
                        ),
                    )
                    rows = await cursor.fetchall()
            return (
                tuple(dict(json_object(row["entry"])) for row in rows),
                False,
            )

        audit_entries_prop = getattr(self._store, "audit_entries", None)
        if isinstance(audit_entries_prop, Sequence):
            unwrapped: list[Mapping[str, Any]] = []
            for item in audit_entries_prop:
                inner = item.get("entry") if isinstance(item, Mapping) else None
                if isinstance(inner, Mapping) and "entry_hash" in item:
                    unwrapped.append(dict(inner))
                elif isinstance(item, Mapping):
                    unwrapped.append(dict(item))
            return tuple(unwrapped), False

        read_audit_fn = getattr(self._store, "read_audit_entries", None)
        if not callable(read_audit_fn):
            raise RuntimeError("StateStore does not expose read_audit_entries")
        result = await read_audit_fn(limit=_MAX_AUDIT_READ_LIMIT)
        return cast(tuple[tuple[Mapping[str, Any], ...], bool], result)


class CompositeDiscoverySignalSource(DiscoverySignalSource):
    """Compose ``OverrideDiscoverySignalSource`` with other discovery signal sources."""

    def __init__(
        self,
        *,
        sources: Sequence[DiscoverySignalSource],
    ) -> None:
        if not sources:
            raise ValueError("at least one discovery signal source is required")
        self._sources = tuple(sources)

    async def observe(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        limit: int,
    ) -> DiscoveryObservationBatch:
        start_utc = _require_aware_utc(window_start, "window_start")
        end_utc = _require_aware_utc(window_end, "window_end")
        if end_utc < start_utc or isinstance(limit, bool) or limit < 1:
            raise ValueError("composite discovery window and limit MUST be valid")
        batches = await asyncio.gather(
            *(
                source.observe(
                    window_start=start_utc,
                    window_end=end_utc,
                    limit=limit,
                )
                for source in self._sources
            )
        )
        signals_by_id: dict[str, DiscoverySignal] = {}
        complete = True
        for batch in batches:
            if batch.window_start != start_utc or batch.window_end != end_utc:
                raise ValueError("discovery signal source returned a mismatched window")
            complete = complete and batch.complete
            for signal in batch.signals:
                existing = signals_by_id.get(signal.signal_id)
                if existing is not None and existing != signal:
                    raise ValueError("conflicting discovery signal identity across sources")
                signals_by_id[signal.signal_id] = signal
        ordered = tuple(signals_by_id[key] for key in sorted(signals_by_id))
        if len(ordered) > limit:
            return DiscoveryObservationBatch(
                window_start=start_utc,
                window_end=end_utc,
                signals=ordered[:limit],
                complete=False,
            )
        return DiscoveryObservationBatch(
            window_start=start_utc,
            window_end=end_utc,
            signals=ordered,
            complete=complete,
        )


def bind_override_discovery_source(
    store: StateStore,
    *,
    thresholds: OverrideSignalThresholds | None = None,
    allowed_actors: Iterable[str] = DEFAULT_ALLOWED_ACTORS,
    allowed_producer_principals: Iterable[str] = DEFAULT_ALLOWED_PRODUCER_PRINCIPALS,
    additional_sources: Sequence[DiscoverySignalSource] = (),
) -> DiscoverySignalSource:
    """Bind the ``governance.override_resolved`` audit source for ``DiscoveryCycleScheduler``."""

    reader = StateStoreOverrideAuditReader(
        store,
        allowed_actors=allowed_actors,
        allowed_producer_principals=allowed_producer_principals,
    )
    override_source = OverrideDiscoverySignalSource(
        reader=reader,
        thresholds=thresholds,
    )
    if not additional_sources:
        return override_source
    return CompositeDiscoverySignalSource(
        sources=(override_source, *additional_sources),
    )


__all__ = [
    "DEFAULT_ALLOWED_ACTORS",
    "DEFAULT_ALLOWED_PRODUCER_PRINCIPALS",
    "OVERRIDE_RESOLVED_ACTION_KIND",
    "CompositeDiscoverySignalSource",
    "StateStoreOverrideAuditReader",
    "bind_override_discovery_source",
]
