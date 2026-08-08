"""Bounded aggregate metrics for the post-turn review path."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PostTurnReviewMetricsSnapshot:
    eligible: int
    ineligible: int
    abstained: int
    duplicates: int
    routed: int
    failed: int


class PostTurnReviewMetrics:
    def __init__(self) -> None:
        self._counts = {
            "eligible": 0,
            "ineligible": 0,
            "abstained": 0,
            "duplicates": 0,
            "routed": 0,
            "failed": 0,
        }

    def increment(self, name: str) -> None:
        if name not in self._counts:
            raise ValueError(f"unknown post-turn review metric {name!r}")
        self._counts[name] += 1

    def snapshot(self) -> PostTurnReviewMetricsSnapshot:
        return PostTurnReviewMetricsSnapshot(**self._counts)


__all__ = ["PostTurnReviewMetrics", "PostTurnReviewMetricsSnapshot"]
