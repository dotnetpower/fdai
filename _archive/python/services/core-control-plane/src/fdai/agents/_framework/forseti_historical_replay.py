"""Read-only historical judgment replay contracts for Forseti."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ForsetiHistoricalQualitySample:
    key: str
    event_type: str
    action_type: str
    risk_verdict: str
    judgment_table_digest: str
    tier: str
    observed_at: str
    evidence_refs: tuple[str, ...]

    def quality_sample(self) -> dict[str, str]:
        return {
            "event_type": self.event_type,
            "action_type": self.action_type,
            "risk_verdict": self.risk_verdict,
            "judgment_table_digest": self.judgment_table_digest,
            "tier": self.tier,
        }


@dataclass(frozen=True, slots=True)
class ForsetiHistoricalReplay:
    archive_ref: str
    content_digest: str
    source_revision: str
    review_ref: str
    window_started_at: str
    window_ended_at: str
    evidence_refs: tuple[str, ...]
    samples: tuple[ForsetiHistoricalQualitySample, ...]


class ForsetiHistoricalReplaySource(Protocol):
    async def read_replay(self, archive_ref: str) -> ForsetiHistoricalReplay | None:
        """Read one exact reviewed archive without granting runtime authority."""


__all__ = [
    "ForsetiHistoricalQualitySample",
    "ForsetiHistoricalReplay",
    "ForsetiHistoricalReplaySource",
]
