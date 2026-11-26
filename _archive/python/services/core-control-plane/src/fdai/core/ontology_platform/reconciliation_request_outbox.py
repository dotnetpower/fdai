"""Durable leased outbox for effect-reconciliation request events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai.shared.providers.state_store import StateStore

from .reconciliation_events import EffectReconciliationRequestEvent


class ReconciliationRequestOutboxConflictError(RuntimeError):
    """Raised when request identity or lease ownership conflicts."""


class ReconciliationRequestOutboxState(StrEnum):
    """Delivery state for one immutable request event."""

    PENDING = "pending"
    CLAIMED = "claimed"
    PUBLISHED = "published"


class ReconciliationRequestOutbox(Protocol):
    """Persistence seam for durable request publication."""

    async def commit(
        self,
        event: EffectReconciliationRequestEvent,
        *,
        available_at: datetime,
    ) -> EffectReconciliationRequestEvent: ...

    async def state_of(
        self,
        request_id: str,
    ) -> ReconciliationRequestOutboxState | None: ...

    async def claim(
        self,
        request_id: str,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> EffectReconciliationRequestEvent | None: ...

    async def claim_next(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> EffectReconciliationRequestEvent | None: ...

    async def complete(
        self,
        request_id: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None: ...

    async def release(
        self,
        request_id: str,
        *,
        claimant_id: str,
        available_at: datetime,
        error: str,
    ) -> None: ...


class StateStoreReconciliationRequestOutbox:
    """StateStore aggregate with immutable payload and lease-fenced delivery."""

    _KEY_PREFIX = "ontology:effect-reconciliation-request:"
    _MAX_CAS_ATTEMPTS = 64

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def commit(
        self,
        event: EffectReconciliationRequestEvent,
        *,
        available_at: datetime,
    ) -> EffectReconciliationRequestEvent:
        """Persist one immutable request before any broker attempt."""

        _require_aware(available_at)
        validated = _validate_event(event)
        key = self._key(validated.observation_attempt_id)
        record = self._record(
            event=validated,
            revision=1,
            state=ReconciliationRequestOutboxState.PENDING,
            attempts=0,
            available_at=available_at,
        )
        if await self._store.write_state_with_audit_if_absent(
            key,
            record,
            self._audit(validated, "effect_reconciliation.request_queued", 1),
        ):
            return validated
        existing = await self._store.read_state(key)
        if existing is None:
            raise RuntimeError("reconciliation request outbox write lost durable state")
        _, prior, _, _, _, _, _ = self._parse(existing)
        if prior.event_digest != validated.event_digest:
            raise ReconciliationRequestOutboxConflictError(
                "reconciliation request identity was reused with different content"
            )
        return prior

    async def state_of(
        self,
        request_id: str,
    ) -> ReconciliationRequestOutboxState | None:
        """Return the validated durable delivery state for one request."""

        raw = await self._store.read_state(self._key(request_id))
        if raw is None:
            return None
        _, event, state, _, _, _, _ = self._parse(raw)
        if event.observation_attempt_id != request_id:
            raise RuntimeError("durable reconciliation request identity does not match its key")
        return state

    async def claim(
        self,
        request_id: str,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> EffectReconciliationRequestEvent | None:
        """Claim one exact request when pending or lease-expired."""

        _validate_lease(claimant_id=claimant_id, now=now, lease_until=lease_until)
        key = self._key(request_id)
        for _ in range(self._MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                return None
            revision, event, state, attempts, available_at, _, current_lease = self._parse(raw)
            if state is ReconciliationRequestOutboxState.PUBLISHED:
                return None
            if available_at > now:
                return None
            if (
                state is ReconciliationRequestOutboxState.CLAIMED
                and current_lease is not None
                and current_lease > now
            ):
                return None
            next_revision = revision + 1
            claimed = self._record(
                event=event,
                revision=next_revision,
                state=ReconciliationRequestOutboxState.CLAIMED,
                attempts=attempts + 1,
                available_at=available_at,
                claimant_id=claimant_id,
                lease_until=lease_until,
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                claimed,
                expected_revision=revision,
                audit_entry=self._audit(
                    event,
                    "effect_reconciliation.request_claimed",
                    next_revision,
                ),
            ):
                return event
        raise RuntimeError("reconciliation request outbox claim conflicted repeatedly")

    async def claim_next(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> EffectReconciliationRequestEvent | None:
        """Claim the oldest due request without starving earlier failures."""

        _validate_lease(claimant_id=claimant_id, now=now, lease_until=lease_until)
        candidates: list[tuple[datetime, str]] = []
        for state in (
            ReconciliationRequestOutboxState.PENDING,
            ReconciliationRequestOutboxState.CLAIMED,
        ):
            offset = 0
            while True:
                page, total = await self._store.read_state_page(
                    self._KEY_PREFIX,
                    limit=100,
                    offset=offset,
                    field="outbox_state",
                    value=state.value,
                )
                for raw in page:
                    _, event, _, _, available_at, _, current_lease = self._parse(raw)
                    due_at = max(available_at, current_lease or available_at)
                    if due_at <= now:
                        candidates.append((due_at, event.observation_attempt_id))
                offset += len(page)
                if not page or offset >= total:
                    break
        for _, request_id in sorted(candidates):
            claimed = await self.claim(
                request_id,
                claimant_id=claimant_id,
                now=now,
                lease_until=lease_until,
            )
            if claimed is not None:
                return claimed
        return None

    async def complete(
        self,
        request_id: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None:
        """Persist broker acknowledgement for a currently owned claim."""

        await self._transition(
            request_id,
            claimant_id=claimant_id,
            transition_at=published_at,
            state=ReconciliationRequestOutboxState.PUBLISHED,
            error=None,
        )

    async def release(
        self,
        request_id: str,
        *,
        claimant_id: str,
        available_at: datetime,
        error: str,
    ) -> None:
        """Release a failed broker attempt for durable retry."""

        if not error:
            raise ValueError("reconciliation request outbox error MUST be non-empty")
        await self._transition(
            request_id,
            claimant_id=claimant_id,
            transition_at=available_at,
            state=ReconciliationRequestOutboxState.PENDING,
            error=error,
        )

    async def _transition(
        self,
        request_id: str,
        *,
        claimant_id: str,
        transition_at: datetime,
        state: ReconciliationRequestOutboxState,
        error: str | None,
    ) -> None:
        _require_aware(transition_at)
        if not claimant_id:
            raise ValueError("reconciliation request outbox claimant id MUST be non-empty")
        key = self._key(request_id)
        for _ in range(self._MAX_CAS_ATTEMPTS):
            raw = await self._store.read_state(key)
            if raw is None:
                raise ReconciliationRequestOutboxConflictError(
                    "reconciliation request outbox event does not exist"
                )
            revision, event, current, attempts, available_at, owner, _ = self._parse(raw)
            if current is ReconciliationRequestOutboxState.PUBLISHED:
                if state is ReconciliationRequestOutboxState.PUBLISHED:
                    return
                raise ReconciliationRequestOutboxConflictError(
                    "published reconciliation request cannot be released"
                )
            if current is not ReconciliationRequestOutboxState.CLAIMED or owner != claimant_id:
                raise ReconciliationRequestOutboxConflictError(
                    "reconciliation request outbox claim is not owned by claimant"
                )
            next_revision = revision + 1
            next_record = self._record(
                event=event,
                revision=next_revision,
                state=state,
                attempts=attempts,
                available_at=(
                    transition_at
                    if state is ReconciliationRequestOutboxState.PENDING
                    else available_at
                ),
                published_at=(
                    transition_at if state is ReconciliationRequestOutboxState.PUBLISHED else None
                ),
                last_error=error,
            )
            action = (
                "effect_reconciliation.request_published"
                if state is ReconciliationRequestOutboxState.PUBLISHED
                else "effect_reconciliation.request_released"
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                next_record,
                expected_revision=revision,
                audit_entry=self._audit(event, action, next_revision),
            ):
                return
        raise RuntimeError("reconciliation request outbox transition conflicted repeatedly")

    @classmethod
    def _key(cls, request_id: str) -> str:
        if not request_id:
            raise ValueError("reconciliation request id MUST be non-empty")
        return f"{cls._KEY_PREFIX}{request_id}"

    @staticmethod
    def _record(
        *,
        event: EffectReconciliationRequestEvent,
        revision: int,
        state: ReconciliationRequestOutboxState,
        attempts: int,
        available_at: datetime,
        claimant_id: str | None = None,
        lease_until: datetime | None = None,
        published_at: datetime | None = None,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "request_id": event.observation_attempt_id,
            "reconciliation_id": event.reconciliation_id,
            "revision": revision,
            "event": event.model_dump(mode="json"),
            "outbox_state": state.value,
            "attempts": attempts,
            "available_at": available_at.isoformat(),
            "claimant_id": claimant_id,
            "lease_until": lease_until.isoformat() if lease_until is not None else None,
            "published_at": published_at.isoformat() if published_at is not None else None,
            "last_error": last_error,
        }

    @staticmethod
    def _parse(
        raw: Mapping[str, Any],
    ) -> tuple[
        int,
        EffectReconciliationRequestEvent,
        ReconciliationRequestOutboxState,
        int,
        datetime,
        str | None,
        datetime | None,
    ]:
        try:
            if raw.get("schema_version") != "1.0.0":
                raise ValueError("unsupported schema version")
            revision = int(raw["revision"])
            attempts = int(raw["attempts"])
            event = EffectReconciliationRequestEvent.model_validate(raw["event"])
            if raw.get("request_id") != event.observation_attempt_id:
                raise ValueError("reconciliation request identity mismatch")
            if raw.get("reconciliation_id") != event.reconciliation_id:
                raise ValueError("reconciliation identity mismatch")
            state = ReconciliationRequestOutboxState(str(raw["outbox_state"]))
            available_at = datetime.fromisoformat(str(raw["available_at"]))
            claimant = raw.get("claimant_id")
            lease_raw = raw.get("lease_until")
            lease_until = datetime.fromisoformat(str(lease_raw)) if lease_raw else None
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("durable reconciliation request outbox failed validation") from exc
        _require_aware(available_at)
        if lease_until is not None:
            _require_aware(lease_until)
        if revision < 1 or attempts < 0:
            raise RuntimeError("durable reconciliation request outbox counters are invalid")
        if state is ReconciliationRequestOutboxState.CLAIMED:
            if not isinstance(claimant, str) or not claimant or lease_until is None:
                raise RuntimeError("claimed reconciliation request requires one lease owner")
        elif claimant is not None or lease_until is not None:
            raise RuntimeError("unclaimed reconciliation request cannot retain a lease")
        return revision, event, state, attempts, available_at, claimant, lease_until

    @staticmethod
    def _audit(
        event: EffectReconciliationRequestEvent,
        action_kind: str,
        revision: int,
    ) -> dict[str, Any]:
        return {
            "action_kind": action_kind,
            "actor": "effect-reconciliation-request-outbox",
            "request_id": event.observation_attempt_id,
            "reconciliation_id": event.reconciliation_id,
            "event_digest": event.event_digest,
            "revision": revision,
        }


def _validate_event(event: EffectReconciliationRequestEvent) -> EffectReconciliationRequestEvent:
    return EffectReconciliationRequestEvent.model_validate_json(event.model_dump_json())


def _validate_lease(*, claimant_id: str, now: datetime, lease_until: datetime) -> None:
    if not claimant_id:
        raise ValueError("reconciliation request outbox claimant id MUST be non-empty")
    _require_aware(now)
    _require_aware(lease_until)
    if lease_until <= now:
        raise ValueError("reconciliation request outbox lease MUST end after claim time")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reconciliation request outbox timestamps MUST be timezone-aware")


__all__ = [
    "ReconciliationRequestOutbox",
    "ReconciliationRequestOutboxConflictError",
    "ReconciliationRequestOutboxState",
    "StateStoreReconciliationRequestOutbox",
]
