"""Durable StateStore-backed effect reconciliation ledger."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from fdai.shared.providers.state_store import StateStore

from .reconciliation_contracts import ReconciliationOutcome
from .reconciliation_errors import (
    ReconciliationAggregateLimitError,
    ReconciliationAttemptLimitError,
    ReconciliationConflictError,
    ReconciliationLedgerCorruptionError,
)
from .reconciliation_events import (
    ReconciliationOutboxDeliveryState,
    ReconciliationOutboxEvent,
    ReconciliationOutboxRecord,
)


def _validate_outbox_lease(
    *,
    claimant_id: str,
    now: datetime,
    lease_until: datetime,
) -> None:
    if not claimant_id:
        raise ValueError("reconciliation outbox claimant id MUST be non-empty")
    if (
        now.tzinfo is None
        or now.utcoffset() is None
        or lease_until.tzinfo is None
        or lease_until.utcoffset() is None
    ):
        raise ValueError("reconciliation outbox lease times MUST be timezone-aware")
    if lease_until <= now:
        raise ValueError("reconciliation outbox lease MUST end after claim time")


def _outbox_is_claimable(record: ReconciliationOutboxRecord, *, now: datetime) -> bool:
    if record.state is ReconciliationOutboxDeliveryState.PUBLISHED:
        return False
    if record.state is ReconciliationOutboxDeliveryState.CLAIMED:
        return record.lease_until is not None and record.lease_until <= now
    return record.available_at is None or record.available_at <= now


def _require_claimed_outbox(
    records: Mapping[str, ReconciliationOutboxRecord],
    *,
    idempotency_key: str,
    claimant_id: str,
) -> ReconciliationOutboxRecord:
    record = records.get(idempotency_key)
    if record is None:
        raise ReconciliationConflictError("reconciliation outbox event does not exist")
    if record.state is ReconciliationOutboxDeliveryState.PUBLISHED:
        return record
    if (
        record.state is not ReconciliationOutboxDeliveryState.CLAIMED
        or record.claimant_id != claimant_id
    ):
        raise ReconciliationConflictError(
            "reconciliation outbox publication is not owned by the claimant"
        )
    return record


class StateStoreReconciliationLedger:
    """Durable reconciliation aggregate with atomic terminal outcome and outbox state."""

    _KEY_PREFIX = "ontology:reconciliation:"
    _SCHEMA_VERSION = "1.1.0"
    _MAX_CAS_ATTEMPTS = 64
    _MAX_ATTEMPTS_PER_RECONCILIATION = 8
    _MAX_AGGREGATE_BYTES = 16 * 1_048_576

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if outcome.terminal:
            raise ValueError("terminal reconciliation MUST use commit_terminal")
        return await self._persist(outcome, terminal=False)

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if not outcome.terminal:
            raise ValueError("unscorable reconciliation is attempt evidence, not terminal closure")
        return await self._persist(outcome, terminal=True)

    async def claim_outbox(
        self,
        *,
        claimant_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> ReconciliationOutboxEvent | None:
        """CAS-claim one pending or lease-expired terminal outbox event."""

        _validate_outbox_lease(claimant_id=claimant_id, now=now, lease_until=lease_until)
        for _ in range(self._MAX_CAS_ATTEMPTS):
            candidates = await self._outbox_candidates()
            if not candidates:
                return None
            saw_claimable = False
            for aggregate in candidates:
                reconciliation_id = aggregate.get("reconciliation_id")
                if not isinstance(reconciliation_id, str):
                    raise ReconciliationLedgerCorruptionError(
                        "durable reconciliation state failed validation"
                    )
                revision, attempts, terminal_outcome, outbox = self._parse_record(
                    aggregate,
                    reconciliation_id=reconciliation_id,
                )
                delivery = next(iter(outbox.values()))
                if not _outbox_is_claimable(delivery, now=now):
                    continue
                saw_claimable = True
                claimed = ReconciliationOutboxRecord(
                    event=delivery.event,
                    state=ReconciliationOutboxDeliveryState.CLAIMED,
                    attempts=delivery.attempts + 1,
                    available_at=delivery.available_at,
                    claimant_id=claimant_id,
                    lease_until=lease_until,
                )
                next_revision = revision + 1
                record = self._record(
                    reconciliation_id=reconciliation_id,
                    revision=next_revision,
                    attempts=attempts,
                    terminal_outcome=terminal_outcome,
                    outbox={claimed.event.idempotency_key: claimed},
                )
                if await self._store.compare_and_set_state_with_audit(
                    f"{self._KEY_PREFIX}{reconciliation_id}",
                    record,
                    expected_revision=revision,
                    audit_entry=self._outbox_audit_entry(
                        claimed.event,
                        action_kind="ontology.reconciliation.outbox_claimed",
                        revision=next_revision,
                    ),
                ):
                    return claimed.event
            if not saw_claimable:
                return None
        raise RuntimeError("reconciliation outbox claim conflicted repeatedly")

    async def complete_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        published_at: datetime,
    ) -> None:
        """Persist broker acknowledgement for the exact claimed outbox event."""

        await self._update_outbox_delivery(
            reconciliation_id=reconciliation_id,
            idempotency_key=idempotency_key,
            claimant_id=claimant_id,
            action="complete",
            transition_at=published_at,
        )

    async def release_outbox(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        claimant_id: str,
        available_at: datetime,
    ) -> None:
        """Release a failed broker publication while retaining event identity."""

        await self._update_outbox_delivery(
            reconciliation_id=reconciliation_id,
            idempotency_key=idempotency_key,
            claimant_id=claimant_id,
            action="release",
            transition_at=available_at,
        )

    async def _outbox_candidates(self) -> tuple[Mapping[str, Any], ...]:
        candidates: list[Mapping[str, Any]] = []
        page_size = 100
        for state in (
            ReconciliationOutboxDeliveryState.PENDING,
            ReconciliationOutboxDeliveryState.CLAIMED,
        ):
            offset = 0
            while True:
                page, total = await self._store.read_state_page(
                    self._KEY_PREFIX,
                    limit=page_size,
                    offset=offset,
                    field="outbox_state",
                    value=state.value,
                )
                candidates.extend(page)
                offset += len(page)
                if not page or offset >= total:
                    break
        return tuple(candidates)

    async def _update_outbox_delivery(
        self,
        *,
        reconciliation_id: str,
        idempotency_key: str,
        claimant_id: str,
        action: Literal["complete", "release"],
        transition_at: datetime,
    ) -> None:
        key = f"{self._KEY_PREFIX}{reconciliation_id}"
        for _ in range(self._MAX_CAS_ATTEMPTS):
            aggregate = await self._store.read_state(key)
            if aggregate is None:
                raise ReconciliationConflictError("reconciliation outbox aggregate does not exist")
            revision, attempts, terminal_outcome, outbox = self._parse_record(
                aggregate,
                reconciliation_id=reconciliation_id,
            )
            delivery = _require_claimed_outbox(
                outbox,
                idempotency_key=idempotency_key,
                claimant_id=claimant_id,
            )
            if delivery.state is ReconciliationOutboxDeliveryState.PUBLISHED:
                return
            updated = (
                ReconciliationOutboxRecord(
                    event=delivery.event,
                    state=ReconciliationOutboxDeliveryState.PUBLISHED,
                    attempts=delivery.attempts,
                    available_at=delivery.available_at,
                    published_at=transition_at,
                )
                if action == "complete"
                else ReconciliationOutboxRecord(
                    event=delivery.event,
                    attempts=delivery.attempts,
                    available_at=transition_at,
                )
            )
            next_revision = revision + 1
            record = self._record(
                reconciliation_id=reconciliation_id,
                revision=next_revision,
                attempts=attempts,
                terminal_outcome=terminal_outcome,
                outbox={idempotency_key: updated},
            )
            action_kind = (
                "ontology.reconciliation.outbox_published"
                if action == "complete"
                else "ontology.reconciliation.outbox_released"
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=self._outbox_audit_entry(
                    updated.event,
                    action_kind=action_kind,
                    revision=next_revision,
                ),
            ):
                return
        raise RuntimeError("reconciliation outbox update conflicted repeatedly")

    async def _persist(
        self,
        outcome: ReconciliationOutcome,
        *,
        terminal: bool,
    ) -> ReconciliationOutcome:
        key = f"{self._KEY_PREFIX}{outcome.reconciliation_id}"
        for _ in range(self._MAX_CAS_ATTEMPTS):
            existing_record = await self._store.read_state(key)
            if existing_record is None:
                record = self._new_record(outcome, terminal=terminal)
                if await self._store.write_state_with_audit_if_absent(
                    key,
                    record,
                    self._audit_entry(outcome, terminal=terminal, revision=1),
                ):
                    return outcome
                continue

            revision, attempts, terminal_outcome, outbox = self._parse_record(
                existing_record,
                reconciliation_id=outcome.reconciliation_id,
            )
            if terminal_outcome is not None:
                return terminal_outcome

            existing_attempt = attempts.get(outcome.observation_attempt_id)
            if existing_attempt is not None:
                if existing_attempt.request_digest != outcome.request_digest:
                    raise ReconciliationConflictError(
                        "reconciliation attempt identity reused with different request content"
                    )
                return existing_attempt

            maximum_existing = self._MAX_ATTEMPTS_PER_RECONCILIATION - int(not terminal)
            if len(attempts) >= maximum_existing:
                raise ReconciliationAttemptLimitError(
                    "reconciliation observation attempt limit reached"
                )
            attempts[outcome.observation_attempt_id] = outcome
            next_revision = revision + 1
            record = self._record(
                reconciliation_id=outcome.reconciliation_id,
                revision=next_revision,
                attempts=attempts,
                terminal_outcome=outcome if terminal else None,
                outbox=(
                    {
                        event.idempotency_key: ReconciliationOutboxRecord(event=event)
                        for event in (ReconciliationOutboxEvent.from_outcome(outcome),)
                    }
                    if terminal
                    else outbox
                ),
            )
            if await self._store.compare_and_set_state_with_audit(
                key,
                record,
                expected_revision=revision,
                audit_entry=self._audit_entry(
                    outcome,
                    terminal=terminal,
                    revision=next_revision,
                ),
            ):
                return outcome
        raise RuntimeError("reconciliation ledger update conflicted repeatedly")

    def _new_record(
        self,
        outcome: ReconciliationOutcome,
        *,
        terminal: bool,
    ) -> dict[str, Any]:
        outbox_event = ReconciliationOutboxEvent.from_outcome(outcome) if terminal else None
        return self._record(
            reconciliation_id=outcome.reconciliation_id,
            revision=1,
            attempts={outcome.observation_attempt_id: outcome},
            terminal_outcome=outcome if terminal else None,
            outbox=(
                {outbox_event.idempotency_key: ReconciliationOutboxRecord(event=outbox_event)}
                if outbox_event is not None
                else {}
            ),
        )

    def _record(
        self,
        *,
        reconciliation_id: str,
        revision: int,
        attempts: Mapping[str, ReconciliationOutcome],
        terminal_outcome: ReconciliationOutcome | None,
        outbox: Mapping[str, ReconciliationOutboxRecord],
    ) -> dict[str, Any]:
        outbox_state = next(iter(outbox.values())).state.value if outbox else None
        record = {
            "schema_version": self._SCHEMA_VERSION,
            "reconciliation_id": reconciliation_id,
            "revision": revision,
            "attempts": {
                attempt_id: attempt.model_dump(mode="json")
                for attempt_id, attempt in attempts.items()
            },
            "terminal_outcome": (
                terminal_outcome.model_dump(mode="json") if terminal_outcome is not None else None
            ),
            "outbox": {
                idempotency_key: delivery.model_dump(mode="json")
                for idempotency_key, delivery in outbox.items()
            },
            "outbox_state": outbox_state,
        }
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded) > self._MAX_AGGREGATE_BYTES:
            raise ReconciliationAggregateLimitError(
                "durable reconciliation aggregate exceeds its canonical byte limit"
            )
        return record

    def _parse_record(
        self,
        record: Mapping[str, Any],
        *,
        reconciliation_id: str,
    ) -> tuple[
        int,
        dict[str, ReconciliationOutcome],
        ReconciliationOutcome | None,
        dict[str, ReconciliationOutboxRecord],
    ]:
        try:
            if (
                record.get("schema_version") != self._SCHEMA_VERSION
                or record.get("reconciliation_id") != reconciliation_id
                or not isinstance(record.get("revision"), int)
                or isinstance(record.get("revision"), bool)
                or int(record["revision"]) < 1
                or not isinstance(record.get("attempts"), Mapping)
                or not isinstance(record.get("outbox"), Mapping)
                or record.get("outbox_state")
                not in {
                    None,
                    ReconciliationOutboxDeliveryState.PENDING.value,
                    ReconciliationOutboxDeliveryState.CLAIMED.value,
                    ReconciliationOutboxDeliveryState.PUBLISHED.value,
                }
            ):
                raise ValueError("invalid reconciliation aggregate metadata")
            attempts = {
                str(attempt_id): ReconciliationOutcome.model_validate(payload)
                for attempt_id, payload in record["attempts"].items()
            }
            if any(
                attempt_id != attempt.observation_attempt_id
                or attempt.reconciliation_id != reconciliation_id
                for attempt_id, attempt in attempts.items()
            ):
                raise ValueError("attempt identity does not match reconciliation aggregate")
            if len(attempts) > self._MAX_ATTEMPTS_PER_RECONCILIATION:
                raise ValueError("reconciliation aggregate exceeds its attempt limit")
            terminal_payload = record.get("terminal_outcome")
            terminal_outcome = (
                ReconciliationOutcome.model_validate(terminal_payload)
                if terminal_payload is not None
                else None
            )
            outbox = {
                str(idempotency_key): ReconciliationOutboxRecord.model_validate(payload)
                for idempotency_key, payload in record["outbox"].items()
            }
            if any(
                idempotency_key != delivery.event.idempotency_key
                for idempotency_key, delivery in outbox.items()
            ):
                raise ValueError("outbox identity does not match reconciliation aggregate")
            if terminal_outcome is None:
                if (
                    outbox
                    or record.get("outbox_state") is not None
                    or len(attempts) >= self._MAX_ATTEMPTS_PER_RECONCILIATION
                ):
                    raise ValueError("non-terminal reconciliation aggregate contains outbox state")
            else:
                expected_event = ReconciliationOutboxEvent.from_outcome(terminal_outcome)
                delivery = outbox.get(expected_event.idempotency_key)
                if (
                    not terminal_outcome.terminal
                    or terminal_outcome.reconciliation_id != reconciliation_id
                    or attempts.get(terminal_outcome.observation_attempt_id) != terminal_outcome
                    or len(outbox) != 1
                    or delivery is None
                    or delivery.event != expected_event
                    or record.get("outbox_state") != delivery.state.value
                ):
                    raise ValueError("terminal reconciliation aggregate is not atomic and bound")
            return int(record["revision"]), attempts, terminal_outcome, outbox
        except (TypeError, ValueError) as exc:
            raise ReconciliationLedgerCorruptionError(
                "durable reconciliation state failed validation"
            ) from exc

    @staticmethod
    def _audit_entry(
        outcome: ReconciliationOutcome,
        *,
        terminal: bool,
        revision: int,
    ) -> dict[str, Any]:
        return {
            "actor": "fdai.core.ontology_platform.reconciliation",
            "action_kind": (
                "ontology.reconciliation.terminal_committed"
                if terminal
                else "ontology.reconciliation.attempt_recorded"
            ),
            "reconciliation_id": outcome.reconciliation_id,
            "observation_attempt_id": outcome.observation_attempt_id,
            "request_digest": outcome.request_digest,
            "receipt_digest": outcome.receipt_digest,
            "recommendation_idempotency_key": outcome.recommendation.idempotency_key,
            "revision": revision,
        }

    @staticmethod
    def _outbox_audit_entry(
        event: ReconciliationOutboxEvent,
        *,
        action_kind: str,
        revision: int,
    ) -> dict[str, Any]:
        return {
            "actor": "fdai.core.ontology_platform.reconciliation",
            "action_kind": action_kind,
            "reconciliation_id": event.result.reconciliation_id,
            "observation_attempt_id": event.result.observation_attempt_id,
            "result_digest": event.result.result_digest,
            "recommendation_idempotency_key": event.idempotency_key,
            "revision": revision,
        }
