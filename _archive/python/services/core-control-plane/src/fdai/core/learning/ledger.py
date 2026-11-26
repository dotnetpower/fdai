"""Restart-safe status ledger contract for post-turn review attempts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from fdai.core.learning.models import EligibilityReason, PostTurnProposalKind


class PostTurnReviewState(StrEnum):
    PENDING = "pending"
    INELIGIBLE = "ineligible"
    ABSTAINED = "abstained"
    DUPLICATE = "duplicate"
    ROUTED = "routed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PostTurnReviewRecord:
    review_id: str
    principal_scope: str
    state: PostTurnReviewState
    reasons: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    proposal_kind: PostTurnProposalKind | None = None
    proposal_ref: str | None = None
    dedup_key: str | None = None


class PostTurnReviewLedger(Protocol):
    async def start(self, record: PostTurnReviewRecord) -> tuple[PostTurnReviewRecord, bool]: ...

    async def reserve_proposal(self, *, review_id: str, dedup_key: str) -> bool: ...

    async def finish(
        self,
        review_id: str,
        *,
        state: PostTurnReviewState,
        reasons: tuple[str, ...],
        updated_at: datetime,
        proposal_kind: PostTurnProposalKind | None = None,
        proposal_ref: str | None = None,
        dedup_key: str | None = None,
    ) -> PostTurnReviewRecord: ...

    async def get(self, review_id: str) -> PostTurnReviewRecord: ...

    async def list(self) -> tuple[PostTurnReviewRecord, ...]: ...


class InMemoryPostTurnReviewLedger:
    """Deterministic test/dev ledger with the durable adapter's CAS semantics."""

    def __init__(self) -> None:
        self._records: dict[str, PostTurnReviewRecord] = {}
        self._proposal_keys: set[str] = set()

    async def start(self, record: PostTurnReviewRecord) -> tuple[PostTurnReviewRecord, bool]:
        prior = self._records.get(record.review_id)
        if prior is not None:
            return prior, False
        self._records[record.review_id] = record
        return record, True

    async def reserve_proposal(self, *, review_id: str, dedup_key: str) -> bool:
        current = await self.get(review_id)
        if current.state is not PostTurnReviewState.PENDING:
            return False
        if dedup_key in self._proposal_keys:
            return False
        self._proposal_keys.add(dedup_key)
        return True

    async def finish(
        self,
        review_id: str,
        *,
        state: PostTurnReviewState,
        reasons: tuple[str, ...],
        updated_at: datetime,
        proposal_kind: PostTurnProposalKind | None = None,
        proposal_ref: str | None = None,
        dedup_key: str | None = None,
    ) -> PostTurnReviewRecord:
        current = await self.get(review_id)
        if current.state is not PostTurnReviewState.PENDING:
            return current
        terminal = replace(
            current,
            state=state,
            reasons=reasons,
            updated_at=updated_at,
            proposal_kind=proposal_kind,
            proposal_ref=proposal_ref,
            dedup_key=dedup_key,
        )
        self._records[review_id] = terminal
        return terminal

    async def get(self, review_id: str) -> PostTurnReviewRecord:
        try:
            return self._records[review_id]
        except KeyError as exc:
            raise LookupError(f"post-turn review {review_id!r} was not found") from exc

    async def list(self) -> tuple[PostTurnReviewRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


def pending_record(
    *,
    review_id: str,
    principal_scope: str,
    reasons: tuple[EligibilityReason, ...],
    at: datetime,
) -> PostTurnReviewRecord:
    return PostTurnReviewRecord(
        review_id=review_id,
        principal_scope=principal_scope,
        state=PostTurnReviewState.PENDING,
        reasons=tuple(reason.value for reason in reasons),
        created_at=at,
        updated_at=at,
    )


__all__ = [
    "InMemoryPostTurnReviewLedger",
    "PostTurnReviewLedger",
    "PostTurnReviewRecord",
    "PostTurnReviewState",
    "pending_record",
]
