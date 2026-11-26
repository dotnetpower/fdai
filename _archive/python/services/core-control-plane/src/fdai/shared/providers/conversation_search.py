"""Access-scoped, read-only search over durable conversation turns."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.providers.user_context import ConversationTurnRole


class ConversationSearchMode(StrEnum):
    TERMS = "terms"
    PHRASE = "phrase"
    PREFIX = "prefix"


@dataclass(frozen=True, slots=True)
class ConversationSearchScope:
    """Server-resolved authorization boundary; filters can only narrow it."""

    principal_id: str
    allowed_channels: frozenset[str] = frozenset()
    allowed_conversation_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _bounded_text("ConversationSearchScope.principal_id", self.principal_id, maximum=256)
        _bounded_set("allowed_channels", self.allowed_channels, maximum=32)
        _bounded_set("allowed_conversation_ids", self.allowed_conversation_ids, maximum=1_000)


@dataclass(frozen=True, slots=True)
class ConversationSearchQuery:
    text: str
    mode: ConversationSearchMode = ConversationSearchMode.TERMS
    limit: int = 20
    context_turns: int = 1
    channels: tuple[str, ...] = ()
    roles: tuple[ConversationTurnRole, ...] = ()
    conversation_id: str | None = None
    incident_id: str | None = None
    correlation_id: str | None = None
    recorded_after: datetime | None = None
    recorded_before: datetime | None = None

    def __post_init__(self) -> None:
        _bounded_text("ConversationSearchQuery.text", self.text, maximum=256)
        if not any(char.isalnum() for char in self.text):
            raise ValueError("ConversationSearchQuery.text MUST contain a letter or digit")
        if not 1 <= self.limit <= 50:
            raise ValueError("ConversationSearchQuery.limit MUST be in [1, 50]")
        if not 0 <= self.context_turns <= 3:
            raise ValueError("ConversationSearchQuery.context_turns MUST be in [0, 3]")
        if len(self.channels) > 16 or len(set(self.channels)) != len(self.channels):
            raise ValueError("ConversationSearchQuery.channels MUST contain <= 16 unique values")
        if len(self.roles) > len(ConversationTurnRole) or len(set(self.roles)) != len(self.roles):
            raise ValueError("ConversationSearchQuery.roles MUST contain unique values")
        for channel in self.channels:
            _bounded_text("ConversationSearchQuery.channels", channel, maximum=128)
        for name, value in (
            ("conversation_id", self.conversation_id),
            ("incident_id", self.incident_id),
            ("correlation_id", self.correlation_id),
        ):
            if value is not None:
                _bounded_text(f"ConversationSearchQuery.{name}", value, maximum=256)
        for name, timestamp_value in (
            ("recorded_after", self.recorded_after),
            ("recorded_before", self.recorded_before),
        ):
            if timestamp_value is not None and timestamp_value.tzinfo is None:
                raise ValueError(f"ConversationSearchQuery.{name} MUST be timezone-aware")
        if (
            self.recorded_after is not None
            and self.recorded_before is not None
            and self.recorded_after >= self.recorded_before
        ):
            raise ValueError("recorded_after MUST be earlier than recorded_before")


@dataclass(frozen=True, slots=True)
class ConversationTextRange:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("ConversationTextRange requires 0 <= start < end")


@dataclass(frozen=True, slots=True)
class ConversationSearchSnippet:
    text: str
    highlights: tuple[ConversationTextRange, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text("ConversationSearchSnippet.text", self.text, maximum=600)
        if len(self.highlights) > 32:
            raise ValueError("ConversationSearchSnippet.highlights exceeds 32 ranges")
        prior_end = 0
        for highlight in self.highlights:
            if highlight.end > len(self.text) or highlight.start < prior_end:
                raise ValueError("ConversationSearchSnippet highlights MUST be ordered in bounds")
            prior_end = highlight.end


@dataclass(frozen=True, slots=True)
class ConversationSearchHit:
    result_id: str
    turn_id: str
    conversation_id: str
    channel_id: str
    role: ConversationTurnRole
    snippet: ConversationSearchSnippet
    recorded_at: datetime
    rank: float
    incident_id: str | None = None
    correlation_id: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("result_id", self.result_id),
            ("turn_id", self.turn_id),
            ("conversation_id", self.conversation_id),
            ("channel_id", self.channel_id),
        ):
            _bounded_text(f"ConversationSearchHit.{name}", value, maximum=256)
        if self.recorded_at.tzinfo is None:
            raise ValueError("ConversationSearchHit.recorded_at MUST be timezone-aware")
        if not 0.0 <= self.rank <= 1.0:
            raise ValueError("ConversationSearchHit.rank MUST be in [0, 1]")
        if len(self.evidence_refs) > 64:
            raise ValueError("ConversationSearchHit.evidence_refs exceeds 64 values")


@dataclass(frozen=True, slots=True)
class ConversationSearchPage:
    hits: tuple[ConversationSearchHit, ...]
    result_cap: int
    query_ms: float
    index_rows: int
    index_bytes: int

    def __post_init__(self) -> None:
        if len(self.hits) > self.result_cap or not 1 <= self.result_cap <= 50:
            raise ValueError("ConversationSearchPage result cap is invalid")
        if self.query_ms < 0 or self.index_rows < 0 or self.index_bytes < 0:
            raise ValueError("ConversationSearchPage measurements MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ConversationSearchContext:
    hit: ConversationSearchHit
    before: tuple[ConversationSearchHit, ...] = ()
    after: tuple[ConversationSearchHit, ...] = ()

    def __post_init__(self) -> None:
        if len(self.before) > 3 or len(self.after) > 3:
            raise ValueError("ConversationSearchContext neighbors exceed cap")


@dataclass(frozen=True, slots=True)
class ConversationLineage:
    conversation_id: str
    channel_id: str
    started_at: datetime
    last_active: datetime
    turn_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _bounded_text("ConversationLineage.conversation_id", self.conversation_id, maximum=256)
        _bounded_text("ConversationLineage.channel_id", self.channel_id, maximum=128)
        if self.started_at.tzinfo is None or self.last_active.tzinfo is None:
            raise ValueError("ConversationLineage timestamps MUST be timezone-aware")
        if len(self.turn_ids) > 1_000:
            raise ValueError("ConversationLineage.turn_ids exceeds cap")


@runtime_checkable
class ConversationSearch(Protocol):
    async def search(
        self,
        *,
        scope: ConversationSearchScope,
        query: ConversationSearchQuery,
    ) -> ConversationSearchPage: ...

    async def context(
        self,
        *,
        scope: ConversationSearchScope,
        result_id: str,
        before: int = 1,
        after: int = 1,
    ) -> ConversationSearchContext | None: ...

    async def lineage(
        self,
        *,
        scope: ConversationSearchScope,
        conversation_id: str,
    ) -> ConversationLineage | None: ...


def _bounded_text(name: str, value: str, *, maximum: int) -> None:
    if not value.strip() or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be bounded text without control characters")


def _bounded_set(name: str, values: frozenset[str], *, maximum: int) -> None:
    if len(values) > maximum:
        raise ValueError(f"ConversationSearchScope.{name} exceeds cap")
    for value in values:
        _bounded_text(f"ConversationSearchScope.{name}", value, maximum=256)


__all__ = [
    "ConversationLineage",
    "ConversationSearch",
    "ConversationSearchContext",
    "ConversationSearchHit",
    "ConversationSearchMode",
    "ConversationSearchPage",
    "ConversationSearchQuery",
    "ConversationSearchScope",
    "ConversationSearchSnippet",
    "ConversationTextRange",
]
