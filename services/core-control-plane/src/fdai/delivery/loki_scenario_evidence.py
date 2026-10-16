"""Immutable reviewed off-path scenario source for Loki."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.agents import ChaosScenarioCandidate


class ImmutableChaosScenarioSource:
    """Return reviewed inert candidates only for one exact design reference."""

    def __init__(
        self,
        *,
        design_ref: str,
        review_ref: str,
        candidates: tuple[ChaosScenarioCandidate, ...],
    ) -> None:
        self.design_ref = design_ref
        self.review_ref = review_ref
        self._candidates = candidates

    async def generate_scenarios(self, design_ref: str) -> Sequence[ChaosScenarioCandidate]:
        if design_ref != self.design_ref:
            raise ValueError("Loki scenario design reference differs from reviewed source")
        return self._candidates


__all__ = ["ImmutableChaosScenarioSource"]
