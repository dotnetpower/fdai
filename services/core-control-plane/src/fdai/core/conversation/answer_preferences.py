"""Principal-scoped response preferences for deterministic answer planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from fdai.core.conversation.answer_plan import AnswerFormat, AnswerIntent, DetailLevel


@dataclass(frozen=True, slots=True)
class ResponsePreferenceProfile:
    """Explicit response-shape defaults owned by one operator principal."""

    locale: str
    default_detail: DetailLevel
    default_format: AnswerFormat
    intent_detail: Mapping[AnswerIntent, DetailLevel]
    intent_format: Mapping[AnswerIntent, AnswerFormat]
    explicit_only: bool
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.locale or not self.locale.strip():
            raise ValueError("ResponsePreferenceProfile.locale MUST be non-empty")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("ResponsePreferenceProfile.updated_at MUST be timezone-aware")

    def detail_for(self, intent: AnswerIntent) -> DetailLevel | None:
        if self.explicit_only:
            return None
        return self.intent_detail.get(intent, self.default_detail)

    def format_for(self, intent: AnswerIntent) -> AnswerFormat | None:
        if self.explicit_only:
            return None
        return self.intent_format.get(intent, self.default_format)


__all__ = ["ResponsePreferenceProfile"]
