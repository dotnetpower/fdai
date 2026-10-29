"""Read-only Console inbox record for one A2 operational alert."""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

CONSOLE_INBOX_PREFIX: Final = "console-inbox:"

InboxSeverity = Literal["info", "warn", "error", "critical"]


class ConsoleInboxRecord(BaseModel):
    """A bounded, pre-redacted alert record that never grants authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    inbox_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    category: str = Field(min_length=1, max_length=128)
    trust_tier: Literal["a2_operational_alert"]
    severity: InboxSeverity
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=4000)
    correlation_id: str = Field(min_length=1, max_length=256)
    audit_id: str | None = Field(default=None, max_length=512)
    recorded_at: datetime
    execution_authority: Literal[False] = False


__all__ = ["CONSOLE_INBOX_PREFIX", "ConsoleInboxRecord", "InboxSeverity"]
