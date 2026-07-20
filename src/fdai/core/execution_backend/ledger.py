"""In-memory reference implementation of the execution submission ledger."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from fdai.shared.providers.execution_backend import (
    ExecutionAttempt,
    ExecutionLedgerRecord,
)


class InMemoryExecutionSubmissionLedger:
    """CAS ledger used by focused tests and explicit fixture composition."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionLedgerRecord] = {}
        self._attempts: dict[str, list[ExecutionAttempt]] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: ExecutionLedgerRecord) -> ExecutionLedgerRecord:
        async with self._lock:
            existing = self._records.get(record.idempotency_key)
            if existing is not None:
                return existing
            self._records[record.idempotency_key] = record
            return record

    async def get(self, idempotency_key: str) -> ExecutionLedgerRecord | None:
        async with self._lock:
            return self._records.get(idempotency_key)

    async def update(
        self,
        record: ExecutionLedgerRecord,
        *,
        expected_revision: int,
    ) -> ExecutionLedgerRecord:
        async with self._lock:
            current = self._records.get(record.idempotency_key)
            if current is None:
                raise LookupError("execution ledger record disappeared")
            if current.revision != expected_revision:
                raise RuntimeError("execution ledger revision conflict")
            updated = replace(record, revision=expected_revision + 1)
            self._records[record.idempotency_key] = updated
            return updated

    async def append_attempt(self, attempt: ExecutionAttempt) -> None:
        async with self._lock:
            values = self._attempts.setdefault(attempt.idempotency_key, [])
            if any(item.sequence == attempt.sequence for item in values):
                return
            values.append(attempt)

    async def attempts(self, idempotency_key: str) -> tuple[ExecutionAttempt, ...]:
        async with self._lock:
            return tuple(self._attempts.get(idempotency_key, ()))


__all__ = ["InMemoryExecutionSubmissionLedger"]
