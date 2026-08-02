"""Deterministic in-memory user-context stores for tests and local development."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime

from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserContextConflictError,
    UserMemoryFact,
    UserPreferenceRecord,
)


class InMemoryConversationHistoryStore:
    def __init__(self) -> None:
        self._conversations: dict[tuple[str, str], ConversationRecord] = {}
        self._turns: dict[tuple[str, str], list[ConversationTurnRecord]] = {}
        self._turn_keys: dict[tuple[str, str], ConversationTurnRecord] = {}

    async def create_conversation(self, record: ConversationRecord) -> ConversationRecord:
        key = (record.principal_id, record.conversation_id)
        existing = self._conversations.get(key)
        if existing is not None:
            if existing.channel_id != record.channel_id:
                raise UserContextConflictError(
                    f"conversation {record.conversation_id!r} already exists"
                )
            return existing
        self._conversations[key] = record
        self._turns[key] = []
        return record

    async def get_conversation(
        self, *, principal_id: str, conversation_id: str
    ) -> ConversationRecord | None:
        return self._conversations.get((principal_id, conversation_id))

    async def list_conversations(
        self, *, principal_id: str, limit: int = 50
    ) -> tuple[ConversationRecord, ...]:
        _validate_limit(limit)
        found = [
            record for (owner, _), record in self._conversations.items() if owner == principal_id
        ]
        found.sort(key=lambda item: (item.last_active, item.conversation_id), reverse=True)
        return tuple(found[:limit])

    async def append_turn(
        self,
        record: ConversationTurnRecord,
        *,
        allocate_index: bool = False,
    ) -> ConversationTurnRecord:
        conversation_key = (record.principal_id, record.conversation_id)
        if conversation_key not in self._conversations:
            raise LookupError(f"conversation {record.conversation_id!r} not found")
        idempotency_key = (record.principal_id, record.idempotency_key)
        existing = self._turn_keys.get(idempotency_key)
        if existing is not None:
            if not _same_turn(existing, record, ignore_index=allocate_index):
                raise UserContextConflictError(
                    f"turn idempotency key {record.idempotency_key!r} conflicts"
                )
            return existing
        turns = self._turns[conversation_key]
        if allocate_index:
            record = replace(
                record,
                turn_index=(max((item.turn_index for item in turns), default=-1) + 1),
            )
        if any(item.turn_index == record.turn_index for item in turns):
            raise UserContextConflictError(
                f"conversation {record.conversation_id!r} already has turn index "
                f"{record.turn_index}"
            )
        turns.append(record)
        turns.sort(key=lambda item: item.turn_index)
        self._turn_keys[idempotency_key] = record
        conversation = self._conversations[conversation_key]
        if record.recorded_at > conversation.last_active:
            self._conversations[conversation_key] = replace(
                conversation, last_active=record.recorded_at
            )
        return record

    async def get_turn_by_idempotency(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
    ) -> ConversationTurnRecord | None:
        return self._turn_keys.get((principal_id, idempotency_key))

    async def list_turns(
        self, *, principal_id: str, conversation_id: str, limit: int = 200
    ) -> tuple[ConversationTurnRecord, ...]:
        _validate_limit(limit)
        return tuple(self._turns.get((principal_id, conversation_id), ())[-limit:])

    async def list_all_turns(
        self, *, principal_id: str, conversation_id: str
    ) -> tuple[ConversationTurnRecord, ...]:
        return tuple(self._turns.get((principal_id, conversation_id), ()))

    async def latest_operator_turn_ids(
        self,
        *,
        principal_id: str,
        conversation_ids: Sequence[str],
    ) -> Mapping[str, str]:
        requested = set(conversation_ids)
        latest: dict[str, tuple[int, str]] = {}
        for turns in self._turns.values():
            for turn in turns:
                if (
                    turn.principal_id != principal_id
                    or turn.conversation_id not in requested
                    or turn.role is not ConversationTurnRole.OPERATOR
                ):
                    continue
                current = latest.get(turn.conversation_id)
                if current is None or turn.turn_index > current[0]:
                    latest[turn.conversation_id] = (turn.turn_index, turn.turn_id)
        return {conversation_id: value[1] for conversation_id, value in latest.items()}

    async def delete_conversation(self, *, principal_id: str, conversation_id: str) -> bool:
        key = (principal_id, conversation_id)
        conversation = self._conversations.pop(key, None)
        turns = self._turns.pop(key, [])
        for turn in turns:
            self._turn_keys.pop((principal_id, turn.idempotency_key), None)
        return conversation is not None

    async def purge_inactive(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> tuple[ConversationRecord, ...]:
        _validate_limit(limit)
        selected = sorted(
            (record for record in self._conversations.values() if record.last_active < before),
            key=lambda item: (item.last_active, item.conversation_id),
        )[:limit]
        for record in selected:
            await self.delete_conversation(
                principal_id=record.principal_id,
                conversation_id=record.conversation_id,
            )
        return tuple(selected)


class InMemoryUserPreferenceStore:
    def __init__(self) -> None:
        self._records: dict[str, UserPreferenceRecord] = {}

    async def get(self, *, principal_id: str) -> UserPreferenceRecord | None:
        return self._records.get(principal_id)

    async def put(
        self,
        record: UserPreferenceRecord,
        *,
        expected_revision: int | None = None,
    ) -> UserPreferenceRecord:
        existing = self._records.get(record.principal_id)
        current_revision = existing.revision if existing is not None else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise UserContextConflictError(
                f"preference revision mismatch: expected {expected_revision}, "
                f"current {current_revision}"
            )
        stored = replace(record, revision=current_revision + 1)
        self._records[record.principal_id] = stored
        return stored

    async def delete(self, *, principal_id: str) -> bool:
        return self._records.pop(principal_id, None) is not None


class InMemoryUserMemoryStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], UserMemoryFact] = {}

    async def create(self, fact: UserMemoryFact) -> UserMemoryFact:
        key = (fact.principal_id, fact.memory_id)
        existing = self._records.get(key)
        if existing is not None:
            if existing != fact:
                raise UserContextConflictError(f"memory {fact.memory_id!r} already exists")
            return existing
        self._records[key] = fact
        return fact

    async def list_active(
        self, *, principal_id: str, now: datetime, limit: int = 100
    ) -> tuple[UserMemoryFact, ...]:
        _validate_limit(limit)
        found = [
            fact
            for (owner, _), fact in self._records.items()
            if owner == principal_id
            and fact.superseded_by is None
            and (fact.expires_at is None or fact.expires_at > now)
        ]
        found.sort(key=lambda item: (item.created_at, item.memory_id))
        return tuple(found[:limit])

    async def supersede(self, *, principal_id: str, memory_id: str, superseded_by: str) -> None:
        key = (principal_id, memory_id)
        existing = self._records.get(key)
        if existing is None:
            raise LookupError(f"memory {memory_id!r} not found")
        replacement = self._records.get((principal_id, superseded_by))
        if replacement is None:
            raise LookupError(f"replacement memory {superseded_by!r} not found")
        if existing.superseded_by is not None:
            raise UserContextConflictError(f"memory {memory_id!r} is already superseded")
        self._records[key] = replace(existing, superseded_by=superseded_by)

    async def delete(self, *, principal_id: str, memory_id: str) -> bool:
        return self._records.pop((principal_id, memory_id), None) is not None

    async def purge_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[UserMemoryFact, ...]:
        _validate_limit(limit)
        selected = sorted(
            (
                fact
                for fact in self._records.values()
                if fact.expires_at is not None and fact.expires_at <= now
            ),
            key=lambda item: (item.expires_at or now, item.memory_id),
        )[:limit]
        for fact in selected:
            self._records.pop((fact.principal_id, fact.memory_id), None)
        return tuple(selected)


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit MUST be in [1, 1000]")


def _same_turn(
    existing: ConversationTurnRecord,
    candidate: ConversationTurnRecord,
    *,
    ignore_index: bool,
) -> bool:
    candidate = replace(candidate, recorded_at=existing.recorded_at)
    if ignore_index:
        candidate = replace(candidate, turn_index=existing.turn_index)
    return existing == candidate


__all__ = [
    "InMemoryConversationHistoryStore",
    "InMemoryUserMemoryStore",
    "InMemoryUserPreferenceStore",
]
