"""Per-user conversation, preference, and explicit memory persistence contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class ConversationTurnRole(StrEnum):
    OPERATOR = "operator"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class UserMemoryCategory(StrEnum):
    PREFERENCE = "preference"
    CONTEXT = "context"
    GOAL = "goal"


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: str
    principal_id: str
    channel_id: str
    started_at: datetime
    last_active: datetime
    status: ConversationStatus = ConversationStatus.ACTIVE

    def __post_init__(self) -> None:
        _require_text("ConversationRecord.conversation_id", self.conversation_id)
        _require_text("ConversationRecord.principal_id", self.principal_id)
        _require_text("ConversationRecord.channel_id", self.channel_id)
        _require_aware("ConversationRecord.started_at", self.started_at)
        _require_aware("ConversationRecord.last_active", self.last_active)
        if self.last_active < self.started_at:
            raise ValueError("ConversationRecord.last_active MUST be >= started_at")


@dataclass(frozen=True, slots=True)
class ConversationTurnRecord:
    turn_id: str
    conversation_id: str
    principal_id: str
    turn_index: int
    role: ConversationTurnRole
    content: str
    recorded_at: datetime
    idempotency_key: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text("ConversationTurnRecord.turn_id", self.turn_id)
        _require_text("ConversationTurnRecord.conversation_id", self.conversation_id)
        _require_text("ConversationTurnRecord.principal_id", self.principal_id)
        _require_text("ConversationTurnRecord.content", self.content)
        _require_text("ConversationTurnRecord.idempotency_key", self.idempotency_key)
        _require_aware("ConversationTurnRecord.recorded_at", self.recorded_at)
        if self.turn_index < 0:
            raise ValueError("ConversationTurnRecord.turn_index MUST be >= 0")


@dataclass(frozen=True, slots=True)
class UserPreferenceRecord:
    principal_id: str
    locale: str = "en"
    verbosity: str = "concise"
    answer_detail: str = "standard"
    answer_format: str = "prose"
    answer_preferences_enabled: bool = True
    answer_intent_detail: Mapping[str, str] = field(default_factory=dict)
    answer_intent_format: Mapping[str, str] = field(default_factory=dict)
    timezone: str | None = None
    share_with_learner: bool = False
    revision: int = 0
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_text("UserPreferenceRecord.principal_id", self.principal_id)
        if self.locale not in {"en", "ko"}:
            raise ValueError("UserPreferenceRecord.locale MUST be en or ko")
        if self.verbosity not in {"concise", "detailed"}:
            raise ValueError("UserPreferenceRecord.verbosity MUST be concise or detailed")
        if self.answer_detail not in {"brief", "standard", "deep"}:
            raise ValueError("UserPreferenceRecord.answer_detail MUST be brief, standard, or deep")
        if self.answer_format not in {
            "prose",
            "bullets",
            "numbered_steps",
            "table",
            "chart",
            "checklist",
            "mixed",
        }:
            raise ValueError("UserPreferenceRecord.answer_format is invalid")
        _validate_answer_intent_preferences(
            self.answer_intent_detail,
            values={"brief", "standard", "deep"},
            field_name="answer_intent_detail",
        )
        _validate_answer_intent_preferences(
            self.answer_intent_format,
            values={"prose", "bullets", "numbered_steps", "table", "chart", "checklist", "mixed"},
            field_name="answer_intent_format",
        )
        if self.timezone is not None:
            _require_text("UserPreferenceRecord.timezone", self.timezone)
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(f"unknown IANA timezone {self.timezone!r}") from exc
        if self.revision < 0:
            raise ValueError("UserPreferenceRecord.revision MUST be >= 0")
        if self.updated_at is not None:
            _require_aware("UserPreferenceRecord.updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class UserMemoryFact:
    memory_id: str
    principal_id: str
    category: UserMemoryCategory
    body: str
    source_turn_id: str
    consented_at: datetime
    created_at: datetime
    expires_at: datetime | None = None
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        _require_text("UserMemoryFact.memory_id", self.memory_id)
        _require_text("UserMemoryFact.principal_id", self.principal_id)
        _require_text("UserMemoryFact.body", self.body)
        _require_text("UserMemoryFact.source_turn_id", self.source_turn_id)
        _require_aware("UserMemoryFact.consented_at", self.consented_at)
        _require_aware("UserMemoryFact.created_at", self.created_at)
        if self.expires_at is not None:
            _require_aware("UserMemoryFact.expires_at", self.expires_at)
            if self.expires_at <= self.created_at:
                raise ValueError("UserMemoryFact.expires_at MUST be after created_at")
        if self.superseded_by is not None:
            _require_text("UserMemoryFact.superseded_by", self.superseded_by)
            if self.superseded_by == self.memory_id:
                raise ValueError("UserMemoryFact cannot supersede itself")


class UserContextConflictError(RuntimeError):
    """A durable user-context write conflicts with an existing record."""


@runtime_checkable
class ConversationHistoryStore(Protocol):
    async def create_conversation(self, record: ConversationRecord) -> ConversationRecord: ...

    async def get_conversation(
        self, *, principal_id: str, conversation_id: str
    ) -> ConversationRecord | None: ...

    async def list_conversations(
        self, *, principal_id: str, limit: int = 50
    ) -> Sequence[ConversationRecord]: ...

    async def append_turn(
        self,
        record: ConversationTurnRecord,
        *,
        allocate_index: bool = False,
    ) -> ConversationTurnRecord: ...

    async def get_turn_by_idempotency(
        self,
        *,
        principal_id: str,
        idempotency_key: str,
    ) -> ConversationTurnRecord | None: ...

    async def list_turns(
        self, *, principal_id: str, conversation_id: str, limit: int = 200
    ) -> Sequence[ConversationTurnRecord]: ...

    async def list_all_turns(
        self, *, principal_id: str, conversation_id: str
    ) -> Sequence[ConversationTurnRecord]: ...

    async def latest_operator_turn_ids(
        self,
        *,
        principal_id: str,
        conversation_ids: Sequence[str],
    ) -> Mapping[str, str]: ...

    async def delete_conversation(self, *, principal_id: str, conversation_id: str) -> bool: ...

    async def purge_inactive(
        self,
        *,
        before: datetime,
        limit: int = 100,
    ) -> Sequence[ConversationRecord]: ...


@runtime_checkable
class UserPreferenceStore(Protocol):
    async def get(self, *, principal_id: str) -> UserPreferenceRecord | None: ...

    async def put(
        self,
        record: UserPreferenceRecord,
        *,
        expected_revision: int | None = None,
    ) -> UserPreferenceRecord: ...

    async def delete(self, *, principal_id: str) -> bool: ...


def _validate_answer_intent_preferences(
    preferences: Mapping[str, str],
    *,
    values: set[str],
    field_name: str,
) -> None:
    intents = {
        "definition",
        "why",
        "procedure",
        "comparison",
        "diagnosis",
        "status",
        "list",
        "summary",
        "proposal",
        "open_question",
        "greeting",
    }
    if any(intent not in intents or value not in values for intent, value in preferences.items()):
        raise ValueError(f"UserPreferenceRecord.{field_name} is invalid")


@runtime_checkable
class UserMemoryStore(Protocol):
    async def create(self, fact: UserMemoryFact) -> UserMemoryFact: ...

    async def list_active(
        self, *, principal_id: str, now: datetime, limit: int = 100
    ) -> Sequence[UserMemoryFact]: ...

    async def supersede(self, *, principal_id: str, memory_id: str, superseded_by: str) -> None: ...

    async def delete(self, *, principal_id: str, memory_id: str) -> bool: ...

    async def purge_expired(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> Sequence[UserMemoryFact]: ...


def _require_text(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} MUST be non-empty")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} MUST be timezone-aware")


__all__ = [
    "ConversationHistoryStore",
    "ConversationRecord",
    "ConversationStatus",
    "ConversationTurnRecord",
    "ConversationTurnRole",
    "UserContextConflictError",
    "UserMemoryCategory",
    "UserMemoryFact",
    "UserMemoryStore",
    "UserPreferenceRecord",
    "UserPreferenceStore",
]
