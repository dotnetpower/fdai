"""Conversation models owned by the Bragi narrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RoutingDecision:
    primary_agent: str | None
    scores: dict[str, float]
    tie_break: str | None
    contributors: tuple[str, ...] = ()


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
    turns: list[Turn] = field(default_factory=list)


__all__ = ["ConversationSession", "RoutingDecision", "Turn"]
