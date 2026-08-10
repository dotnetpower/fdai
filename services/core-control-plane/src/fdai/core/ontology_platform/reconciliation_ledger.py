"""Atomic attempt, terminal outcome, and publication persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from fdai.shared.providers.state_store import StateStore

from .reconciliation_contracts import (
    ReconciliationOutcome,
    ReconciliationRecommendation,
)
from .reconciliation_publication import (
    InMemoryReconciliationPublicationOutbox,
    ReconciliationAggregateLimitError,
    ReconciliationConflictError,
    ReconciliationLedgerCorruptionError,
    ReconciliationPublication,
    StateStoreReconciliationPublicationOutbox,
    deserialize_publication,
    initial_publication_state,
    serialize_publication,
)


class ReconciliationAttemptLimitError(RuntimeError):
    """A reconciliation exhausted its bounded non-terminal observation attempts."""


class ReconciliationLedger(Protocol):
    """Persistence seam for attempt evidence and atomic terminal outcome plus outbox."""

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome: ...

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome: ...

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ReconciliationPublication, ...]: ...

    async def complete_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        published_at: datetime,
        topic: str,
        partition: int,
        offset: int | None,
        lease_token: str,
    ) -> None: ...

    async def release_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        available_at: datetime,
        error: str,
        lease_token: str,
    ) -> None: ...

    async def dead_letter_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        failed_at: datetime,
        error: str,
        lease_token: str,
    ) -> None: ...


class InMemoryReconciliationLedger:
    """Concurrency-safe reference ledger for local composition and focused tests."""

    _MAX_ATTEMPTS_PER_RECONCILIATION = 8

    def __init__(self) -> None:
        self._attempts: dict[str, ReconciliationOutcome] = {}
        self._terminal_outcomes: dict[str, ReconciliationOutcome] = {}
        self._outbox: dict[str, ReconciliationRecommendation] = {}
        self._publication_outbox = InMemoryReconciliationPublicationOutbox()
        self._lock = asyncio.Lock()

    @property
    def attempts(self) -> tuple[ReconciliationOutcome, ...]:
        return tuple(self._attempts.values())

    @property
    def terminal_outcomes(self) -> tuple[ReconciliationOutcome, ...]:
        return tuple(self._terminal_outcomes.values())

    @property
    def outbox(self) -> tuple[ReconciliationRecommendation, ...]:
        return tuple(self._outbox.values())

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if outcome.terminal:
            raise ValueError("terminal reconciliation MUST use commit_terminal")
        async with self._lock:
            existing = self._attempts.get(outcome.observation_attempt_id)
            if existing is None:
                attempt_count = sum(
                    attempt.reconciliation_id == outcome.reconciliation_id
                    for attempt in self._attempts.values()
                )
                if attempt_count >= self._MAX_ATTEMPTS_PER_RECONCILIATION - 1:
                    raise ReconciliationAttemptLimitError(
                        "reconciliation non-terminal observation attempt limit reached"
                    )
                self._attempts[outcome.observation_attempt_id] = outcome
                return outcome
            if existing.request_digest != outcome.request_digest:
                raise ReconciliationConflictError(
                    "reconciliation attempt identity reused with different request content"
                )
            return existing

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        """Atomically persist one terminal attempt, outcome, and proposal-only outbox event."""

        if not outcome.terminal:
            raise ValueError("unscorable reconciliation is attempt evidence, not terminal closure")
        async with self._lock:
            existing = self._terminal_outcomes.get(outcome.reconciliation_id)
            if existing is not None:
                if existing.request_digest != outcome.request_digest:
                    raise ReconciliationConflictError(
                        "reconciliation terminal identity reused with different request content"
                    )
                return existing
            existing_attempt = self._attempts.get(outcome.observation_attempt_id)
            if (
                existing_attempt is not None
                and existing_attempt.request_digest != outcome.request_digest
            ):
                raise ReconciliationConflictError(
                    "reconciliation attempt identity reused with different request content"
                )
            attempt_count = sum(
                attempt.reconciliation_id == outcome.reconciliation_id
                for attempt in self._attempts.values()
            )
            if existing_attempt is None and attempt_count >= self._MAX_ATTEMPTS_PER_RECONCILIATION:
                raise ReconciliationAttemptLimitError(
                    "reconciliation terminal observation attempt limit reached"
                )
            self._attempts[outcome.observation_attempt_id] = outcome
            self._terminal_outcomes[outcome.reconciliation_id] = outcome
            self._outbox[outcome.recommendation.idempotency_key] = outcome.recommendation
            self._publication_outbox.register(outcome.recommendation)
            return outcome

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ReconciliationPublication, ...]:
        return await self._publication_outbox.claim_publications(
            now=now,
            limit=limit,
            lease_until=lease_until,
        )

    async def complete_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        published_at: datetime,
        topic: str,
        partition: int,
        offset: int | None,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.complete_publication(
            reconciliation_id,
            idempotency_key,
            published_at=published_at,
            topic=topic,
            partition=partition,
            offset=offset,
            lease_token=lease_token,
        )

    async def release_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        available_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.release_publication(
            reconciliation_id,
            idempotency_key,
            available_at=available_at,
            error=error,
            lease_token=lease_token,
        )

    async def dead_letter_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        failed_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.dead_letter_publication(
            reconciliation_id,
            idempotency_key,
            failed_at=failed_at,
            error=error,
            lease_token=lease_token,
        )


class StateStoreReconciliationLedger:
    """Durable reconciliation aggregate with atomic terminal outcome and outbox state."""

    _KEY_PREFIX = "ontology:reconciliation:"
    _SCHEMA_VERSION = "1.0.0"
    _MAX_CAS_ATTEMPTS = 64
    _MAX_ATTEMPTS_PER_RECONCILIATION = 8
    _MAX_AGGREGATE_BYTES = 16 * 1_048_576

    def __init__(self, *, store: StateStore) -> None:
        self._store = store
        self._publication_outbox = StateStoreReconciliationPublicationOutbox(store)

    async def record_attempt(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if outcome.terminal:
            raise ValueError("terminal reconciliation MUST use commit_terminal")
        return await self._persist(outcome, terminal=False)

    async def commit_terminal(self, outcome: ReconciliationOutcome) -> ReconciliationOutcome:
        if not outcome.terminal:
            raise ValueError("unscorable reconciliation is attempt evidence, not terminal closure")
        return await self._persist(outcome, terminal=True)

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
            revision, attempts, terminal_outcome, publications = self._parse_record(
                existing_record,
                reconciliation_id=outcome.reconciliation_id,
            )
            if terminal_outcome is not None:
                if terminal_outcome.request_digest != outcome.request_digest:
                    raise ReconciliationConflictError(
                        "reconciliation terminal identity reused with different request content"
                    )
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
                publications=(
                    initial_publication_state(outcome.recommendation) if terminal else publications
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
        return self._record(
            reconciliation_id=outcome.reconciliation_id,
            revision=1,
            attempts={outcome.observation_attempt_id: outcome},
            terminal_outcome=outcome if terminal else None,
            publications=(initial_publication_state(outcome.recommendation) if terminal else {}),
        )

    def _record(
        self,
        *,
        reconciliation_id: str,
        revision: int,
        attempts: Mapping[str, ReconciliationOutcome],
        terminal_outcome: ReconciliationOutcome | None,
        publications: Mapping[str, ReconciliationPublication],
    ) -> dict[str, Any]:
        outbox = (
            {
                terminal_outcome.recommendation.idempotency_key: (
                    terminal_outcome.recommendation.model_dump(mode="json")
                )
            }
            if terminal_outcome is not None
            else {}
        )
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
            "outbox": outbox,
            "publication_state": {
                idempotency_key: serialize_publication(publication)
                for idempotency_key, publication in publications.items()
            },
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
        dict[str, ReconciliationPublication],
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
            publication_raw = record.get("publication_state", {})
            if not isinstance(publication_raw, Mapping):
                raise ValueError("reconciliation publication state MUST be an object")
            if terminal_outcome is None:
                if (
                    record["outbox"]
                    or publication_raw
                    or len(attempts) >= self._MAX_ATTEMPTS_PER_RECONCILIATION
                ):
                    raise ValueError("non-terminal reconciliation aggregate contains outbox state")
                publications: dict[str, ReconciliationPublication] = {}
            else:
                recommendation = terminal_outcome.recommendation
                if (
                    not terminal_outcome.terminal
                    or terminal_outcome.reconciliation_id != reconciliation_id
                    or attempts.get(terminal_outcome.observation_attempt_id) != terminal_outcome
                    or record["outbox"]
                    != {recommendation.idempotency_key: recommendation.model_dump(mode="json")}
                ):
                    raise ValueError("terminal reconciliation aggregate is not atomic and bound")
                publications = (
                    initial_publication_state(recommendation)
                    if not publication_raw
                    else {
                        str(idempotency_key): deserialize_publication(payload)
                        for idempotency_key, payload in publication_raw.items()
                    }
                )
                if set(publications) != {recommendation.idempotency_key} or any(
                    publication.recommendation != recommendation
                    for publication in publications.values()
                ):
                    raise ValueError("reconciliation publication state is not bound to outbox")
            return int(record["revision"]), attempts, terminal_outcome, publications
        except (TypeError, ValueError) as exc:
            raise ReconciliationLedgerCorruptionError(
                "durable reconciliation state failed validation"
            ) from exc

    async def claim_publications(
        self,
        *,
        now: datetime,
        limit: int,
        lease_until: datetime,
    ) -> tuple[ReconciliationPublication, ...]:
        return await self._publication_outbox.claim_publications(
            now=now,
            limit=limit,
            lease_until=lease_until,
        )

    async def complete_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        published_at: datetime,
        topic: str,
        partition: int,
        offset: int | None,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.complete_publication(
            reconciliation_id,
            idempotency_key,
            published_at=published_at,
            topic=topic,
            partition=partition,
            offset=offset,
            lease_token=lease_token,
        )

    async def release_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        available_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.release_publication(
            reconciliation_id,
            idempotency_key,
            available_at=available_at,
            error=error,
            lease_token=lease_token,
        )

    async def dead_letter_publication(
        self,
        reconciliation_id: str,
        idempotency_key: str,
        *,
        failed_at: datetime,
        error: str,
        lease_token: str,
    ) -> None:
        await self._publication_outbox.dead_letter_publication(
            reconciliation_id,
            idempotency_key,
            failed_at=failed_at,
            error=error,
            lease_token=lease_token,
        )

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


__all__ = [
    "InMemoryReconciliationLedger",
    "ReconciliationAttemptLimitError",
    "ReconciliationLedger",
    "StateStoreReconciliationLedger",
]
