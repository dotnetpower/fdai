"""Conversation models owned by the Bragi narrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RoutingDecision:
    primary_agent: str | None
    scores: dict[str, float]
    tie_break: str | None
    contributors: tuple[str, ...] = ()
    method: str = "t0_abstain"
    semantic_score: float | None = None
    semantic_margin: float | None = None
    provider_status: str = "not_used"


@dataclass
class Turn:
    turn_index: int
    question: str
    primary_agent: str | None
    answer: dict[str, Any]
    decision: RoutingDecision


@dataclass
class ConversationSession:
    session_id: str
    user_id: str
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    ended_at: datetime | None = None
    generation: int = 1
    turns: list[Turn] = field(default_factory=list)
    conversation_published: bool = False
    conversation_publication_inflight: bool = False
    next_turn_index: int = 0


__all__ = ["ConversationSession", "RoutingDecision", "Turn"]
