"""Atomic StateStore ledger for FDAI Console action dispatch."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from fdai.shared.providers.state_store import StateStore

from .console_action_dispatch_models import (
    ConsoleActionDispatch,
    ConsoleActionDispatchConflictError,
    ConsoleActionDispatchState,
)

_PREFIX: Final[str] = "console_action_dispatch:"
_SCHEMA_VERSION: Final[str] = "1.0.0"
_LOGGER = logging.getLogger(__name__)


def console_action_dispatch_id(idempotency_key: str) -> str:
    return "cad-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsoleActionDispatchStore:
    """Atomically persist, lease, and complete dispatch records."""

    state_store: StateStore
    scan_limit: int = 10_000

    def __post_init__(self) -> None:
        if not 1 <= self.scan_limit <= 100_000:
            raise ValueError("console action dispatch scan_limit is invalid")

    async def enqueue(
        self,
        *,
        idempotency_key: str,
        intent_digest: str,
        topic: str,
        partition_key: str,
        payload: Mapping[str, object],
        correlation_id: str,
        actor_oid: str,
        now: datetime,
        initial_state: ConsoleActionDispatchState = ConsoleActionDispatchState.PENDING,
    ) -> tuple[ConsoleActionDispatch, bool]:
        if initial_state not in {
            ConsoleActionDispatchState.BLOCKED,
            ConsoleActionDispatchState.PENDING,
        }:
            raise ValueError("console action dispatch initial state is invalid")
        dispatch_id = console_action_dispatch_id(idempotency_key)
        record = ConsoleActionDispatch(
            dispatch_id=dispatch_id,
            idempotency_key=idempotency_key,
            intent_digest=intent_digest,
            topic=topic,
            partition_key=partition_key,
            payload=dict(payload),
            correlation_id=correlation_id,
            actor_oid=actor_oid,
            state=initial_state,
            revision=1,
            attempt_count=0,
            available_at=now,
            accepted_at=now,
            updated_at=now,
        )
        created = await self.state_store.write_state_with_audit_if_absent(
            _state_key(dispatch_id),
            record.to_mapping(),
            _audit(record, "console.action.dispatch.accepted", now),
        )
        if created:
            return record, True
        existing = await self.get(dispatch_id)
        if existing is None:
            raise RuntimeError("console action dispatch disappeared after enqueue race")
        if existing.idempotency_key != idempotency_key or existing.intent_digest != intent_digest:
            raise ConsoleActionDispatchConflictError(
                "console action idempotency key is bound to another intent",
                dispatch_id=existing.dispatch_id,
                correlation_id=existing.correlation_id,
                accepted_at=existing.accepted_at,
            )
        return existing, False

    async def get(self, dispatch_id: str) -> ConsoleActionDispatch | None:
        value = await self.state_store.read_state(_state_key(dispatch_id))
        return None if value is None else ConsoleActionDispatch.from_mapping(value)

    async def claim(
        self,
        dispatch_id: str,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
    ) -> ConsoleActionDispatch | None:
        if lease_seconds < 1 or not lease_owner.strip():
            raise ValueError("console action dispatch lease is invalid")
        for _attempt in range(5):
            current = await self.get(dispatch_id)
            if current is None or current.state in {
                ConsoleActionDispatchState.ABANDONED,
                ConsoleActionDispatchState.BLOCKED,
                ConsoleActionDispatchState.PUBLISHED,
            }:
                return None
            if current.available_at > now:
                return None
            if (
                current.state is ConsoleActionDispatchState.PUBLISHING
                and current.lease_until is not None
                and current.lease_until > now
            ):
                return None
            updated = replace(
                current,
                state=ConsoleActionDispatchState.PUBLISHING,
                revision=current.revision + 1,
                attempt_count=current.attempt_count + 1,
                updated_at=now,
                lease_owner=lease_owner,
                lease_until=now + timedelta(seconds=lease_seconds),
                last_error=None,
            )
            if await self.state_store.compare_and_set_state_with_audit(
                _state_key(dispatch_id),
                updated.to_mapping(),
                expected_revision=current.revision,
                audit_entry=_audit(updated, "console.action.dispatch.claimed", now),
            ):
                return updated
        return None

    async def due(self, *, now: datetime, limit: int) -> tuple[ConsoleActionDispatch, ...]:
        values = await self._page(limit)
        due = []
        for record in values:
            if (
                record.state
                in {
                    ConsoleActionDispatchState.ABANDONED,
                    ConsoleActionDispatchState.BLOCKED,
                    ConsoleActionDispatchState.PUBLISHED,
                }
                or record.available_at > now
            ):
                continue
            if (
                record.state is ConsoleActionDispatchState.PUBLISHING
                and record.lease_until is not None
                and record.lease_until > now
            ):
                continue
            due.append(record)
        return tuple(
            sorted(due, key=lambda item: (item.available_at, item.accepted_at, item.dispatch_id))[
                :limit
            ]
        )

    async def blocked(self, *, limit: int) -> tuple[ConsoleActionDispatch, ...]:
        values = await self._page(
            limit,
            field="state",
            value=ConsoleActionDispatchState.BLOCKED.value,
        )
        return tuple(sorted(values, key=lambda item: (item.accepted_at, item.dispatch_id))[:limit])

    async def _page(
        self,
        limit: int,
        *,
        field: str | None = None,
        value: str | None = None,
    ) -> tuple[ConsoleActionDispatch, ...]:
        if not 1 <= limit <= self.scan_limit:
            raise ValueError("console action dispatch page limit is invalid")
        values, _total = await self.state_store.read_state_page(
            _PREFIX,
            limit=self.scan_limit,
            field=field,
            value=value,
        )
        records = []
        for item in values:
            try:
                records.append(ConsoleActionDispatch.from_mapping(item))
            except (TypeError, ValueError):
                _LOGGER.exception(
                    "console_action_dispatch_record_invalid",
                    extra={"dispatch_id": str(item.get("dispatch_id") or "unknown")[:200]},
                )
        return tuple(records)

    async def activate(
        self,
        dispatch_id: str,
        *,
        now: datetime,
    ) -> ConsoleActionDispatch | None:
        for _attempt in range(5):
            current = await self.get(dispatch_id)
            if current is None:
                return None
            if current.state is not ConsoleActionDispatchState.BLOCKED:
                return current
            updated = replace(
                current,
                state=ConsoleActionDispatchState.PENDING,
                revision=current.revision + 1,
                available_at=now,
                updated_at=now,
            )
            if await self.state_store.compare_and_set_state_with_audit(
                _state_key(dispatch_id),
                updated.to_mapping(),
                expected_revision=current.revision,
                audit_entry=_audit(updated, "console.action.dispatch.activated", now),
            ):
                return updated
        return None

    async def abandon(
        self,
        dispatch_id: str,
        *,
        now: datetime,
        reason: str,
    ) -> ConsoleActionDispatch | None:
        if not reason.strip():
            raise ValueError("console action abandonment reason MUST be non-empty")
        for _attempt in range(5):
            current = await self.get(dispatch_id)
            if current is None:
                return None
            if current.state is not ConsoleActionDispatchState.BLOCKED:
                return current
            updated = replace(
                current,
                state=ConsoleActionDispatchState.ABANDONED,
                revision=current.revision + 1,
                updated_at=now,
                lease_owner=None,
                lease_until=None,
                last_error=reason[:200],
            )
            if await self.state_store.compare_and_set_state_with_audit(
                _state_key(dispatch_id),
                updated.to_mapping(),
                expected_revision=current.revision,
                audit_entry=_audit(updated, "console.action.dispatch.abandoned", now),
            ):
                return updated
        return None

    async def published(
        self,
        claimed: ConsoleActionDispatch,
        *,
        lease_owner: str,
        now: datetime,
    ) -> ConsoleActionDispatch:
        return await self._finish(
            claimed,
            lease_owner=lease_owner,
            now=now,
            state=ConsoleActionDispatchState.PUBLISHED,
            last_error=None,
            available_at=claimed.available_at,
        )

    async def deferred(
        self,
        claimed: ConsoleActionDispatch,
        *,
        lease_owner: str,
        now: datetime,
        retry_at: datetime,
        error: str,
    ) -> ConsoleActionDispatch:
        return await self._finish(
            claimed,
            lease_owner=lease_owner,
            now=now,
            state=ConsoleActionDispatchState.PENDING,
            last_error=error[:200],
            available_at=retry_at,
        )

    async def _finish(
        self,
        claimed: ConsoleActionDispatch,
        *,
        lease_owner: str,
        now: datetime,
        state: ConsoleActionDispatchState,
        last_error: str | None,
        available_at: datetime,
    ) -> ConsoleActionDispatch:
        current = await self.get(claimed.dispatch_id)
        if (
            current is None
            or current.state is not ConsoleActionDispatchState.PUBLISHING
            or current.revision != claimed.revision
            or current.lease_owner != lease_owner
        ):
            raise RuntimeError("console action dispatch lease no longer belongs to worker")
        updated = replace(
            current,
            state=state,
            revision=current.revision + 1,
            updated_at=now,
            available_at=available_at,
            lease_owner=None,
            lease_until=None,
            published_at=(now if state is ConsoleActionDispatchState.PUBLISHED else None),
            last_error=last_error,
        )
        kind = (
            "console.action.dispatch.published"
            if state is ConsoleActionDispatchState.PUBLISHED
            else "console.action.dispatch.deferred"
        )
        if not await self.state_store.compare_and_set_state_with_audit(
            _state_key(claimed.dispatch_id),
            updated.to_mapping(),
            expected_revision=current.revision,
            audit_entry=_audit(updated, kind, now),
        ):
            raise RuntimeError("console action dispatch completion raced")
        return updated


def _state_key(dispatch_id: str) -> str:
    return f"{_PREFIX}{dispatch_id}"


def _audit(record: ConsoleActionDispatch, kind: str, at: datetime) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "event_id": f"{record.dispatch_id}:{record.revision}",
        "correlation_id": record.correlation_id,
        "idempotency_key": f"{record.dispatch_id}:{record.revision}:{kind}",
        "producer": "console-action-dispatch",
        "producer_principal": "console-action-dispatch",
        "actor": record.actor_oid,
        "action_kind": kind,
        "kind": kind,
        "mode": "shadow",
        "dispatch_id": record.dispatch_id,
        "dispatch_state": record.state.value,
        "dispatch_revision": record.revision,
        "attempt_count": record.attempt_count,
        "intent_digest": record.intent_digest,
        "recorded_at": at.isoformat(),
    }


__all__ = ["ConsoleActionDispatchStore", "console_action_dispatch_id"]
