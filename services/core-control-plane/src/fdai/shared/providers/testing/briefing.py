"""In-memory conversation-policy and briefing stores."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from fdai.shared.providers.briefing import (
    BriefingConflictError,
    BriefingRun,
    BriefingSubscription,
    ConversationPolicyRecord,
)


class InMemoryConversationPolicyStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ConversationPolicyRecord] = {}

    async def put(
        self, record: ConversationPolicyRecord, *, expected_revision: int | None = None
    ) -> ConversationPolicyRecord:
        key = (record.principal_id, record.policy_id)
        existing = self._records.get(key)
        current_revision = existing.revision if existing is not None else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise BriefingConflictError(
                f"policy revision mismatch: expected {expected_revision}, "
                f"current {current_revision}"
            )
        stored = replace(record, revision=current_revision + 1)
        self._records[key] = stored
        return stored

    async def list_for_principal(
        self, *, principal_id: str
    ) -> tuple[ConversationPolicyRecord, ...]:
        found = [record for (owner, _), record in self._records.items() if owner == principal_id]
        return tuple(sorted(found, key=lambda item: item.policy_id))

    async def delete(
        self,
        *,
        principal_id: str,
        policy_id: str,
        expected_revision: int,
    ) -> bool:
        current = self._records.get((principal_id, policy_id))
        if current is not None and current.revision != expected_revision:
            raise BriefingConflictError("policy revision mismatch")
        return self._records.pop((principal_id, policy_id), None) is not None


class InMemoryBriefingSubscriptionStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], BriefingSubscription] = {}
        self._leases: dict[str, tuple[str, datetime]] = {}

    async def create(self, record: BriefingSubscription) -> BriefingSubscription:
        key = (record.principal_id, record.subscription_id)
        existing = self._records.get(key)
        if existing is not None:
            if existing != record:
                raise BriefingConflictError(
                    f"subscription {record.subscription_id!r} already exists"
                )
            return existing
        stored = replace(record, revision=1)
        self._records[key] = stored
        return stored

    async def list_for_principal(self, *, principal_id: str) -> tuple[BriefingSubscription, ...]:
        found = [record for (owner, _), record in self._records.items() if owner == principal_id]
        return tuple(sorted(found, key=lambda item: (item.next_run_at, item.subscription_id)))

    async def claim_due(
        self, *, now: datetime, limit: int, lease_owner: str, lease_seconds: int
    ) -> tuple[BriefingSubscription, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        if lease_seconds < 1:
            raise ValueError("lease_seconds MUST be >= 1")
        due: list[BriefingSubscription] = []
        for record in sorted(
            self._records.values(), key=lambda item: (item.next_run_at, item.subscription_id)
        ):
            lease = self._leases.get(record.subscription_id)
            if not record.enabled or record.next_run_at > now:
                continue
            if lease is not None and lease[1] > now:
                continue
            self._leases[record.subscription_id] = (
                lease_owner,
                now + timedelta(seconds=lease_seconds),
            )
            due.append(record)
            if len(due) >= limit:
                break
        return tuple(due)

    async def advance(
        self,
        *,
        subscription_id: str,
        principal_id: str,
        expected_revision: int,
        next_run_at: datetime,
    ) -> BriefingSubscription:
        key = (principal_id, subscription_id)
        existing = self._records.get(key)
        if existing is None:
            raise LookupError(f"subscription {subscription_id!r} not found")
        if existing.revision != expected_revision:
            raise BriefingConflictError(
                f"subscription revision mismatch: expected {expected_revision}, "
                f"current {existing.revision}"
            )
        stored = replace(existing, next_run_at=next_run_at, revision=existing.revision + 1)
        self._records[key] = stored
        self._leases.pop(subscription_id, None)
        return stored

    async def delete(
        self,
        *,
        principal_id: str,
        subscription_id: str,
        expected_revision: int,
    ) -> bool:
        current = self._records.get((principal_id, subscription_id))
        if current is not None and current.revision != expected_revision:
            raise BriefingConflictError("subscription revision mismatch")
        self._leases.pop(subscription_id, None)
        return self._records.pop((principal_id, subscription_id), None) is not None


class InMemoryBriefingRunStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], BriefingRun] = {}
        self._idempotency: dict[tuple[str, str], BriefingRun] = {}

    async def create(self, run: BriefingRun) -> BriefingRun:
        idem_key = (run.principal_id, run.idempotency_key)
        existing = self._idempotency.get(idem_key)
        if existing is not None:
            if existing != run:
                raise BriefingConflictError(
                    f"briefing run idempotency key {run.idempotency_key!r} conflicts"
                )
            return existing
        key = (run.principal_id, run.run_id)
        if key in self._records:
            raise BriefingConflictError(f"briefing run {run.run_id!r} already exists")
        self._records[key] = run
        self._idempotency[idem_key] = run
        return run

    async def list_for_principal(
        self, *, principal_id: str, limit: int = 100
    ) -> tuple[BriefingRun, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        found = [record for (owner, _), record in self._records.items() if owner == principal_id]
        found.sort(key=lambda item: (item.started_at, item.run_id), reverse=True)
        return tuple(found[:limit])

    async def purge_before(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> tuple[BriefingRun, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit MUST be in [1, 1000]")
        selected = sorted(
            (record for record in self._records.values() if record.started_at < before),
            key=lambda item: (item.started_at, item.run_id),
        )[:limit]
        for run in selected:
            self._records.pop((run.principal_id, run.run_id), None)
            self._idempotency.pop((run.principal_id, run.idempotency_key), None)
        return tuple(selected)


__all__ = [
    "InMemoryBriefingRunStore",
    "InMemoryBriefingSubscriptionStore",
    "InMemoryConversationPolicyStore",
]
