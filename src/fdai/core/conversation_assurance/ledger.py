"""Append-only in-memory ledger and persistence protocol for assurance."""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from fdai.core.conversation_assurance.models import AssessmentRecord, DisputeRecord


@runtime_checkable
class ConversationAssuranceLedger(Protocol):
    async def append_assessment(self, record: AssessmentRecord) -> bool: ...

    async def append_dispute(self, record: DisputeRecord) -> bool: ...

    async def get_assessment(
        self,
        *,
        principal_scope: str,
        assessment_id: str,
    ) -> AssessmentRecord | None: ...

    async def list_assessments(
        self,
        *,
        principal_scope: str,
        limit: int = 100,
    ) -> tuple[AssessmentRecord, ...]: ...

    async def list_disputes(
        self,
        *,
        principal_scope: str,
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> tuple[DisputeRecord, ...]: ...


class InMemoryConversationAssuranceLedger:
    """Process-local adapter with the same append-only semantics as persistence."""

    def __init__(self) -> None:
        self._assessments: dict[str, AssessmentRecord] = {}
        self._disputes: dict[str, DisputeRecord] = {}
        self._lock = asyncio.Lock()

    async def append_assessment(self, record: AssessmentRecord) -> bool:
        async with self._lock:
            existing = self._assessments.get(record.assessment_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("assessment id already belongs to different content")
                return False
            self._assessments[record.assessment_id] = record
            return True

    async def append_dispute(self, record: DisputeRecord) -> bool:
        async with self._lock:
            assessment = self._assessments.get(record.assessment_id)
            if assessment is None or assessment.principal_scope != record.principal_scope:
                raise LookupError("assessment is unavailable in the principal scope")
            existing = self._disputes.get(record.dispute_id)
            if existing is not None:
                if not same_dispute_request(existing, record):
                    raise ValueError("dispute id already belongs to different content")
                return False
            self._disputes[record.dispute_id] = record
            return True

    async def get_assessment(
        self,
        *,
        principal_scope: str,
        assessment_id: str,
    ) -> AssessmentRecord | None:
        record = self._assessments.get(assessment_id)
        return record if record is not None and record.principal_scope == principal_scope else None

    async def list_assessments(
        self,
        *,
        principal_scope: str,
        limit: int = 100,
    ) -> tuple[AssessmentRecord, ...]:
        _require_limit(limit)
        records = (
            item for item in self._assessments.values() if item.principal_scope == principal_scope
        )
        return tuple(
            sorted(records, key=lambda item: (item.assessed_at, item.assessment_id), reverse=True)[
                :limit
            ]
        )

    async def list_disputes(
        self,
        *,
        principal_scope: str,
        assessment_id: str | None = None,
        limit: int = 100,
    ) -> tuple[DisputeRecord, ...]:
        _require_limit(limit)
        records = (
            item
            for item in self._disputes.values()
            if item.principal_scope == principal_scope
            and (assessment_id is None or item.assessment_id == assessment_id)
        )
        return tuple(
            sorted(records, key=lambda item: (item.reported_at, item.dispute_id), reverse=True)[
                :limit
            ]
        )


def _require_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError("assurance list limit MUST be in [1, 1000]")


def same_dispute_request(first: DisputeRecord, second: DisputeRecord) -> bool:
    """Compare idempotent request content while preserving the first timestamp."""

    return (
        first.dispute_id == second.dispute_id
        and first.assessment_id == second.assessment_id
        and first.principal_scope == second.principal_scope
        and first.reported_by == second.reported_by
        and first.reason is second.reason
        and first.detail == second.detail
        and first.evidence_refs == second.evidence_refs
    )


__all__ = [
    "ConversationAssuranceLedger",
    "InMemoryConversationAssuranceLedger",
    "same_dispute_request",
]
