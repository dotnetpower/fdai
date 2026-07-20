"""Human-reviewed, aggregate-only trajectory input for off-path learning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TrajectoryLearningAggregate:
    """Counts only; no prompts, conversation bodies, or tool payloads."""

    record_count: int
    outcome_counts: tuple[tuple[str, int], ...]
    tool_request_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.record_count < 1:
            raise ValueError("reviewed trajectory aggregate record_count MUST be positive")
        _ordered_counts("outcome_counts", self.outcome_counts)
        _ordered_counts("tool_request_counts", self.tool_request_counts)
        if sum(count for _, count in self.outcome_counts) != self.record_count:
            raise ValueError("reviewed trajectory outcome counts MUST equal record_count")


@dataclass(frozen=True, slots=True)
class ReviewedTrajectoryDataset:
    """Explicit human-review receipt plus bounded learning aggregate."""

    dataset_id: str
    manifest_checksum: str
    reviewed_by: str
    reviewed_at: datetime
    review_ref: str
    aggregate: TrajectoryLearningAggregate

    def __post_init__(self) -> None:
        if not all((self.dataset_id, self.reviewed_by, self.review_ref)):
            raise ValueError("reviewed trajectory identity fields MUST be non-empty")
        if _DIGEST.fullmatch(self.manifest_checksum) is None:
            raise ValueError("reviewed trajectory manifest_checksum MUST be SHA-256")
        if self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed trajectory reviewed_at MUST be timezone-aware")


def _ordered_counts(name: str, values: tuple[tuple[str, int], ...]) -> None:
    keys = tuple(key for key, _ in values)
    if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError(f"reviewed trajectory {name} MUST use unique sorted keys")
    if any(not key or count < 0 for key, count in values):
        raise ValueError(f"reviewed trajectory {name} MUST contain non-negative counts")


__all__ = ["ReviewedTrajectoryDataset", "TrajectoryLearningAggregate"]
