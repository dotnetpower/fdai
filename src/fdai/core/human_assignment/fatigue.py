"""Pure fatigue policy for proactive handover invitations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class HandoverFatiguePolicy:
    max_invitations_per_session: int = 1
    max_invitations_per_week: int = 2
    max_questions_per_session: int = 3
    max_session_minutes: int = 5
    snooze_hours: int = 24

    def __post_init__(self) -> None:
        for name in (
            "max_invitations_per_session",
            "max_invitations_per_week",
            "max_questions_per_session",
            "max_session_minutes",
            "snooze_hours",
        ):
            if not 1 <= getattr(self, name) <= 168:
                raise ValueError(f"{name} MUST be in [1, 168]")

    def week_key(self, at: datetime) -> str:
        if at.tzinfo is None:
            raise ValueError("fatigue timestamp MUST be timezone-aware")
        year, week, _ = at.isocalendar()
        return f"{year}-W{week:02d}"


__all__ = ["HandoverFatiguePolicy"]
